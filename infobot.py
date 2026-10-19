"""RESPOND Infobot, setup stage: read RSS and verify login without posting.

Python 3.12+, standard library only. There is deliberately no publishing API
call or scheduler in this setup version. Run `python infobot.py` for a feed
preview, or `python infobot.py --check-login` to also check GitHub credentials.
"""

import argparse
import html
import json
import os
from pathlib import Path
import sys
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


MAX_RESPONSE_BYTES = 2_000_000
TIMEOUT_SECONDS = 25
LOGIN_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"


class SetupError(Exception):
    """A setup problem whose message is safe to show in public logs."""


def clean_text(value):
    value = unicodedata.normalize("NFC", html.unescape(value or ""))
    value = " ".join(value.split())
    # RSS titles are plain text; remove control characters from log output.
    value = "".join(c for c in value if not unicodedata.category(c).startswith("C"))
    return " ".join(value.split())


def https_url(value):
    try:
        parts = urlsplit(value)
        return (
            parts.scheme == "https"
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and not any(c.isspace() or ord(c) < 32 for c in value)
        )
    except ValueError:
        return False


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError("Cannot read config.json. Check that it contains valid JSON.") from exc
    if not isinstance(config, dict):
        raise SetupError("config.json must contain a JSON object.")
    source = config.get("source_name")
    feed = config.get("feed_url")
    count = config.get("preview_count")
    if not isinstance(source, str) or not clean_text(source):
        raise SetupError("Set source_name in config.json.")
    if not isinstance(feed, str) or not https_url(feed):
        raise SetupError("Set feed_url to a complete HTTPS RSS feed address.")
    if type(count) is not int or not 1 <= count <= 10:
        raise SetupError("preview_count must be a whole number from 1 to 10.")
    return {"source_name": clean_text(source), "feed_url": feed, "preview_count": count}


def read_response(request, description):
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        # Do not print response bodies or request headers: login data is private.
        if description == "Bluesky login" and exc.code in (400, 401, 403):
            raise SetupError(
                "Bluesky rejected the login. Check BSKY_HANDLE and BSKY_APP_PASSWORD "
                "in GitHub Actions secrets. Use an app password, not the main password."
            ) from None
        raise SetupError(f"{description} failed with HTTP status {exc.code}. Try again later.") from None
    except (URLError, TimeoutError, OSError):
        raise SetupError(f"{description} could not connect or timed out. Try again later.") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise SetupError(f"{description} returned an unexpectedly large response.")
    return body


def parse_feed(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise SetupError("The feed contains unsupported XML declarations.")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise SetupError("The feed did not return valid RSS XML. Check the feed URL.") from None
    if root.tag != "rss" or root.find("channel") is None:
        raise SetupError("The address did not return an RSS 2.0 feed. Check the feed URL.")
    articles = []
    seen_links = set()
    for item in root.findall("./channel/item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not title or not https_url(link):
            continue
        if link not in seen_links:
            articles.append({"title": title, "link": link})
            seen_links.add(link)
    if not articles:
        raise SetupError("The feed contains no usable articles. Check its address and contents.")
    return articles


def preview_text(article, source):
    suffix = f"\n\nSource: {source}\n{article['link']}"
    available = 300 - len(suffix)
    if available < 2:
        raise SetupError("The source name and article link are too long for a preview post.")
    title = article["title"]
    if len(title) > available:
        title = title[: available - 1].rstrip() + "…"
    # A conservative code-point limit also stays within Bluesky's grapheme limit.
    return title + suffix


def check_login():
    handle = os.environ.get("BSKY_HANDLE", "").strip().lstrip("@")
    password = os.environ.get("BSKY_APP_PASSWORD", "").strip()
    if not handle or not password:
        raise SetupError(
            "Missing GitHub Actions secrets. Add BSKY_HANDLE and BSKY_APP_PASSWORD "
            "under Settings > Secrets and variables > Actions."
        )
    request = Request(
        LOGIN_URL,
        data=json.dumps({"identifier": handle, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "RESPOND-Infobot-Setup/0.1"},
        method="POST",
    )
    body = read_response(request, "Bluesky login")
    try:
        session = json.loads(body)
    except ValueError:
        raise SetupError("Bluesky returned an unexpected login response.") from None
    if not isinstance(session, dict) or not all(
        isinstance(session.get(key), str) and session[key]
        for key in ("handle", "did", "accessJwt")
    ):
        raise SetupError("Bluesky did not return a valid login session.")
    if session.get("active") is False:
        raise SetupError("The Bluesky account is not active. Check the account in Bluesky.")
    # Neither tokens nor passwords are saved or printed.
    return session["handle"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--check-login", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    request = Request(
        config["feed_url"],
        headers={"Accept": "application/rss+xml, application/xml, text/xml", "User-Agent": "RESPOND-Infobot-Setup/0.1"},
    )
    articles = parse_feed(read_response(request, "RSS feed download"))
    print(f"Feed OK: {len(articles)} usable articles.")
    for index, article in enumerate(articles[: config["preview_count"]], 1):
        print(f"\nPREVIEW {index} (not published):")
        # JSON quoting prevents feed titles from being interpreted as log commands.
        print(json.dumps(preview_text(article, config["source_name"]), ensure_ascii=False))
    if args.check_login:
        handle = check_login()
        print("\nBluesky login OK: " + json.dumps(handle))
    else:
        print("\nBluesky login was not checked. Use --check-login to check it.")
    print("\nPreview finished. No posts were published.")


if __name__ == "__main__":
    try:
        main()
    except SetupError as exc:
        print(f"Setup check failed: {exc}", file=sys.stderr)
        sys.exit(1)
