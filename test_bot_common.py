"""Offline checks for post text and Bluesky authentication; no network or posts."""

import io
import json
import os
import unittest
from unittest.mock import patch

import bot_common as common


class TextTests(unittest.TestCase):


    def test_preview_keeps_source_and_full_link_with_long_unicode_title(self):
        article = {"title": "\U0001f30d" * 500, "link": "https://example.org/story"}
        text = common.preview_text(article, "OCCRP")
        self.assertLessEqual(len(text), 300)
        self.assertIn("…\n\nSource: OCCRP\n", text)
        self.assertTrue(text.endswith(article["link"]))

    def test_preview_fails_instead_of_truncating_an_overlong_link(self):
        with self.assertRaises(common.SetupError):
            common.preview_text({"title": "Title", "link": "https://example.org/" + "a" * 300}, "OCCRP")


class LoginTests(unittest.TestCase):
    def test_login_requires_both_secrets(self):
        with patch.dict(os.environ, {}, clear=True), patch("bot_common.read_response") as request:
            with self.assertRaises(common.SetupError):
                common.login()
            request.assert_not_called()

    def test_login_uses_app_password_without_printing_or_saving_tokens(self):
        response = json.dumps({"handle": "example.bsky.social", "did": "did:plc:example", "accessJwt": "private-token"}).encode()
        with patch.dict(os.environ, {"BSKY_HANDLE": "example.bsky.social", "BSKY_APP_PASSWORD": "private-password"}), patch("bot_common.read_response", return_value=response) as request, patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(common.login().handle, "example.bsky.social")
            sent_request = request.call_args.args[0]
            self.assertEqual(sent_request.full_url, common.LOGIN_URL)
            self.assertEqual(json.loads(sent_request.data)["password"], "private-password")
            self.assertEqual(output.getvalue(), "")

    def test_rejects_inactive_account(self):
        response = json.dumps({"handle": "example.bsky.social", "did": "did:plc:example", "accessJwt": "private-token", "active": False}).encode()
        with patch.dict(os.environ, {"BSKY_HANDLE": "example.bsky.social", "BSKY_APP_PASSWORD": "private-password"}), patch("bot_common.read_response", return_value=response):
            with self.assertRaises(common.SetupError):
                common.login()


if __name__ == "__main__":
    unittest.main()
