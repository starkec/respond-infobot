"""Offline checks for shared Bluesky records, profile protection and identifiers."""

from copy import deepcopy
import re
import unittest
from unittest.mock import patch

import bot_common as common
import infobot_v2 as bot


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
            raise common.APIError(400, "InvalidSwap", "Fake write")
        if key == self.fail_before_key:
            raise common.SetupError("Simulated server failure before write")
        self.write_count += 1
        uri = f"at://{self.did}/{collection}/{key}"
        self.records[(collection, key)] = {"uri": uri, "cid": f"cid-{self.write_count}",
                                            "value": deepcopy(value)}
        if collection == common.POST_COLLECTION:
            self.post_count += 1
            if self.lose_next_post_response:
                self.lose_next_post_response = False
                raise common.SetupError("Simulated response lost after server accepted post")
        return {"uri": uri, "cid": f"cid-{self.write_count}"}


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeBluesky()


    def test_existing_profile_and_other_labels_survive_bot_label(self):
        profile = {"$type": common.PROFILE_COLLECTION, "displayName": "RESPOND", "description": "Project account",
                   "labels": {"$type": "com.atproto.label.defs#selfLabels", "values": [{"val": "other-label"}]}}
        self.client.put_record(common.PROFILE_COLLECTION, "self", profile)
        common.ensure_bot_label(self.client)
        updated = self.client.get_record(common.PROFILE_COLLECTION, "self")["value"]
        self.assertEqual(updated["displayName"], "RESPOND")
        self.assertEqual(updated["description"], "Project account")
        self.assertEqual(updated["labels"]["values"], [{"val": "other-label"}, {"val": "bot"}])

    def test_record_key_collision_stops_instead_of_overwriting(self):
        item = article(1)
        key = common.record_key(item)
        self.client.put_record(common.POST_COLLECTION, key, common.post_record(item, "OCCRP"))
        with patch.object(common, "record_key", return_value=key):
            with self.assertRaises(common.SetupError):
                bot.publish_article(self.client, article(2))
        self.assertEqual(self.client.post_count, 1)

    def test_profile_compare_and_swap_prevents_lost_edits(self):
        original = {"$type": common.PROFILE_COLLECTION, "description": "Original"}
        self.client.put_record(common.PROFILE_COLLECTION, "self", original)
        snapshot = self.client.get_record(common.PROFILE_COLLECTION, "self")
        self.client.put_record(common.PROFILE_COLLECTION, "self",
                               {**original, "description": "Updated by account owner"}, snapshot["cid"])
        with patch.object(self.client, "get_record", return_value=snapshot):
            with self.assertRaises(common.APIError):
                common.ensure_bot_label(self.client)
        current = self.client.records[(common.PROFILE_COLLECTION, "self")]["value"]
        self.assertEqual(current["description"], "Updated by account owner")


class RecordTests(unittest.TestCase):
    def test_record_keys_are_stable_valid_tid_syntax(self):
        first = common.record_key(article(1))
        self.assertRegex(first, re.compile(r"^[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}$"))
        self.assertEqual(first, common.record_key(article(1)))
        self.assertNotEqual(first, common.record_key(article(2)))

    def test_tracking_parameters_do_not_create_another_article_identity(self):
        first = article(1)
        tracked = {**first, "link": first["link"] + "?utm_source=example&fbclid=123#section"}
        self.assertEqual(common.article_id(first), common.article_id(tracked))
        different = {**first, "link": first["link"] + "?page=2"}
        self.assertNotEqual(common.article_id(first), common.article_id(different))

    def test_link_facet_points_to_full_url_with_unicode_title(self):
        item = {"title": "Investigation: naïve claims 🌍", "link": "https://example.org/story"}
        record = common.post_record(item, "OCCRP")
        index = record["facets"][0]["index"]
        raw = record["text"].encode("utf-8")
        self.assertEqual(raw[index["byteStart"]:index["byteEnd"]].decode(), item["link"])
        self.assertLessEqual(len(record["text"]), 300)
        self.assertLessEqual(len(raw), 3000)

    def test_create_post_uses_absence_guard(self):
        client = common.BlueskyClient({"did": "did:plc:test", "handle": "test.bsky.social", "accessJwt": "fake-token"})
        with patch.object(client, "call", return_value={}) as call:
            client.put_record(common.POST_COLLECTION, "2222222222222", {"text": "Example"})
            self.assertIn("swapRecord", call.call_args.kwargs["payload"])
            self.assertIsNone(call.call_args.kwargs["payload"]["swapRecord"])


if __name__ == "__main__":
    unittest.main()
