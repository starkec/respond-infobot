"""Publisher image/link-card tests: no network, credentials or real posts."""

from io import BytesIO
import importlib.util
import json
import os
import unittest
from unittest.mock import patch

import bot_common as common
import publisher_images as images


ARTICLE = {"title": "The publisher's original headline", "link": "https://example.org/story"}
CARD = {"image_url": "https://media.example.org/photo.jpg", "image_bytes": b"image-bytes",
        "mime_type": "image/jpeg", "width": 1200, "height": 630}
BLOB = {"$type": "blob", "mimeType": "image/jpeg", "size": 11, "ref": {"$link": "fake-cid"}}


class MetadataTests(unittest.TestCase):
    def test_publisher_og_image_preferred_over_twitter_and_relative_urls_resolved(self):
        markup = '''<meta property="og:description" content="An unwanted summary">
        <meta NAME="twitter:image" content="//media.example.org/twitter.jpg">
        <meta property="og:image" content="/photo.jpg?a=1&amp;b=2">
        <meta property="og:image:secure_url" content="https://media.example.org/original.jpg">'''
        self.assertEqual(images.image_candidates(markup, ARTICLE["link"]), [
            "https://media.example.org/original.jpg", "https://example.org/photo.jpg?a=1&b=2",
            "https://media.example.org/twitter.jpg"])

    def test_non_https_and_non_metadata_images_are_not_substituted(self):
        markup = '<img src="https://example.org/advert.jpg"><meta property="og:image" content="javascript:alert(1)">'
        self.assertEqual(images.image_candidates(markup, ARTICLE["link"]), [])

    def test_missing_metadata_holds_instead_of_inventing_a_picture(self):
        with self.assertRaises(common.SetupError):
            images.prepare_card(ARTICLE, lambda url: b'<html><p>No image</p></html>')

    def test_broken_primary_image_can_fall_back_to_another_publisher_image(self):
        markup = b'<meta property="og:image" content="/broken.jpg"><meta name="twitter:image" content="/photo.jpg">'
        with patch.object(images, "download_image", side_effect=[common.SetupError("Unavailable"), b"valid"]), patch.object(images, "thumbnail", return_value=(b"thumbnail", "image/jpeg", 1200, 630)):
            card = images.prepare_card(ARTICLE, lambda url: markup)
        self.assertEqual(card["image_url"], "https://example.org/photo.jpg")
        self.assertEqual(card["image_bytes"], b"thumbnail")

    def test_card_has_original_title_image_and_link_without_any_summary(self):
        card = images.embed(ARTICLE, BLOB)
        self.assertEqual(card["$type"], "app.bsky.embed.external")
        self.assertEqual(card["external"], {"uri": ARTICLE["link"], "title": ARTICLE["title"],
                                            "description": "", "thumb": BLOB})
        self.assertEqual(len(images.embed({**ARTICLE, "title": "x" * 500}, BLOB)["external"]["title"]), 300)


class DownloadAndUploadTests(unittest.TestCase):
    def test_private_local_unencrypted_and_invalid_port_addresses_rejected(self):
        for url in ("https://localhost/photo", "http://example.org/photo", "https://example.org:123/photo", "https://example.org:bad/photo", "https://127.0.0.1/photo", "https://example.org.evil.example/photo"):
            with self.subTest(url=url), self.assertRaises(common.SetupError):
                images.check_image_address(url, ARTICLE["link"])

    def test_publisher_cdn_subdomains_work_without_local_dns_resolution(self):
        images.check_image_address("https://media.example.org/photo.jpg", ARTICLE["link"])

    def test_image_redirects_are_checked_before_the_request(self):
        request = images.Request("https://media.example.org/a.jpg")
        with patch.object(images, "check_image_address", side_effect=common.SetupError("Private")) as check:
            with self.assertRaises(common.SetupError):
                images.ImageRedirect(ARTICLE["link"]).redirect_request(request, None, 302, "", {}, "https://localhost/secret")
        check.assert_called_once_with("https://localhost/secret", ARTICLE["link"])

    def test_image_download_size_is_bounded(self):
        with patch.object(images, "MAX_IMAGE_DOWNLOAD", 10), patch.object(images, "check_image_address"), patch.object(images, "build_opener") as opener:
            opener.return_value.open.return_value = BytesIO(b"x" * 11)
            with self.assertRaises(common.SetupError):
                images.download_image(CARD["image_url"], ARTICLE["link"])

    def test_upload_uses_binary_bytes_and_validates_blob(self):
        client = common.BlueskyClient({"did": "did:plc:example", "handle": "example.bsky.social", "accessJwt": "fake-private-token"})
        with patch.object(common, "read_response", return_value=json.dumps({"blob": BLOB}).encode()) as call:
            self.assertEqual(images.upload_thumbnail(client, CARD), BLOB)
        request = call.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/xrpc/com.atproto.repo.uploadBlob"))
        self.assertEqual(request.data, CARD["image_bytes"])
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-private-token")

    def test_bad_or_oversize_upload_responses_cannot_be_used_in_a_post(self):
        client = common.BlueskyClient({"did": "did:plc:example", "handle": "example.bsky.social", "accessJwt": "fake-token"})
        for value in ({}, {"blob": {**BLOB, "size": 1_000_001}}, {"blob": {**BLOB, "mimeType": "image/png"}}, []):
            with self.subTest(value=value), patch.object(common, "read_response", return_value=json.dumps(value).encode()):
                with self.assertRaises(common.SetupError):
                    images.upload_thumbnail(client, CARD)


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow image processing is installed by the v2 workflow")
class ThumbnailTests(unittest.TestCase):
    def test_large_photo_is_resized_without_cropping_and_fits_bluesky(self):
        from PIL import Image
        original = Image.frombytes("RGB", (2000, 1500), os.urandom(2000 * 1500 * 3))
        source = BytesIO()
        original.save(source, format="PNG")
        data, mime, width, height = images.thumbnail(source.getvalue())
        self.assertLessEqual(len(data), 1_000_000)
        self.assertEqual(mime, "image/jpeg")
        self.assertLessEqual(width, 1600)
        self.assertAlmostEqual(width / height, 4 / 3, places=2)
        with Image.open(BytesIO(data)) as result:
            self.assertEqual(result.size, (width, height))

    def test_orientation_is_preserved_and_exif_metadata_removed(self):
        from PIL import Image
        original = Image.new("RGB", (80, 40), "blue")
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "Private metadata"
        source = BytesIO()
        original.save(source, format="JPEG", exif=exif)
        data, _, width, height = images.thumbnail(source.getvalue())
        self.assertEqual((width, height), (40, 80))
        with Image.open(BytesIO(data)) as result:
            self.assertFalse(result.getexif())

    def test_transparent_png_is_preserved(self):
        from PIL import Image
        source = BytesIO()
        Image.new("RGBA", (40, 20), (0, 0, 255, 100)).save(source, format="PNG")
        data, mime, width, height = images.thumbnail(source.getvalue())
        self.assertEqual((mime, width, height), ("image/png", 40, 20))
        with Image.open(BytesIO(data)) as result:
            self.assertEqual(result.mode, "RGBA")

    def test_invalid_or_oversize_pixel_images_are_held(self):
        from PIL import Image
        with self.assertRaises(common.SetupError):
            images.thumbnail(b'<html>Not an image</html>')
        source = BytesIO()
        Image.new("RGB", (40, 20)).save(source, format="PNG")
        with patch.object(images, "MAX_IMAGE_PIXELS", 10), self.assertRaises(common.SetupError):
            images.thumbnail(source.getvalue())


if __name__ == "__main__":
    unittest.main()
