"""Manual decisions never publish until a live run, and retain all publication guards."""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import infobot as v1
import infobot_v2 as bot
from test_infobot_v2 import FEED, REVIEW, PUBLISH, SKIP, CARD, BLOB, article
from test_publishing import FakeBluesky


class ManualReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.queue = Path(self.directory.name) / "review.md"
        self.client = FakeBluesky()
        self.config = {**bot.load_config("config-v2.json"), "feeds": [FEED], "max_posts_per_run": 1}
        self.item = article()
        self.key = v1.article_id(self.item)
        self.state = {"version": 2, "account_did": self.client.did, "feeds": [FEED["feed_url"]],
                      "seen": [self.key], "posted": {}, "decisions": {
                          self.key: {**REVIEW, "url": self.item["link"], "title": self.item["title"],
                                     "source": FEED["source_name"]}}}
        v1.save_state(self.path, self.state)
        for target, kwargs in (("sys.stdout", {"new_callable": io.StringIO}),
                               ("infobot_v2.prepare_link_card", {"return_value": CARD}),
                               ("publisher_images.upload_thumbnail", {"return_value": BLOB})):
            mock = patch(target, **kwargs)
            started = mock.start()
            self.addCleanup(mock.stop)
            if target.endswith("prepare_link_card"):
                self.card = started

    def review(self, action="approve"):
        bot.record_manual_review(self.state, self.config, self.item["link"], action,
                                 "I read the article and verified its corruption connection.", "editor", self.path)

    def publish(self):
        report = {"articles": [], "posted": 0}
        bot.publish_manual_approvals(self.state, self.config, self.client, report, self.path)
        return report

    def test_approval_records_actor_note_and_original_reason_without_publishing(self):
        self.review()
        saved = bot.read_v2_state(self.path, self.client)["decisions"][self.key]
        self.assertEqual(saved["decision"], "review")
        self.assertEqual(saved["reason"], REVIEW["reason"])
        self.assertEqual(saved["manual_review"]["by"], "editor")
        self.assertEqual(self.client.write_count, 0)
        self.assertEqual(self.state["seen"], [self.key])

    def test_only_known_live_holds_can_be_reviewed(self):
        for url in ("http://example.org/story-1", "https://example.org/unknown"):
            with self.subTest(url=url), self.assertRaises(v1.SetupError):
                bot.record_manual_review(self.state, self.config, url, "approve", "A sufficient note", "editor", self.path)
        self.state["decisions"][self.key].update(SKIP)
        with self.assertRaisesRegex(v1.SetupError, "neither a live review"):
            self.review()

    def test_preview_only_article_can_be_imported_from_configured_feed_for_explicit_review(self):
        self.state["decisions"] = {}
        bot.record_manual_review(self.state, self.config, self.item["link"], "approve",
                                 "I checked the article and its corruption connection.", "editor", self.path,
                                 {FEED["feed_url"]: [self.item]})
        self.assertEqual(self.client.write_count, 0)
        self.assertEqual(self.state["decisions"][self.key]["review_origin"], "current_feed_manual_import")
        self.publish()
        self.assertEqual(self.client.post_count, 1)

    def test_import_does_not_accept_offsite_or_missing_article(self):
        self.state["decisions"] = {}
        for item in (article(2), {**self.item, "link": "https://other.example/story"}):
            with self.subTest(item=item), self.assertRaises(v1.SetupError):
                bot.record_manual_review(self.state, self.config, item["link"], "approve", "An editorial note", "editor", self.path,
                                         {FEED["feed_url"]: [self.item]})
        self.assertEqual(self.state["decisions"], {})

    def test_invalid_notes_and_published_stories_cannot_be_approved(self):
        with self.assertRaises(v1.SetupError):
            bot.record_manual_review(self.state, self.config, self.item["link"], "approve", "", "editor", self.path)
        self.state["posted"][self.key] = "at://already-published"
        with self.assertRaisesRegex(v1.SetupError, "already published"):
            self.review()
        self.assertNotIn("manual_review", self.state["decisions"][self.key])

    def test_approved_article_posts_even_after_leaving_feed_and_never_duplicates(self):
        self.review()
        with patch.object(bot, "classify") as classify:
            report = self.publish()
            self.publish()
        classify.assert_not_called()
        self.assertEqual(report["posted"], 1)
        self.assertEqual(self.client.post_count, 1)
        record = self.client.get_record(v1.POST_COLLECTION, v1.record_key(self.item))["value"]
        self.assertEqual(record["embed"]["external"]["description"], "")
        self.assertEqual(record["embed"]["external"]["thumb"], BLOB)
        self.assertIn("Source: Example", record["text"])

    def test_lost_response_and_lost_state_commit_recover_without_duplicate(self):
        self.review()
        before = deepcopy(self.state)
        self.client.lose_next_post_response = True
        self.publish()
        self.state = before
        self.card.side_effect = v1.SetupError("Image no longer available")
        self.publish()
        self.assertEqual(self.client.post_count, 1)
        self.assertIn(self.key, self.state["posted"])

    def test_missing_image_retains_approval_and_retries_without_llm(self):
        self.review()
        self.card.side_effect = v1.SetupError("No original image")
        report = self.publish()
        self.assertEqual(self.client.write_count, 0)
        self.assertEqual(report["articles"][0]["decision"], "review")
        self.assertEqual(self.state["decisions"][self.key]["manual_review"]["action"], "approve")
        self.card.side_effect = None
        self.publish()
        self.assertEqual(self.client.post_count, 1)

    def test_rejection_is_final_without_publishing_or_reclassification(self):
        self.review("reject")
        report = self.publish()
        with patch.object(bot, "classify") as classify:
            bot.select_and_publish({FEED["feed_url"]: [self.item]}, self.config, "key", report,
                                   self.client, self.state, self.path)
        classify.assert_not_called()
        self.assertEqual(self.client.write_count, 0)

    def test_manual_and_automatic_posts_share_one_run_limit(self):
        self.review()
        report = self.publish()
        with patch.object(bot, "classify") as classify:
            bot.select_and_publish({FEED["feed_url"]: [article(2)]}, self.config, "key", report,
                                   self.client, self.state, self.path)
        classify.assert_not_called()
        self.assertEqual(report["posted"], 1)
        self.assertNotIn(v1.article_id(article(2)), self.state["seen"])

    def test_removing_publisher_holds_previously_approved_story(self):
        self.review()
        self.config["feeds"] = []
        report = self.publish()
        self.assertEqual(self.client.write_count, 0)
        self.assertEqual(report["articles"][0]["decision"], "review")

    def test_image_hold_on_classifier_publish_can_be_manually_rejected(self):
        self.state["decisions"][self.key].update(PUBLISH, image_error="No image")
        self.review("reject")
        self.publish()
        self.assertEqual(self.client.write_count, 0)

    def test_queue_shows_reason_and_hides_rejected_and_published_stories(self):
        bot.write_review_queue(self.state, self.queue)
        self.assertIn(REVIEW["reason"], self.queue.read_text())
        self.review()
        bot.write_review_queue(self.state, self.queue)
        self.assertIn("approved, waiting", self.queue.read_text())
        self.publish()
        bot.write_review_queue(self.state, self.queue)
        self.assertIn("No articles", self.queue.read_text())

    def test_malformed_saved_manual_approval_is_rejected(self):
        self.state["decisions"][self.key]["manual_review"] = {"action": "approve"}
        v1.save_state(self.path, self.state)
        with self.assertRaisesRegex(v1.SetupError, "manual review is invalid"):
            bot.read_v2_state(self.path, self.client)

    def test_cli_review_uses_no_api_key_or_feed_download_and_never_posts(self):
        args = ["infobot_v2.py", "--mode", "review", "--state", str(self.path),
                "--review-queue", str(self.queue), "--report", str(self.queue.with_suffix(".json")),
                "--article-url", self.item["link"], "--review-action", "approve",
                "--review-note", "Read and checked the article."]
        with patch.dict(os.environ, {"GITHUB_ACTOR": "editor"}, clear=True), patch("sys.argv", args), \
                patch.object(bot, "load_config", return_value=self.config), \
                patch.object(bot.v1, "login", return_value=self.client), patch.object(bot, "fetch_feeds") as fetch:
            bot.main()
        fetch.assert_not_called()
        self.assertEqual(self.client.write_count, 0)
        self.assertTrue(self.queue.exists())

    def test_first_live_run_can_initialise_without_llm_or_posts(self):
        self.path.unlink()
        args = ["infobot_v2.py", "--mode", "run", "--initialise-if-needed", "--state", str(self.path),
                "--review-queue", str(self.queue), "--report", str(self.queue.with_suffix(".json"))]
        def initialise(*unused):
            v1.save_state(self.path, self.state)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "key", "INFOBOT_ENABLED": "false"}), patch("sys.argv", args), \
                patch.object(bot, "fetch_feeds", return_value=({FEED["feed_url"]: [self.item]}, [])), \
                patch.object(bot.v1, "login", return_value=self.client), \
                patch.object(bot, "initialise", side_effect=initialise) as init, patch.object(bot, "classify") as classify:
            bot.main()
        init.assert_called_once()
        classify.assert_not_called()
        self.assertEqual(self.client.write_count, 0)

    def test_partial_feed_failure_cannot_baseline_first_live_run(self):
        self.path.unlink()
        args = ["infobot_v2.py", "--mode", "run", "--initialise-if-needed", "--state", str(self.path),
                "--report", str(self.queue.with_suffix(".json"))]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "key", "INFOBOT_ENABLED": "false"}), patch("sys.argv", args), \
                patch.object(bot, "fetch_feeds", return_value=({FEED["feed_url"]: []}, ["Other feed failed"])), \
                patch.object(bot, "initialise") as init:
            with self.assertRaisesRegex(v1.SetupError, "All feeds"):
                bot.main()
        init.assert_not_called()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
