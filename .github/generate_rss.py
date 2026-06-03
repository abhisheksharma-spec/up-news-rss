%%writefile generate_rss.py
import argparse
import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return html.unescape(text).strip()


def is_valid_url(url):
    parsed = urlparse(url)
    return parsed.scheme in ["http", "https"] and parsed.netloc


def fetch_html(url, timeout=15):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_date(date_text):
    if not date_text:
        return None

    try:
        dt = date_parser.parse(date_text)

        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)

        return format_datetime(dt)

    except Exception:
        return None


def get_channel_title(soup, url):
    og_title = soup.select_one('meta[property="og:site_name"]')

    if og_title and og_title.get("content"):
        return clean_text(og_title["content"])

    title = soup.find("title")

    if title:
        return clean_text(title.get_text())

    return urlparse(url).netloc


def get_channel_description(soup):
    meta_desc = soup.select_one('meta[name="description"]')

    if meta_desc and meta_desc.get("content"):
        return clean_text(meta_desc["content"])

    og_desc = soup.select_one('meta[property="og:description"]')

    if og_desc and og_desc.get("content"):
        return clean_text(og_desc["content"])

    return "Auto-generated RSS feed"


def extract_items_generic(soup, page_url, limit=30):
    items = []
    seen_links = set()

    for a_tag in soup.find_all("a", href=True):
        title = clean_text(a_tag.get_text(" "))

        if not title or len(title) < 15:
            continue

        link = urljoin(page_url, a_tag["href"])

        if not is_valid_url(link):
            continue

        if link in seen_links:
            continue

        seen_links.add(link)

        parent = a_tag.find_parent(["article", "div", "li", "section"])

        description = ""

        if parent:
            paragraph = parent.find("p")

            if paragraph:
                description = clean_text(paragraph.get_text(" "))

        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pub_date": None,
            }
        )

        if len(items) >= limit:
            break

    return items


def extract_items_with_selectors(
    soup,
    page_url,
    item_selector,
    title_selector,
    link_selector,
    desc_selector=None,
    date_selector=None,
    limit=30,
):
    items = []
    seen_links = set()

    for block in soup.select(item_selector):
        title_node = block.select_one(title_selector) if title_selector else None
        link_node = block.select_one(link_selector) if link_selector else None

        if not title_node or not link_node:
            continue

        title = clean_text(title_node.get_text(" "))
        href = link_node.get("href")

        if not href:
            continue

        link = urljoin(page_url, href)

        if not title or not is_valid_url(link):
            continue

        if link in seen_links:
            continue

        seen_links.add(link)

        description = ""

        if desc_selector:
            desc_node = block.select_one(desc_selector)

            if desc_node:
                description = clean_text(desc_node.get_text(" "))

        pub_date = None

        if date_selector:
            date_node = block.select_one(date_selector)

            if date_node:
                date_text = (
                    date_node.get("datetime")
                    or date_node.get_text(" ")
                )

                pub_date = parse_date(clean_text(date_text))

        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
            }
        )

        if len(items) >= limit:
            break

    return items


def build_rss(channel_title, channel_link, channel_description, items):
    rss = Element("rss", version="2.0")

    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = channel_title
    SubElement(channel, "link").text = channel_link
    SubElement(channel, "description").text = channel_description
    SubElement(channel, "language").text = "hi-IN"

    SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )

    for item_data in items:
        item = SubElement(channel, "item")

        SubElement(item, "title").text = item_data["title"]
        SubElement(item, "link").text = item_data["link"]
        SubElement(item, "guid").text = item_data["link"]

        description = (
            item_data.get("description")
            or item_data["title"]
        )

        SubElement(item, "description").text = description

        if item_data.get("pub_date"):
            SubElement(item, "pubDate").text = item_data["pub_date"]

    raw_xml = tostring(rss, encoding="utf-8")

    return minidom.parseString(raw_xml).toprettyxml(indent="  ")


def main():
    parser = argparse.ArgumentParser(
        description="Generate RSS feed from webpage"
    )

    parser.add_argument("url")
    parser.add_argument(
        "-o",
        "--output",
        default="rss.xml"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=30
    )

    parser.add_argument("--item-selector")
    parser.add_argument("--title-selector")
    parser.add_argument("--link-selector")
    parser.add_argument("--desc-selector")
    parser.add_argument("--date-selector")

    args = parser.parse_args()

    html_source = fetch_html(args.url)

    soup = BeautifulSoup(
        html_source,
        "lxml"
    )

    channel_title = get_channel_title(
        soup,
        args.url
    )

    channel_description = get_channel_description(
        soup
    )

    if args.item_selector:
        if (
            not args.title_selector
            or not args.link_selector
        ):
            raise ValueError(
                "title-selector and link-selector required"
            )

        items = extract_items_with_selectors(
            soup=soup,
            page_url=args.url,
            item_selector=args.item_selector,
            title_selector=args.title_selector,
            link_selector=args.link_selector,
            desc_selector=args.desc_selector,
            date_selector=args.date_selector,
            limit=args.limit,
        )

    else:
        items = extract_items_generic(
            soup=soup,
            page_url=args.url,
            limit=args.limit,
        )

    if not items:
        raise RuntimeError(
            "No feed items found."
        )

    rss_xml = build_rss(
        channel_title=channel_title,
        channel_link=args.url,
        channel_description=channel_description,
        items=items,
    )

    with open(
        args.output,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(rss_xml)

    print(
        f"RSS feed generated: {args.output}"
    )

    print(
        f"Items found: {len(items)}"
    )


if __name__ == "__main__":
    main()
