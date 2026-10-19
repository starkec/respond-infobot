"""Offline checks: these tests make no network requests and publish nothing."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import infobot


RSS = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Example</title>
<item><title>A corruption investigation &amp; its findings</title>
<link>https://example.org/article</link></item>
<item><title>Duplicate link</title><link>https://example.org/article</link></item>
<item><title>Another article</title><link>https://example.org/second</link></item>
<item><title>Missing link</title></item>
<item><title>Invalid link</title><link>javascript:alert(1)</link></item>
</channel></rss>'''


class FeedTests(unittest.TestCase):
    def test_parses_rss_and_discards_duplicate_or_unusable_items(self):
        articles = infobot.parse_feed(RSS)
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0]["title"], "A corruption investigation & its findings")

    def test_rejects_html_error_page(self):
        with self.assertRaises(infobot.SetupError):
            infobot.parse_feed(b"<html><body>Server error</body></html>")

    def test_rejects_empty_or_invalid_feed(self):
        for data in (b"<rss><channel /></rss>", b"<rss>"):
            with self.subTest(data=data), self.assertRaises(infobot.SetupError):
                infobot.parse_feed(data)

    def test_rejects_xml_entities(self):
        with self.assertRaises(infobot.SetupError):
            infobot.parse_feed(b'<!DOCTYPE rss [<!ENTITY x "test">]><rss/>')

    def test_preview_keeps_source_and_full_link_with_long_unicode_title(self):
        article = {"title": "\U0001f30d" * 500, "link": "https://example.org/story"}
        text = infobot.preview_text(article, "OCCRP")
        self.assertLessEqual(len(text), 300)
        self.assertIn("…\n\nSource: OCCRP\n", text)
        self.assertTrue(text.endswith(article["link"]))

    def test_preview_fails_instead_of_truncating_an_overlong_link(self):
        with self.assertRaises(infobot.SetupError):
            infobot.preview_text({"title": "Title", "link": "https://example.org/" + "a" * 300}, "OCCRP")

    def test_rejects_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"source_name": "OCCRP", "feed_url": "http://example.org/", "preview_count": 3}))
            with self.assertRaises(infobot.SetupError):
                infobot.load_config(path)


class LoginTests(unittest.TestCase):
    def test_login_requires_both_secrets(self):
        with patch.dict(os.environ, {}, clear=True), patch("infobot.read_response") as request:
            with self.assertRaises(infobot.SetupError):
                infobot.check_login()
            request.assert_not_called()

    def test_login_uses_app_password_without_printing_or_saving_tokens(self):
        response = json.dumps({"handle": "example.bsky.social", "did": "did:plc:example", "accessJwt": "private-token"}).encode()
        with patch.dict(os.environ, {"BSKY_HANDLE": "example.bsky.social", "BSKY_APP_PASSWORD": "private-password"}), patch("infobot.read_response", return_value=response) as request, patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(infobot.check_login(), "example.bsky.social")
            sent_request = request.call_args.args[0]
            self.assertEqual(sent_request.full_url, infobot.LOGIN_URL)
            self.assertEqual(json.loads(sent_request.data)["password"], "private-password")
            self.assertEqual(output.getvalue(), "")

    def test_rejects_inactive_account(self):
        response = json.dumps({"handle": "example.bsky.social", "did": "did:plc:example", "accessJwt": "private-token", "active": False}).encode()
        with patch.dict(os.environ, {"BSKY_HANDLE": "example.bsky.social", "BSKY_APP_PASSWORD": "private-password"}), patch("infobot.read_response", return_value=response):
            with self.assertRaises(infobot.SetupError):
                infobot.check_login()

    def test_default_preview_does_not_attempt_login(self):
        with patch("sys.argv", ["infobot.py"]), patch("infobot.read_response", return_value=RSS), patch("infobot.check_login") as login, patch("sys.stdout", new_callable=io.StringIO) as output:
            infobot.main()
            login.assert_not_called()
            self.assertIn("No posts were published.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
