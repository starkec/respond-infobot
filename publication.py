"""Publisher attribution and licence checks for plain-text headline/link posts.

No image is downloaded, uploaded or embedded, regardless of publisher policy.
Article-specific licence exceptions or missing credits create review holds.
"""

from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

import bot_common as common


POLICIES = {
    "EDJNet": ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "Mongabay": ("CC BY-ND 4.0", "https://creativecommons.org/licenses/by-nd/4.0/"),
    "Global Voices": ("CC BY 3.0", "https://creativecommons.org/licenses/by/3.0/"),
}


def validate_feed_policy(feed):
    policy = feed.get("image_policy", "omit")
    if policy != "omit":
        raise common.SetupError("Images are disabled for every publisher.")
    if feed["source_name"] in POLICIES:
        name, url = POLICIES[feed["source_name"]]
        if (policy != "omit" or feed.get("license_name") != name
                or feed.get("license_url") != url or feed.get("language") != "en"):
            raise common.SetupError("Openly licensed sources require English, full credits and no automatic photo reuse.")


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.authors = []
        self.licences = []
        self.skip = 0
        self.json_ld = False
        self.script = []
        self.structured_authors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "nav", "footer", "aside"):
            self.skip += 1
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.json_ld = True
            self.script = []
        if tag == "meta" and attrs.get("name", "").lower() == "author" and attrs.get("content"):
            self.authors.append(attrs["content"])
        if tag == "a":
            url = attrs.get("href", "")
            parts = urlsplit(url)
            if parts.hostname == "creativecommons.org" and parts.path.startswith("/licenses/"):
                self.licences.append("https://creativecommons.org" + parts.path.rstrip("/") + "/")

    def handle_endtag(self, tag):
        if tag == "script" and self.json_ld:
            try:
                data = json.loads("".join(self.script))
                nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
                for node in nodes:
                    if isinstance(node, dict) and node.get("@type") == "Person" and isinstance(node.get("name"), str):
                        self.structured_authors.append(node["name"])
            except (ValueError, TypeError):
                pass
            self.json_ld = False
        if tag in ("script", "style", "nav", "footer", "aside"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, value):
        if self.json_ld:
            self.script.append(value)
        if not self.skip and value.strip():
            self.parts.append(common.clean_text(value))


def labelled_value(parts, label):
    for index, part in enumerate(parts[:-1]):
        if re.fullmatch(label + r"\s*:?", part, re.I):
            return parts[index + 1]
        match = re.fullmatch(label + r"\s*:\s*(.+)", part, re.I)
        if match:
            return match[1]
    return ""


def prepare_attribution(article, download):
    validate_feed_policy(article)
    metadata = Metadata()
    metadata.feed(download(article["link"]).decode("utf-8", errors="replace"))
    expected = article["license_url"]
    licence = labelled_value(metadata.parts, r"Licen[cs]e")
    # EDJNet's licence text links to its policy page, rather than to CC itself.
    edjnet_by4 = article["source_name"] == "EDJNet" and "CC BY 4.0" in licence
    # Mongabay's new article template does not repeat its default text licence;
    # CC links inside photo captions describe photographs, not the article text.
    mongabay_default = article["source_name"] == "Mongabay" and not licence
    if not (edjnet_by4 or mongabay_default) and expected not in metadata.licences:
        raise common.SetupError("Article licence is missing or differs from the configured reuse terms; held for review.")
    if article["source_name"] == "EDJNet" and not edjnet_by4:
        raise common.SetupError("EDJNet article has nonstandard licence terms; held for review.")
    text = " ".join(metadata.parts)
    if re.search(r"(?:this (?:article|story)|article text).{0,100}(?:not (?:available|permitted|licensed) for repub|may not be repub|all rights reserved)", text, re.I):
        raise common.SetupError("Article states a republication restriction; held for review.")
    # RSS dc:creator is the story byline; WordPress's meta author may instead
    # name the editor/uploader (as in Mongabay's current template).
    author = (labelled_value(metadata.parts, r"Author(?:/s|s)?")
              or article.get("author", "") or ", ".join(metadata.authors)
              or ", ".join(metadata.structured_authors))
    author = common.clean_text(author)
    if not author or len(author) > 180:
        raise common.SetupError("Article author credit is missing or too long; held for review.")
    article["author"] = author
    member = labelled_value(metadata.parts, r"Source(?:/s|s)?") if article["source_name"] == "EDJNet" else ""
    original = labelled_value(metadata.parts, r"Original source") if article["source_name"] == "EDJNet" else ""
    if not member and common.https_url(original):
        member = urlsplit(original).hostname.removeprefix("www.")
    if member and member != article["source_name"]:
        article["credit_source"] = common.clean_text(member) + " | EDJNet"
    if article["source_name"] == "EDJNet" and not member:
        raise common.SetupError("EDJNet producing-outlet credit is missing; held for review.")
    # Verify that the public post fits without dropping any attribution.
    common.preview_text(article, article["source_name"])
    result = {"format": "text-only", "source": article.get("credit_source", article["source_name"]),
              "author": author, "license_name": article["license_name"], "license_url": expected}
    if original:
        result["original_publisher_url"] = original
    return result
