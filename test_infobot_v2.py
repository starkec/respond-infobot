"""V2 checks with fake publisher/API/Bluesky responses. No network or real posts."""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import infobot
import infobot_v2 as bot
from test_publishing import FakeBluesky


FEED = {"source_name": "Example", "feed_url": "https://example.org/feed/", "language": "en"}
TEXT = "The investigation alleges that officials accepted kickbacks for public contracts. " * 12
PUBLISH = {"decision": "publish", "reason": "The investigation concerns alleged procurement kickbacks.",
           "evidence": ["officials accepted kickbacks for public contracts."]}
SKIP = {"decision": "skip", "reason": "An unrelated story.", "evidence": []}
REVIEW = {"decision": "review", "reason": "The connection is uncertain.", "evidence": []}
CHECKS = {"abuse_of_entrusted_power": True, "private_gain": True,
          "substantive_corruption_coverage": True}
CARD = {"image_url": "https://example.org/original-photo.jpg", "image_bytes": b"fake-image",
        "mime_type": "image/jpeg", "width": 1200, "height": 630}
BLOB = {"$type": "blob", "mimeType": "image/jpeg", "size": 10, "ref": {"$link": "fake-blob"}}


def article(number=1, feed=FEED):
    return {**feed, "title": f"Investigation {number}", "link": f"https://example.org/story-{number}", "feed_content": TEXT}


