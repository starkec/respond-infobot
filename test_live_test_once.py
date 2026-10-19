"""Offline safeguards for the single authorised live test."""

import unittest
from unittest.mock import patch

import infobot
import infobot_v2
import live_test_once as test_run
from test_infobot_v2 import article, CARD, BLOB, PUBLISH, REVIEW
from test_publishing import FakeBluesky


class SinglePostTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeBluesky()
        self.item = article()

    def test_creates_one_post_and_repeating_the_test_cannot_create_a_second(self):
        with patch.object(infobot_v2, "classify", return_value=PUBLISH) as classify, patch.object(infobot_v2, "prepare_link_card", return_value=CARD), patch("publisher_images.upload_thumbnail", return_value=BLOB):
            first = test_run.run_one(self.client, self.item, {}, "fake-key")
            second = test_run.run_one(self.client, self.item, {}, "fake-key")
        self.assertEqual(self.client.post_count, 1)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(classify.call_count, 1)
        self.assertEqual(first["post_uri"], second["post_uri"])

    def test_review_decision_cannot_make_any_bluesky_writes(self):
        with patch.object(infobot_v2, "classify", return_value=REVIEW), self.assertRaises(infobot.SetupError):
            test_run.run_one(self.client, self.item, {}, "fake-key")
        self.assertEqual(self.client.write_count, 0)

    def test_missing_image_cannot_publish_or_edit_profile(self):
        with patch.object(infobot_v2, "classify", return_value=PUBLISH), patch.object(infobot_v2, "prepare_link_card", side_effect=infobot.SetupError("Missing image")), self.assertRaises(infobot.SetupError):
            test_run.run_one(self.client, self.item, {}, "fake-key")
        self.assertEqual(self.client.write_count, 0)

    def test_existing_text_only_post_is_not_overwritten(self):
        infobot.publish_article(self.client, self.item, self.item["source_name"])
        with self.assertRaises(infobot.SetupError):
            test_run.run_one(self.client, self.item, {}, "fake-key")
        self.assertEqual(self.client.post_count, 1)

    def test_lost_publish_response_still_has_exactly_one_post(self):
        self.client.lose_next_post_response = True
        with patch.object(infobot_v2, "classify", return_value=PUBLISH), patch.object(infobot_v2, "prepare_link_card", return_value=CARD), patch("publisher_images.upload_thumbnail", return_value=BLOB):
            report = test_run.run_one(self.client, self.item, {}, "fake-key")
        self.assertEqual(self.client.post_count, 1)
        self.assertTrue(report["image_blob"])


if __name__ == "__main__":
    unittest.main()
