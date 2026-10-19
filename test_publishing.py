"""Publishing integration checks with an in-memory Bluesky server; no network."""

from copy import deepcopy
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import infobot


CONFIG = {"source_name": "OCCRP", "feed_url": "https://example.org/feed",
          "preview_count": 3, "max_posts_per_run": 2}


def article(number):
    return {"title": f"Investigation {number}", "link": f"https://example.org/article-{number}"}


class FakeBluesky:
    did = "did:plc:testaccount"
    handle = "testaccount.bsky.social"

    def __init__(self):
        self.records = {}
        self.post_count = 0
        self.write_count = 0
        self.fail_before_key = None
        self.lose_next_post_response = False

    def get_record(self, collection, key):
        return deepcopy(self.records.get((collection, key)))

    def put_record(self, collection, key, value, previous_cid=None):
        existing = self.records.get((collection, key))
        if ((existing and previous_cid != existing["cid"])
                or (existing is None and previous_cid is not None)):
            raise infobot.APIError(400, "InvalidSwap", "Fake write")
        if key == self.fail_before_key:
            raise infobot.SetupError("Simulated server failure before write")
        self.write_count += 1
        uri = f"at://{self.did}/{collection}/{key}"
        self.records[(collection, key)] = {"uri": uri, "cid": f"cid-{self.write_count}",
                                            "value": deepcopy(value)}
        if collection == infobot.POST_COLLECTION:
            self.post_count += 1
            if self.lose_next_post_response:
                self.lose_next_post_response = False
                raise infobot.SetupError("Simulated response lost after server accepted post")
        return {"uri": uri, "cid": f"cid-{self.write_count}"}


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "data" / "state.json"
        self.client = FakeBluesky()
        self.output = io.StringIO()
        self.print_patch = patch("sys.stdout", self.output)
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)

    def cycle(self, articles, mode="test-post"):
        infobot.run_cycle(self.client, articles, CONFIG, self.state_path, mode)

    def state(self):
        return json.loads(self.state_path.read_text())

    def test_first_test_publishes_one_article_and_baselines_the_rest(self):
        articles = [article(3), article(2), article(1)]
        self.cycle(articles)
        self.assertEqual(self.client.post_count, 1)
        self.assertEqual(set(self.state()["seen"]), {infobot.article_id(item) for item in articles})
        self.cycle(articles, "run")
        self.assertEqual(self.client.post_count, 1)

    def test_repeating_same_test_does_not_duplicate_a_post(self):
        self.cycle([article(1)])
        self.cycle([article(1)])
        self.assertEqual(self.client.post_count, 1)
        self.assertIn("duplicate skipped", self.output.getvalue())

    def test_run_refuses_to_start_without_initial_history(self):
        with self.assertRaises(infobot.SetupError):
            self.cycle([article(1)], "run")
        self.assertEqual(self.client.write_count, 0)
        self.assertFalse(self.state_path.exists())

    def test_run_publishes_only_new_items_and_respects_limit(self):
        self.cycle([article(1)])
        self.cycle([article(4), article(3), article(2), article(1)], "run")
        self.assertEqual(self.client.post_count, 3)
        self.assertNotIn(infobot.article_id(article(4)), self.state()["seen"])
        self.cycle([article(4), article(3), article(2), article(1)], "run")
        self.assertEqual(self.client.post_count, 4)

    def test_lost_state_commit_recovers_without_reposting(self):
        self.cycle([article(1)])
        committed_state = self.state_path.read_text()
        self.cycle([article(2), article(1)], "run")
        self.state_path.write_text(committed_state)
        self.cycle([article(2), article(1)], "run")
        self.assertEqual(self.client.post_count, 2)
        self.assertIn(infobot.article_id(article(2)), self.state()["seen"])

    def test_timeout_after_server_accepted_post_is_reconciled(self):
        self.client.lose_next_post_response = True
        self.cycle([article(1)])
        self.assertEqual(self.client.post_count, 1)
        self.assertEqual(len(self.state()["posted"]), 1)

    def test_failure_does_not_mark_unpublished_new_article_as_seen(self):
        self.cycle([article(1)])
        self.client.fail_before_key = infobot.record_key(article(3))
        with self.assertRaises(infobot.SetupError):
            self.cycle([article(3), article(2), article(1)], "run")
        self.assertIn(infobot.article_id(article(2)), self.state()["seen"])
        self.assertNotIn(infobot.article_id(article(3)), self.state()["seen"])
        self.client.fail_before_key = None
        self.cycle([article(3), article(2), article(1)], "run")
        self.assertEqual(self.client.post_count, 3)

    def test_corrupt_history_is_not_reset_or_overwritten(self):
        self.state_path.parent.mkdir()
        self.state_path.write_text("invalid json")
        with self.assertRaises(infobot.SetupError):
            self.cycle([article(1)])
        self.assertEqual(self.state_path.read_text(), "invalid json")
        self.assertEqual(self.client.post_count, 0)

    def test_history_cannot_be_reused_for_different_account_or_feed(self):
        self.cycle([article(1)])
        original = self.state_path.read_text()
        for key, value in (("account_did", "did:plc:other"), ("feed_url", "https://example.org/other")):
            data = json.loads(original)
            data[key] = value
            self.state_path.write_text(json.dumps(data))
            with self.subTest(key=key), self.assertRaises(infobot.SetupError):
                self.cycle([article(2), article(1)], "run")
        self.assertEqual(self.client.post_count, 1)

    def test_existing_profile_and_other_labels_survive_bot_label(self):
        profile = {"$type": infobot.PROFILE_COLLECTION, "displayName": "RESPOND", "description": "Project account",
                   "labels": {"$type": "com.atproto.label.defs#selfLabels", "values": [{"val": "other-label"}]}}
        self.client.put_record(infobot.PROFILE_COLLECTION, "self", profile)
        self.cycle([article(1)])
        updated = self.client.get_record(infobot.PROFILE_COLLECTION, "self")["value"]
        self.assertEqual(updated["displayName"], "RESPOND")
        self.assertEqual(updated["description"], "Project account")
        self.assertEqual(updated["labels"]["values"], [{"val": "other-label"}, {"val": "bot"}])

    def test_record_key_collision_stops_instead_of_overwriting(self):
        self.cycle([article(1)])
        with patch("infobot.record_key", return_value=infobot.record_key(article(1))):
            with self.assertRaises(infobot.SetupError):
                infobot.publish_article(self.client, article(2), "OCCRP")
        self.assertEqual(self.client.post_count, 1)

    def test_profile_compare_and_swap_prevents_lost_edits(self):
        original = {"$type": infobot.PROFILE_COLLECTION, "description": "Original"}
        self.client.put_record(infobot.PROFILE_COLLECTION, "self", original)
        snapshot = self.client.get_record(infobot.PROFILE_COLLECTION, "self")
        self.client.put_record(infobot.PROFILE_COLLECTION, "self",
                               {**original, "description": "Updated by account owner"}, snapshot["cid"])
        with patch.object(self.client, "get_record", return_value=snapshot):
            with self.assertRaises(infobot.APIError):
                infobot.ensure_bot_label(self.client)
        current = self.client.records[(infobot.PROFILE_COLLECTION, "self")]["value"]
        self.assertEqual(current["description"], "Updated by account owner")