class FeedTests(unittest.TestCase):
    def test_rss_extracts_content_deduplicates_and_rejects_offsite_links(self):
        xml = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
        <item><title>Story</title><link>https://example.org/a?utm_source=x#part</link>
        <content:encoded><![CDATA[<p>Alleged kickbacks.</p>]]></content:encoded></item>
        <item><title>Duplicate</title><link>https://example.org/a</link></item>
        <item><title>Offsite</title><link>https://evil.example/a</link></item>
        </channel></rss>'''
        items = bot.parse_feed(xml, FEED)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["link"], "https://example.org/a")
        self.assertEqual(items[0]["feed_content"], "Alleged kickbacks.")
        self.assertEqual(items[0]["source_name"], "Example")

    def test_atom_supported(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Story</title>
        <link rel="self" href="https://example.org/api"/>
        <link rel="alternate" href="https://example.org/a"/>
        <content type="html">&lt;p&gt;Article text&lt;/p&gt;</content></entry></feed>'''
        items = bot.parse_feed(xml, FEED)
        self.assertEqual(items[0]["feed_content"], "Article text")
        self.assertEqual(items[0]["link"], "https://example.org/a")

    def test_entities_and_html_error_pages_rejected(self):
        for body in (b'<!DOCTYPE rss><rss/>', b'<!ENTITY x "oops"><rss/>', b'<html/>', b'invalid'):
            with self.subTest(body=body), self.assertRaises(infobot.SetupError):
                bot.parse_feed(body, FEED)

    def test_legitimately_empty_feed_can_be_baselined(self):
        self.assertEqual(bot.parse_feed(b'<rss><channel/></rss>', FEED), [])

    def test_fair_sampling_and_cross_feed_url_deduplication(self):
        feeds = {"a": [article(1), article(2), article(3)], "b": [article(4), article(1)]}
        self.assertEqual([x["title"] for x in bot.round_robin(feeds)],
                         ["Investigation 1", "Investigation 4", "Investigation 2", "Investigation 3"])

    def test_html_excludes_navigation_scripts_and_related_sidebar(self):
        markup = '<nav>Corruption menu</nav><main><article><p>Actual story.</p><script>secret</script><aside>Other story</aside></article></main><footer>Footer</footer>'
        self.assertEqual(bot.html_text(markup), "Actual story.")

    def test_redirect_to_another_domain_or_http_is_blocked(self):
        request = bot.Request("https://example.org/story")
        for target in ("https://evil.example/a", "http://example.org/a"):
            with self.subTest(target=target), self.assertRaises(infobot.SetupError):
                bot.PublisherRedirect().redirect_request(request, None, 302, "", {}, target)

    def test_feed_failure_is_isolated_and_reported(self):
        config = {"feeds": [FEED, {**FEED, "feed_url": "https://other.example/feed"}]}
        with patch.object(bot, "download", side_effect=[b'<rss><channel/></rss>', infobot.SetupError("Unavailable")]):
            feeds, errors = bot.fetch_feeds(config)
        self.assertIn(FEED["feed_url"], feeds)
        self.assertEqual(len(errors), 1)


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.config = bot.load_config("config-v2.json")

    def test_structured_api_request_and_validated_evidence(self):
        response = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({**CHECKS, "decision": "publish", "reason": PUBLISH["reason"], "evidence_ids": [1]})}]}]}
        with patch.object(bot.v1, "read_response", return_value=json.dumps(response).encode()) as call:
            result = bot.classify(article(), self.config, "fake-private-key")
            self.assertEqual(result["decision"], "publish")
            self.assertIn(result["evidence"][0], TEXT)
        request = call.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, bot.API_URL)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["instructions"], bot.POLICY)
        self.assertNotIn("fake-private-key", request.data.decode())
        self.assertNotIn("fake-private-key", json.dumps(PUBLISH))

    def test_passages_preserve_the_source_without_model_generated_quotations(self):
        passages = bot.split_passages(TEXT)
        self.assertEqual(" ".join(p["text"] for p in passages), TEXT.strip())
        self.assertTrue(all(len(p["text"]) <= 220 and p["text"] in TEXT for p in passages))
        result = bot.resolve_evidence({**CHECKS, "decision": "publish", "reason": "Relevant.", "evidence_ids": [2, 1, 2]}, passages, TEXT)
        self.assertEqual(result["evidence"], [passages[1]["text"], passages[0]["text"]])

    def test_invalid_or_missing_evidence_ids_cannot_publish(self):
        passages = bot.split_passages(TEXT)
        for ids in ([], [99999], [True], ["1"], [1, 1, 1, 1]):
            with self.subTest(ids=ids), self.assertRaises(infobot.SetupError):
                bot.resolve_evidence({**CHECKS, "decision": "publish", "reason": "Relevant.", "evidence_ids": ids}, passages, TEXT)

    def test_uncertain_private_gain_role_or_centrality_overrides_publish(self):
        passages = bot.split_passages(TEXT)
        for condition in CHECKS:
            value = {**CHECKS, condition: False, "decision": "publish", "reason": "Possibly related.", "evidence_ids": [1]}
            with self.subTest(condition=condition):
                result = bot.resolve_evidence(value, passages, TEXT)
                self.assertEqual(result["decision"], "review")
                self.assertIn(condition, result["reason"])
                self.assertFalse(result["checks"][condition])

    def test_truthy_strings_cannot_bypass_corruption_checks(self):
        value = {**CHECKS, "private_gain": "true", "decision": "publish", "reason": "Related.", "evidence_ids": [1]}
        with self.assertRaises(infobot.SetupError):
            bot.resolve_evidence(value, bot.split_passages(TEXT), TEXT)

    def test_long_unbroken_text_can_be_split_without_loss(self):
        text = "x" * 701
        passages = bot.split_passages(text)
        self.assertEqual("".join(p["text"] for p in passages), text)

    def test_hallucinated_missing_or_overlong_evidence_cannot_publish(self):
        for evidence in ([], ["Invented bribery evidence"], ["x" * 241], [12]):
            with self.subTest(evidence=evidence), self.assertRaises(infobot.SetupError):
                bot.validate_decision({**PUBLISH, "evidence": evidence}, TEXT)

    def test_invalid_schema_refusal_or_incomplete_output_is_held(self):
        responses = [{"status": "incomplete", "output": []},
                     {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]},
                     {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}]}, []]
        for response in responses:
            with self.subTest(response=response), patch.object(bot.v1, "read_response", return_value=json.dumps(response).encode()):
                with self.assertRaises(infobot.SetupError):
                    bot.classify(article(), self.config, "fake-key")

    def test_short_feed_requires_article_download(self):
        markup = f'<article><p>{TEXT}</p></article>'.encode()
        with patch.object(bot, "download", return_value=markup) as download:
            text, origin, truncated = bot.article_text({**article(), "feed_content": "Short teaser"}, self.config)
        download.assert_called_once_with(article()["link"])
        self.assertIn("kickbacks", text)
        self.assertEqual(origin, "extracted article text")
        self.assertFalse(truncated)

    def test_short_or_blocked_article_cannot_reach_the_llm(self):
        with patch.object(bot, "download", return_value=b'<p>Access denied.</p>'), patch.object(bot.v1, "read_response") as call:
            with self.assertRaises(infobot.SetupError):
                bot.classify({**article(), "feed_content": ""}, self.config, "fake-key")
        call.assert_not_called()

    def test_input_size_is_bounded_and_truncation_disclosed(self):
        text, _, truncated = bot.article_text({**article(), "feed_content": TEXT * 100}, self.config)
        self.assertEqual(len(text), self.config["max_article_chars"])
        self.assertTrue(truncated)


class StateAndPublishingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state-v2.json"
        self.client = FakeBluesky()
        self.config = bot.load_config("config-v2.json")
        self.config["max_posts_per_run"] = 2
        self.feeds = {FEED["feed_url"]: [article(3), article(2), article(1)]}
        self.state = {"version": 2, "account_did": self.client.did, "feeds": list(self.feeds),
                      "seen": [], "posted": {}, "decisions": {}}
        self.output = patch("sys.stdout", new_callable=io.StringIO)
        self.output.start()
        self.addCleanup(self.output.stop)
        self.card_patch = patch.object(bot, "prepare_link_card", return_value=CARD)
        self.card_mock = self.card_patch.start()
        self.addCleanup(self.card_patch.stop)
        self.upload_patch = patch.object(bot.publisher_images, "upload_thumbnail", return_value=BLOB)
        self.upload_mock = self.upload_patch.start()
        self.addCleanup(self.upload_patch.stop)

    def run_bot(self, result=PUBLISH, preview=False):
        report = {"articles": []}
        with patch.object(bot, "classify", return_value=result) as classifier:
            bot.select_and_publish(self.feeds, self.config, "fake-key", report,
                                   self.client, None if preview else self.state, self.path)
        return report, classifier

    def test_preview_makes_no_bluesky_or_history_writes(self):
        report, classifier = self.run_bot(preview=True)
        self.assertEqual(classifier.call_count, 3)
        self.assertEqual(self.client.write_count, 0)
        self.assertFalse(self.path.exists())
        self.assertEqual(report["posted"], 0)

    def test_only_publish_decisions_create_posts_with_source_language(self):
        self.feeds[FEED["feed_url"]][2]["language"] = "de"
        with patch.object(bot, "classify", side_effect=[PUBLISH, SKIP, REVIEW]):
            bot.select_and_publish(self.feeds, self.config, "key", {"articles": []}, self.client, self.state, self.path)
        self.assertEqual(self.client.post_count, 1)
        record = self.client.get_record(infobot.POST_COLLECTION, infobot.record_key(article(1)))
        self.assertEqual(record["value"]["langs"], ["de"])
        self.assertIn("Source: Example", record["value"]["text"])
        self.assertEqual(record["value"]["embed"]["external"]["thumb"], BLOB)
        self.assertEqual(record["value"]["embed"]["external"]["description"], "")
        self.assertEqual(len(self.state["decisions"]), 3)
        self.assertEqual(len(self.state["seen"]), 3)

    def test_publication_limit_does_not_discard_unpublished_items(self):
        self.run_bot()
        self.assertEqual(self.client.post_count, 2)
        self.assertNotIn(infobot.article_id(article(3)), self.state["seen"])
        self.run_bot()
        self.assertEqual(self.client.post_count, 3)

    def test_budget_applies_to_classifications_not_only_posts(self):
        self.config["max_articles_per_run"] = 1
        report, classifier = self.run_bot(SKIP)
        self.assertEqual(classifier.call_count, 1)
        self.assertEqual(len(self.state["seen"]), 1)
        self.assertTrue(report["limit_reached"])

    def test_api_failure_never_publishes_or_marks_story_seen(self):
        with patch.object(bot, "classify", side_effect=infobot.APIError(429, "RateLimit", "LLM classification")):
            with self.assertRaises(infobot.SetupError):
                bot.select_and_publish(self.feeds, self.config, "key", {"articles": []}, self.client, self.state, self.path)
        self.assertEqual(self.client.post_count, 0)
        self.assertEqual(self.state["seen"], [])

    def test_fetch_failure_holds_article_without_publication(self):
        with patch.object(bot, "classify", side_effect=infobot.SetupError("Insufficient article text")):
            report = {"articles": []}
            bot.select_and_publish(self.feeds, self.config, "key", report, self.client, self.state, self.path)
        self.assertEqual(self.client.post_count, 0)
        self.assertTrue(all(row["decision"] == "review" for row in report["articles"]))

    def test_lost_state_commit_or_response_cannot_duplicate_a_post(self):
        before = deepcopy(self.state)
        self.client.lose_next_post_response = True
        self.run_bot()
        self.state = before
        self.run_bot()
        self.assertEqual(self.client.post_count, 2)

    def test_failed_publish_does_not_mark_unpublished_article_as_seen(self):
        self.client.fail_before_key = infobot.record_key(article(1))
        with self.assertRaises(infobot.SetupError):
            self.run_bot()
        self.assertNotIn(infobot.article_id(article(1)), self.state["seen"])
        self.client.fail_before_key = None
        self.run_bot()
        self.assertEqual(self.client.post_count, 2)

    def test_new_feeds_are_baselined_without_posting_their_backlog(self):
        self.state["seen"] = [infobot.article_id(item) for item in self.feeds[FEED["feed_url"]]]
        self.feeds["https://new.example/feed"] = [article(9)]
        _, classifier = self.run_bot()
        classifier.assert_not_called()
        self.assertIn(infobot.article_id(article(9)), self.state["seen"])
        self.assertEqual(self.client.post_count, 0)

    def test_initialisation_imports_legacy_history_and_suppresses_backlog(self):
        legacy_path = Path(self.directory.name) / "legacy.json"
        legacy_config = Path(self.directory.name) / "legacy-config.json"
        legacy_config.write_text(json.dumps({**FEED, "preview_count": 3}))
        original = {"version": 1, "account_did": self.client.did, "feed_url": FEED["feed_url"],
                    "seen": [infobot.article_id(article(99))], "posted": {"old": "at://previous-post"}}
        legacy_path.write_text(json.dumps(original))
        bot.initialise(self.path, legacy_path, self.client, self.feeds, legacy_config)
        migrated = bot.read_v2_state(self.path, self.client)
        self.assertIn(infobot.article_id(article(99)), migrated["seen"])
        self.assertEqual(len(migrated["seen"]), 4)
        self.assertEqual(migrated["posted"], original["posted"])
        self.assertEqual(json.loads(legacy_path.read_text()), original)
        self.assertEqual(self.client.write_count, 0)
        with self.assertRaises(infobot.SetupError):
            bot.initialise(self.path, legacy_path, self.client, self.feeds, legacy_config)

    def test_corrupt_or_wrong_account_history_is_rejected(self):
        for value in ("invalid json", json.dumps({**self.state, "account_did": "other"})):
            self.path.write_text(value)
            with self.assertRaises(infobot.SetupError):
                bot.read_v2_state(self.path, self.client)

    def test_malformed_saved_publish_decision_cannot_be_reused(self):
        key = infobot.article_id(article())
        for value in ("publish", {**PUBLISH, "url": article()["link"], "evidence": []}):
            self.path.write_text(json.dumps({**self.state, "decisions": {key: value}}))
            with self.assertRaises(infobot.SetupError):
                bot.read_v2_state(self.path, self.client)

    def test_failed_publication_reuses_valid_pending_classification(self):
        self.client.fail_before_key = infobot.record_key(article(1))
        with self.assertRaises(infobot.SetupError):
            self.run_bot()
        self.state = bot.read_v2_state(self.path, self.client)
        self.client.fail_before_key = None
        _, classifier = self.run_bot()
        self.assertEqual(classifier.call_count, 1)  # Article 1 was already classified.
        self.assertEqual(self.client.post_count, 2)

    def test_model_change_invalidates_pending_classification(self):
        self.client.fail_before_key = infobot.record_key(article(1))
        with self.assertRaises(infobot.SetupError):
            self.run_bot()
        self.client.fail_before_key = None
        self.config["model"] = "different-model"
        _, classifier = self.run_bot()
        self.assertEqual(classifier.call_count, 2)

    def test_report_retains_partial_progress_after_later_api_failure(self):
        report = {"articles": []}
        with patch.object(bot, "classify", side_effect=[PUBLISH, infobot.APIError(429, "RateLimit", "LLM classification")]):
            with self.assertRaises(infobot.SetupError):
                bot.select_and_publish(self.feeds, self.config, "key", report, self.client, self.state, self.path)
        self.assertEqual(report["posted"], 1)
        self.assertEqual(report["checked"], 2)
        self.assertEqual(len(bot.read_v2_state(self.path, self.client)["posted"]), 1)

    def test_retryable_download_failure_is_persisted_and_retried(self):
        with patch.object(bot, "classify", side_effect=infobot.SetupError("Publisher download failed")):
            bot.select_and_publish(self.feeds, self.config, "key", {"articles": []}, self.client, self.state, self.path)
        self.state = bot.read_v2_state(self.path, self.client)
        self.assertTrue(self.state["decisions"][infobot.article_id(article(1))]["retryable"])
        _, classifier = self.run_bot()
        self.assertEqual(classifier.call_count, 2)
        self.assertEqual(self.client.post_count, 2)

    def test_missing_image_holds_the_story_without_discarding_it_or_writing_profile(self):
        self.card_mock.side_effect = infobot.SetupError("No publisher sharing image found")
        report, _ = self.run_bot()
        self.assertEqual(self.client.write_count, 0)
        self.assertEqual(self.state["seen"], [])
        self.assertTrue(all(row["decision"] == "review" and row["image_error"] for row in report["articles"]))
        self.upload_mock.assert_not_called()
        self.card_mock.side_effect = None
        _, classifier = self.run_bot()
        classifier.assert_not_called()
        self.assertEqual(self.client.post_count, 2)
        self.assertNotIn("image_error", self.state["decisions"][infobot.article_id(article(1))])

    def test_preview_exposes_image_url_without_uploading_it(self):
        report, _ = self.run_bot(preview=True)
        self.assertEqual(report["articles"][0]["link_card"]["image_url"], CARD["image_url"])
        self.upload_mock.assert_not_called()
        json.dumps(report)  # Report must not contain raw image bytes.

    def test_preview_holds_missing_images_without_publication(self):
        self.card_mock.side_effect = infobot.SetupError("No image")
        report, _ = self.run_bot(preview=True)
        self.assertTrue(all(row["decision"] == "review" for row in report["articles"]))
        self.assertEqual(self.client.write_count, 0)

    def test_existing_posts_can_be_recovered_even_if_the_publisher_image_is_gone(self):
        before = deepcopy(self.state)
        self.run_bot()
        self.state = before
        self.card_mock.side_effect = infobot.SetupError("Image disappeared")
        self.run_bot()
        self.assertEqual(self.client.post_count, 2)

    def test_initialisation_cannot_bypass_legacy_account_check(self):
        legacy_path = Path(self.directory.name) / "legacy.json"
        legacy_config = Path(self.directory.name) / "legacy-config.json"
        legacy_config.write_text(json.dumps({**FEED, "preview_count": 3}))
        legacy_path.write_text(json.dumps({"version": 1, "account_did": "other", "feed_url": FEED["feed_url"], "seen": [], "posted": {}}))
        with self.assertRaises(infobot.SetupError):
            bot.initialise(self.path, legacy_path, self.client, self.feeds, legacy_config)
        self.assertFalse(self.path.exists())


