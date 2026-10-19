"""Build Bluesky link cards from a publisher's own sharing image."""

from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import warnings

import infobot as v1


MAX_IMAGE_DOWNLOAD = 10_000_000
MAX_THUMB_BYTES = 1_000_000
MAX_IMAGE_PIXELS = 40_000_000


class ImageMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = {key: [] for key in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        attrs = {key.lower(): value for key, value in attrs}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in self.images and attrs.get("content"):
            self.images[key].append(attrs["content"].strip())


def image_candidates(markup, article_url):
    metadata = ImageMetadata()
    metadata.feed(markup)
    candidates = []
    for values in metadata.images.values():
        for value in values:
            url = urljoin(article_url, value)
            if v1.https_url(url) and url not in candidates:
                candidates.append(url)
    return candidates[:6]


def check_image_address(url, publisher_url):
    try:
        if not v1.https_url(url) or urlsplit(url).port not in (None, 443):
            raise v1.SetupError("Publisher image must use a public HTTPS address.")
        host = urlsplit(url).hostname
        publisher = urlsplit(publisher_url).hostname.removeprefix("www.")
        if host != publisher and not host.endswith("." + publisher):
            raise v1.SetupError("Image host is outside the publisher's domain.")
    except (AttributeError, ValueError):
        raise v1.SetupError("Publisher image address is invalid.") from None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            raise v1.SetupError("Publisher image address is not public.")
    else:
        if not address.is_global:
            raise v1.SetupError("Publisher image address is not public.")


class ImageRedirect(HTTPRedirectHandler):
    def __init__(self, publisher_url):
        super().__init__()
        self.publisher_url = publisher_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_image_address(newurl, self.publisher_url)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_image(url, publisher_url):
    check_image_address(url, publisher_url)
    request = Request(url, headers={"User-Agent": "RESPOND-Infobot/0.4", "Accept": "image/jpeg, image/png, image/webp"})
    try:
        with build_opener(ImageRedirect(publisher_url)).open(request, timeout=20) as response:
            data = response.read(MAX_IMAGE_DOWNLOAD + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise v1.SetupError("Publisher image download failed or timed out.") from None
    if not data or len(data) > MAX_IMAGE_DOWNLOAD:
        raise v1.SetupError("Publisher image is empty or exceeds the download limit.")
    return data


def thumbnail(data):
    """Retain the photograph and its aspect ratio; strip metadata and fit the API."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise v1.SetupError("Install requirements-v2.txt to prepare publisher images.") from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as original:
                if original.width * original.height > MAX_IMAGE_PIXELS:
                    raise v1.SetupError("Publisher image dimensions exceed the processing limit.")
                original.load()
                image = ImageOps.exif_transpose(original).copy()
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        if "A" in image.getbands() or "transparency" in image.info:
            image = image.convert("RGBA")
            image.info.clear()
            output = BytesIO()
            image.save(output, format="PNG", optimize=True)
            if len(output.getvalue()) <= MAX_THUMB_BYTES:
                return output.getvalue(), "image/png", image.width, image.height
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        image.info.clear()
        # No EXIF, ICC or other publisher metadata is copied into the thumbnail.
        for _ in range(5):
            for quality in (90, 80, 65):
                output = BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                if len(output.getvalue()) <= MAX_THUMB_BYTES:
                    return output.getvalue(), "image/jpeg", image.width, image.height
            image = image.resize((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise v1.SetupError("Publisher image is unsupported, invalid or too large to decode.") from None
    raise v1.SetupError("Publisher image cannot fit Bluesky's thumbnail limit.")


def prepare_card(article, download_html):
    markup = download_html(article["link"]).decode("utf-8", errors="replace")
    urls = image_candidates(markup, article["link"])
    if not urls:
        raise v1.SetupError("No publisher sharing image found; article held for review.")
    for url in urls:
        try:
            data, mime, width, height = thumbnail(download_image(url, article["link"]))
            return {"image_url": url, "image_bytes": data, "mime_type": mime,
                    "width": width, "height": height}
        except v1.SetupError:
            continue
    raise v1.SetupError("Publisher sharing images could not be prepared; article held for review.")


def card_preview(card):
    return {key: card[key] for key in ("image_url", "mime_type", "width", "height")}


def upload_thumbnail(client, card):
    request = Request(client.service + "/xrpc/com.atproto.repo.uploadBlob",
                      data=card["image_bytes"], method="POST",
                      headers={"Authorization": "Bearer " + client.token,
                               "Content-Type": card["mime_type"], "User-Agent": "RESPOND-Infobot/0.4"})
    try:
        response = json.loads(v1.read_response(request, "Bluesky image upload"))
        blob = response["blob"]
        if (blob.get("$type") != "blob" or blob.get("mimeType") != card["mime_type"]
                or type(blob.get("size")) is not int or not 0 < blob["size"] <= MAX_THUMB_BYTES
                or not isinstance(blob.get("ref"), dict) or not blob["ref"].get("$link")):
            raise ValueError("Invalid blob")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise v1.SetupError("Bluesky returned an invalid image-upload response.") from None
    return blob


def embed(article, thumb):
    title = article["title"]
    if len(title) > 300:
        title = title[:299].rstrip() + "…"
    return {"$type": "app.bsky.embed.external", "external": {
        "uri": article["link"], "title": title, "description": "", "thumb": thumb}}
