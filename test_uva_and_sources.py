"""Migration regressions: credentials, source withdrawal, rights and no-photo posts."""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import bot_common as common
import infobot_v2 as bot
import publication
from test_infobot_v2 import article, CHECKS, PUBLISH
from test_publishing import FakeBluesky


class UvATests(unittest.TestCase):
    def setUp(self):
        self.config = bot.load_config("config-v2.json")

    def test_request_routes_only_to_uva_with_bearer_and_separate_timeout(self):
        response = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
                    "text": json.dumps({**CHECKS, "decision": "publish", "reason": "Alleged kickbacks.", "evidence_ids": [1]})}]}]}
        with patch.object(common, "read_response", return_value=json.dumps(response).encode()) as call:
            bot.classify(article(), self.config, "secret-test-key")
        req = call.call_args.args[0]
        self.assertEqual(req.full_url, "https://llmproxy.uva.nl/v1/responses")
        self.assertEqual(req.get_header("Authorization"), "Bearer secret-test-key")
        self.assertEqual(call.call_args.kwargs, {"timeout": 180, "allow_redirects": False})
        self.assertNotIn("secret-test-key", req.data.decode())

    def test_old_openai_secret_cannot_silently_keep_commercial_api_in_use(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "old-key"}, clear=True), patch("sys.argv", ["infobot_v2.py"]), patch.object(bot, "fetch_feeds") as fetch:
            with self.assertRaisesRegex(common.SetupError, "UVAAI_API_KEY"):
                bot.main()
        fetch.assert_not_called()

    def test_configuration_rejects_other_endpoint_and_noninteger_timeout(self):
        for change in ({"api_url": "https://api.openai.com/v1/responses"}, {"api_timeout_seconds": True}, {"max_output_tokens": 1}):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "config.json"
                p.write_text(json.dumps({**self.config, **change}))
                with self.assertRaises(common.SetupError):
                    bot.load_config(p)

    def test_redirect_never_forwards_uva_credentials(self):
        req = bot.Request(bot.API_URL, headers={"Authorization": "Bearer private"})
        with self.assertRaises(common.SetupError):
            common.NoRedirect().redirect_request(req, None, 302, "", {}, "https://other.example/")

    def test_gateway_error_is_sanitized_without_logging_body(self):
        error = HTTPError(bot.API_URL, 401, "Unauthorized", {}, io.BytesIO(b'{"error":{"code":"invalid_api_key","message":"private-value"}}'))
        with patch.object(common, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(common.APIError, "invalid_api_key") as caught:
                common.read_response(bot.Request(bot.API_URL), "LLM classification", allow_redirects=False)
        self.assertNotIn("private-value", str(caught.exception))

    def test_provider_endpoint_and_reasoning_are_part_of_cache_identity(self):
        for key, value in (("provider", "other"), ("api_url", "https://other.example/v1/responses"), ("reasoning_effort", "medium")):
            self.assertNotEqual(bot.classifier_id(self.config), bot.classifier_id({**self.config, key: value}))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.config = bot.load_config("config-v2.json")
        self.feed = next(f for f in self.config["feeds"] if f["source_name"] == "EDJNet")
        self.item = {**self.feed, "author": "Jane Reporter", "title": "An investigation", "link": "https://www.europeandatajournalism.eu/cp_data_news/a/"}
        self.html = b'<article>Story</article><p>Original source:</p><a href="https://example.org/original">https://example.org/original</a><h2>Licence:</h2><a>Creative Commons Attribution 4.0 International (CC BY 4.0)</a>'

    def test_config_is_english_and_has_no_occpr_feed(self):
        self.assertEqual({f["source_name"] for f in self.config["feeds"]}, {"ICIJ", "Bellingcat", "CORRECTIV", "EDJNet", "Mongabay", "Global Voices"})
        self.assertTrue(all(f["language"] == "en" for f in self.config["feeds"]))

    def test_rss_retains_author_and_source_rights_policy(self):
        xml = b'<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item><title>Story</title><link>https://www.europeandatajournalism.eu/cp_data_news/a/</link><dc:creator>Jane Reporter</dc:creator></item></channel></rss>'
        item = bot.parse_feed(xml, self.feed)[0]
        self.assertEqual(item["author"], "Jane Reporter")
        self.assertEqual(item["image_policy"], "omit")
        self.assertEqual(item["license_name"], "CC BY 4.0")

    def test_attributed_card_publishes_without_photo_or_image_upload(self):
        client = FakeBluesky()
        with patch.object(bot, "download", return_value=self.html), patch.object(bot.publisher_images, "upload_thumbnail") as upload:
            bot.publish_article(client, self.item)
        upload.assert_not_called()
        record = client.get_record(common.POST_COLLECTION, common.record_key(self.item))["value"]
        self.assertNotIn("thumb", record["embed"]["external"])
        self.assertIn("By: Jane Reporter", record["text"])
        self.assertIn("example.org | EDJNet", record["text"])
        self.assertIn("https://example.org/original", record["embed"]["external"]["description"])
        for facet in record["facets"]:
            bounds = facet["index"]
            label = record["text"].encode()[bounds["byteStart"]:bounds["byteEnd"]].decode()
            self.assertIn(label, (self.item["link"], "CC BY 4.0"))
        self.assertLessEqual(len(record["text"]), 300)

    def test_nonstandard_edjnet_licence_and_missing_author_hold_before_writes(self):
        for markup, item in ((self.html.replace(b'CC BY 4.0', b'Royalty-free copyright'), self.item), (self.html, {**self.item, "author": ""})):
            client = FakeBluesky()
            with patch.object(bot, "download", return_value=markup), self.assertRaises(common.SetupError):
                bot.publish_article(client, deepcopy(item))
            self.assertEqual(client.write_count, 0)

    def test_manual_approval_cannot_publish_withdrawn_occpr_source(self):
        decision = {**PUBLISH, "source": "OCCRP", "title": "Previously held story", "url": "https://www.occrp.org/en/a"}
        with self.assertRaises(common.SetupError):
            bot.reviewed_article(decision, self.config)

    def test_mongabay_default_text_licence_does_not_relicense_photo(self):
        feed = next(f for f in self.config["feeds"] if f["source_name"] == "Mongabay")
        item = {**self.item, **feed, "link": "https://news.mongabay.com/2026/11/a/"}
        photo_credit = b'<article>Story</article><figcaption>Photo <a href="https://creativecommons.org/licenses/by-nc/2.0/">CC BY-NC 2.0</a></figcaption>'
        card = publication.prepare_attributed_card(item, lambda _: photo_credit)
        self.assertEqual(card["image_policy"], "omit")
        self.assertEqual(item["license_name"], "CC BY-ND 4.0")

    def test_wordpress_editor_metadata_does_not_replace_the_feed_byline(self):
        item = deepcopy(self.item)
        publication.prepare_attributed_card(item, lambda _: b'<meta name="author" content="Website uploader">' + self.html)
        self.assertEqual(item["author"], "Jane Reporter")

    def test_explicit_republication_restriction_holds(self):
        with self.assertRaises(common.SetupError):
            publication.prepare_attributed_card(self.item, lambda _: self.html + b'<p>This article may not be republished.</p>')

    def test_missing_global_voices_licence_cannot_post(self):
        feed = next(f for f in self.config["feeds"] if f["source_name"] == "Global Voices")
        with self.assertRaises(common.SetupError):
            publication.prepare_attributed_card({**self.item, **feed}, lambda _: b'<article>Story</article>')


if __name__ == "__main__":
    unittest.main()