class RecordTests(unittest.TestCase):
    def test_record_keys_are_stable_valid_tid_syntax(self):
        first = infobot.record_key(article(1))
        self.assertRegex(first, re.compile(r"^[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}$"))
        self.assertEqual(first, infobot.record_key(article(1)))
        self.assertNotEqual(first, infobot.record_key(article(2)))

    def test_tracking_parameters_do_not_create_another_article_identity(self):
        first = article(1)
        tracked = {**first, "link": first["link"] + "?utm_source=example&fbclid=123#section"}
        self.assertEqual(infobot.article_id(first), infobot.article_id(tracked))
        different = {**first, "link": first["link"] + "?page=2"}
        self.assertNotEqual(infobot.article_id(first), infobot.article_id(different))

    def test_link_facet_points_to_full_url_with_unicode_title(self):
        item = {"title": "Investigation: naïve claims 🌍", "link": "https://example.org/story"}
        record = infobot.post_record(item, "OCCRP")
        index = record["facets"][0]["index"]
        raw = record["text"].encode("utf-8")
        self.assertEqual(raw[index["byteStart"]:index["byteEnd"]].decode(), item["link"])
        self.assertLessEqual(len(record["text"]), 300)
        self.assertLessEqual(len(raw), 3000)

    def test_create_post_uses_absence_guard(self):
        client = infobot.BlueskyClient({"did": "did:plc:test", "handle": "test.bsky.social", "accessJwt": "fake-token"})
        with patch.object(client, "call", return_value={}) as call:
            client.put_record(infobot.POST_COLLECTION, "2222222222222", {"text": "Example"})
            self.assertIn("swapRecord", call.call_args.kwargs["payload"])
            self.assertIsNone(call.call_args.kwargs["payload"]["swapRecord"])


if __name__ == "__main__":
    unittest.main()
