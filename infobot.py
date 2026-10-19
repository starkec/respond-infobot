"""RESPOND Infobot: preview, publish one test article, or publish new RSS items.

Python 3.12+, standard library only. The default mode is preview (no writes).
The GitHub workflow gates scheduled posting with INFOBOT_ENABLED=true.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


MAX_RESPONSE_BYTES = 2_000_000
TIMEOUT_SECONDS = 25
LOGIN_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"
POST_COLLECTION = "app.bsky.feed.post"
PROFILE_COLLECTION = "app.bsky.actor.profile"
TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


class SetupError(Exception):
    """A setup problem whose message is safe to show in public logs."""


class APIError(SetupError):
    def __init__(self, status, code, description):
        self.status = status
        self.code = code
        super().__init__(f"{description} failed (HTTP {status}, {code}).")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    maximum = config.get("max_posts_per_run", 5)
    if type(maximum) is not int or not 1 <= maximum <= 10:
        raise SetupError("max_posts_per_run must be a whole number from 1 to 10.")
    return {"source_name": clean_text(source), "feed_url": feed,
            "preview_count": count, "max_posts_per_run": maximum}


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
        try:
            code = json.loads(exc.read(4096)).get("error", "RequestFailed")
        except (ValueError, AttributeError):
            code = "RequestFailed"
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,60}", code):
            code = "RequestFailed"
        raise APIError(exc.code, code, description) from None
    except (URLError, TimeoutError, OSError):
        raise SetupError(f"{description} could not connect or timed out. Try again later.") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise SetupError(f"{description} returned an unexpectedly large response.")
    return body


def canonical_url(url):
    """Ignore tracking parameters and fragments when identifying an article."""
    parts = urlsplit(url)
    tracking = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in tracking]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


def article_id(article):
    return hashlib.sha256(canonical_url(article["link"]).encode("utf-8")).hexdigest()


def record_key(article):
    # Stable URL-derived identifier in valid TID syntax. Its timestamp component
    # is intentionally not a wall-clock time; the post's createdAt is the real
    # posting time. A stable key allows recovery after an ambiguous API response
    # or failed GitHub state commit. Existing records are never overwritten.
    number = int(article_id(article)[:16], 16) & ((1 << 63) - 1)
    digits = []
    for _ in range(13):
        digits.append(TID_ALPHABET[number & 31])
        number >>= 5
    return "".join(reversed(digits))


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
        link = canonical_url(link)
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


def post_record(article, source):
    text = preview_text(article, source)
    start = len(text[: text.rfind(article["link"])].encode("utf-8"))
    end = start + len(article["link"].encode("utf-8"))
    return {
        "$type": POST_COLLECTION,
        "text": text,
        "createdAt": utc_now(),
        "langs": ["en"],
        "facets": [{
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": article["link"]}],
        }],
    }


class BlueskyClient:
    def __init__(self, session):
        self.did = session["did"]
        self.handle = session["handle"]
        self.token = session["accessJwt"]
        self.service = "https://bsky.social"
        for service in session.get("didDoc", {}).get("service", []):
            if service.get("type") == "AtprotoPersonalDataServer":
                endpoint = service.get("serviceEndpoint")
                if not isinstance(endpoint, str) or not https_url(endpoint):
                    raise SetupError("Bluesky returned an invalid account server address.")
                self.service = endpoint.rstrip("/")
                break

    def call(self, method, payload=None, parameters=None):
        url = self.service + "/xrpc/" + method
        if parameters:
            url += "?" + urlencode(parameters)
        headers = {"Authorization": "Bearer " + self.token,
                   "User-Agent": "RESPOND-Infobot/0.2"}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers,
                          method="POST" if data is not None else "GET")
        try:
            result = json.loads(read_response(request, "Bluesky API"))
        except ValueError:
            raise SetupError("Bluesky returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise SetupError("Bluesky returned an unexpected API response.")
        return result

    def get_record(self, collection, key):
        try:
            result = self.call("com.atproto.repo.getRecord", parameters={
                "repo": self.did, "collection": collection, "rkey": key})
        except APIError as exc:
            if exc.code == "RecordNotFound" and exc.status in (400, 404):
                return None
            raise
        if not isinstance(result.get("value"), dict) or not result.get("uri") or not result.get("cid"):
            raise SetupError("Bluesky returned an incomplete record.")
        return result

    def put_record(self, collection, key, value, previous_cid=None):
        return self.call("com.atproto.repo.putRecord", payload={
            "repo": self.did, "collection": collection, "rkey": key,
            "record": value, "validate": True,
            # null means the record must not exist; a CID protects profile edits.
            "swapRecord": previous_cid,
        })


def login():
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
    return BlueskyClient(session)


def check_login():
    """Retain compatibility with the earlier preview workflow."""
    return login().handle


def ensure_bot_label(client):
    existing = client.get_record(PROFILE_COLLECTION, "self")
    profile = deepcopy(existing["value"]) if existing else {"$type": PROFILE_COLLECTION}
    labels = profile.setdefault("labels", {"$type": "com.atproto.label.defs#selfLabels", "values": []})
    values = labels.get("values") if isinstance(labels, dict) else None
    if not isinstance(values, list):
        raise SetupError("The profile labels have an unexpected format. No profile changes made.")
    if any(isinstance(value, dict) and value.get("val") == "bot" for value in values):
        return
    values.append({"val": "bot"})
    client.put_record(PROFILE_COLLECTION, "self", profile,
                      previous_cid=existing["cid"] if existing else None)
    print("Bot label added; existing profile fields preserved.")


def existing_post_uri(record, article, client):
    expected = f"at://{client.did}/{POST_COLLECTION}/{record_key(article)}"
    if record.get("uri") != expected:
        raise SetupError("An unexpected record URI was returned. Publishing stopped.")
    value = record.get("value", {})
    links = [feature.get("uri") for facet in value.get("facets", [])
             for feature in facet.get("features", [])
             if feature.get("$type") == "app.bsky.richtext.facet#link"]
    if article["link"] not in links:
        raise SetupError("A record key is already used by different content. Nothing was overwritten.")
    return expected


def publish_article(client, article, source):
    key = record_key(article)
    existing = client.get_record(POST_COLLECTION, key)
    if existing:
        return existing_post_uri(existing, article, client), False
    try:
        result = client.put_record(POST_COLLECTION, key, post_record(article, source))
    except SetupError:
        # A timeout may happen after the server accepted a post. Read back the
        # same key; never create a second key or blindly repeat the write.
        recovered = client.get_record(POST_COLLECTION, key)
        if recovered:
            return existing_post_uri(recovered, article, client), False
        raise
    expected = f"at://{client.did}/{POST_COLLECTION}/{key}"
    if result.get("uri") != expected:
        raise SetupError("The publish response was unexpected. Rerun to reconcile the record.")
    return expected, True


def load_state(path, client, config):
    path = Path(path)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SetupError("Cannot read data/state.json. Restore the last valid version; do not delete it.") from None
    if not isinstance(state, dict) or state.get("version") != 1:
        raise SetupError("The saved state has an unsupported format.")
    if state.get("account_did") != client.did or state.get("feed_url") != config["feed_url"]:
        raise SetupError("The saved state belongs to another account or feed. Publishing stopped.")
    if (not isinstance(state.get("seen"), list)
            or not all(isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key) for key in state["seen"])
            or not isinstance(state.get("posted"), dict)):
        raise SetupError("The saved article history is invalid. Restore the last valid state file.")
    return state


def save_state(path, state):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        raise SetupError("Cannot save article history. Check repository write permissions and rerun.") from None


def run_cycle(client, articles, config, state_path, mode):
    state = load_state(state_path, client, config)
    if state is None:
        if mode != "test-post":
            raise SetupError("No article history exists. Run test-post once before enabling automatic posting.")
        state = {"version": 1, "account_did": client.did, "feed_url": config["feed_url"],
                 "started_at": utc_now(), "last_checked_date": None,
                 "seen": sorted({article_id(article) for article in articles}), "posted": {}}
        save_state(state_path, state)
        print(f"Initialised history: {len(state['seen'])} existing articles recorded; no backlog will be posted.")
    seen = set(state["seen"])
    if mode == "test-post":
        selected = articles[:1]
    else:
        selected = [article for article in reversed(articles) if article_id(article) not in seen]
        selected = selected[: config["max_posts_per_run"]]
    if selected:
        ensure_bot_label(client)
    for article in selected:
        uri, created = publish_article(client, article, config["source_name"])
        key = article_id(article)
        seen.add(key)
        state["seen"] = sorted(seen)
        state["posted"][key] = uri
        save_state(state_path, state)
        verb = "Published" if created else "Already published; duplicate skipped"
        print(verb + ": " + json.dumps(article["title"], ensure_ascii=False))
        print("Post URL: https://bsky.app/profile/" + client.did + "/post/" + record_key(article))
    # A once-per-day successful-check date gives durable health information
    # and repository activity without a new commit for every empty feed check.
    state["last_checked_date"] = utc_now()[:10]
    save_state(state_path, state)
    if not selected:
        print("No new articles. Nothing published.")
    print("Run finished. Article history saved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--check-login", action="store_true")
    parser.add_argument("--mode", choices=("preview", "test-post", "run"), default="preview")
    parser.add_argument("--state", default="data/state.json")
    args = parser.parse_args()
    config = load_config(args.config)
    request = Request(
        config["feed_url"],
        headers={"Accept": "application/rss+xml, application/xml, text/xml", "User-Agent": "RESPOND-Infobot-Setup/0.1"},
    )
    articles = parse_feed(read_response(request, "RSS feed download"))
    print(f"Feed OK: {len(articles)} usable articles.")
    if args.mode != "preview":
        client = login()
        print("Bluesky login OK: " + json.dumps(client.handle))
        run_cycle(client, articles, config, args.state, args.mode)
        return
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