class CLITests(unittest.TestCase):
    def test_missing_api_key_fails_without_network_or_posts(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["infobot_v2.py"]), patch.object(bot, "fetch_feeds") as fetch:
            with self.assertRaisesRegex(infobot.SetupError, "OPENAI_API_KEY"):
                bot.main()
            fetch.assert_not_called()

    def test_original_bot_must_be_paused_before_initialisation_or_run(self):
        for mode in ("initialise", "run"):
            with patch.dict(os.environ, {"INFOBOT_ENABLED": "true", "OPENAI_API_KEY": "fake-key"}), patch("sys.argv", ["infobot_v2.py", "--mode", mode]), patch.object(bot, "fetch_feeds") as fetch:
                with self.assertRaisesRegex(infobot.SetupError, "Pause the original"):
                    bot.main()
                fetch.assert_not_called()

    def test_preview_writes_report_without_login_or_history(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "decisions.json"
            with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"}), patch("sys.argv", ["infobot_v2.py", "--report", str(report_path)]), patch.object(bot, "fetch_feeds", return_value=({FEED["feed_url"]: [article()]}, [])), patch.object(bot, "classify", return_value=SKIP), patch.object(bot.v1, "login") as login, patch("sys.stdout", new_callable=io.StringIO):
                bot.main()
            login.assert_not_called()
            self.assertEqual(json.loads(report_path.read_text())["articles"][0]["decision"], "skip")


if __name__ == "__main__":
    unittest.main()
