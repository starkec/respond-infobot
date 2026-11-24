"""Behaviour checks for the autonomous selection and verification boundary."""

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bot_common as common
import infobot_v2 as bot
import relevance_checks as checks
from test_infobot_v2 import article, TEXT, PUBLISH, MODEL_FIELDS, CHECKS
from test_publishing import FakeBluesky


def response(decision="publish", **changes):
    value = {**deepcopy(MODEL_FIELDS), "decision": decision, "reason": "A concrete allegation.", "evidence_ids": [1], **changes}
    return json.dumps({"status": "completed", "usage": {"input_tokens": 100, "output_tokens": 20},
                       "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}]}).encode()


class AutonomousClassifierTests(unittest.TestCase):
    def setUp(self):
        self.config = bot.load_config("config-v2.json")

    def test_verifier_receives_full_article_but_no_first_decision(self):
        with patch.object(common, "read_response", side_effect=[response(reason="FIRST-DECISION-MARKER"), response()]) as api:
            result = bot.classify_text(article(), self.config, "private-key", TEXT)
        self.assertEqual(result["decision"], "publish")
        first, second = [json.loads(call.args[0].data) for call in api.call_args_list]
        self.assertEqual(first["input"], second["input"])
        self.assertNotIn("FIRST-DECISION-MARKER", json.dumps(second))
        self.assertEqual(first["reasoning"]["effort"], "low")
        self.assertEqual(second["reasoning"]["effort"], "medium")
        self.assertEqual(result["api_usage"]["requests"], 2)
        self.assertEqual(result["api_usage"]["input_tokens"], 200)
        self.assertEqual(result["verification"]["decision"], "publish")

    def test_verifier_disagreement_and_uncertainty_are_excluded(self):
        for decision in ("skip", "review"):
            with self.subTest(decision=decision), patch.object(common, "read_response", side_effect=[response(), response(decision)]):
                result = bot.classify_text(article(), self.config, "key", TEXT)
            self.assertEqual(result["decision"], "skip")
            self.assertTrue(result["autonomous_exclusion"])
            self.assertEqual(result["selection"]["decision"], "publish")

    def test_first_pass_nonmatch_uses_one_call_and_no_human_approval(self):
        with patch.object(common, "read_response", return_value=response("review")) as api:
            result = bot.classify_text(article(), self.config, "key", TEXT)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(result["decision"], "skip")
        self.assertNotIn("verification", result)

    def test_publish_requires_concrete_case_and_evidence_for_each_criterion(self):
        for changes in ({"corruption_case": {**MODEL_FIELDS["corruption_case"], "entrusted_role": "Unknown"}},
                        {"criterion_evidence_ids": {**MODEL_FIELDS["criterion_evidence_ids"], "private_gain": []}}):
            with self.subTest(changes=changes), patch.object(common, "read_response", return_value=response(**changes)) as api:
                result = bot.classify_text(article(), self.config, "key", TEXT)
            self.assertEqual(result["decision"], "skip")
            self.assertEqual(api.call_count, 1)

    def test_other_primary_focus_blocks_publish_even_with_true_criteria(self):
        with patch.object(common, "read_response", return_value=response(
                coverage_type="other", article_focus="Advocacy for journalism funding using investigations as examples")) as api:
            result = bot.classify_text(article(), self.config, "key", TEXT)
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(api.call_count, 1)
        self.assertIn("principal_corruption_focus", result["reason"])

    def test_nonexistent_per_criterion_evidence_cannot_publish(self):
        with patch.object(common, "read_response", return_value=response(
                criterion_evidence_ids={name: [99999] for name in CHECKS})):
            with self.assertRaises(common.SetupError):
                bot.classify_text(article(), self.config, "key", TEXT)

    def test_gateway_failure_during_verification_never_returns_publish(self):
        with patch.object(common, "read_response", side_effect=[response(), common.APIError(401, "InvalidKey", "LLM classification")]):
            with self.assertRaises(common.APIError):
                bot.classify_text(article(), self.config, "key", TEXT)

    def test_long_rss_excerpt_never_substitutes_for_article_body(self):
        item = {**article(), "feed_content": "A long misleading RSS excerpt. " * 100}
        with patch.object(bot, "download", return_value=f"<article>{TEXT}</article>".encode()) as download:
            text, origin, _ = bot.article_text(item, self.config)
            bot.article_text(item, self.config)
        download.assert_called_once_with(item["link"])
        self.assertEqual(text, TEXT.strip())
        self.assertEqual(origin, "extracted article body")

    def test_publisher_body_wins_over_sibling_articles_and_embedded_widgets(self):
        markup = ('<main><article><div class="entry-content"><p>Main allegation.</p>'
                  '<div class="related-posts"><p>Other bribery story.</p></div>'
                  '<div class="newsrelated-widget"><article>More corruption</article></div>'
                  '<figcaption>Caption mentioning kickbacks</figcaption></div></article>'
                  '<article>' + 'Unrelated long teaser. ' * 100 + '</article></main>')
        self.assertEqual(bot.html_text(markup), "Main allegation.")

    def test_commentary_topic_class_does_not_hide_the_article_body(self):
        markup = '<article class="post topic-commentary"><p>Actual commentary body.</p><div class="comments">Discussion widget.</div></article>'
        self.assertEqual(bot.html_text(markup), "Actual commentary body.")

    def test_verifier_configuration_changes_cache_identity(self):
        self.assertNotEqual(bot.classifier_id(self.config), bot.classifier_id({**self.config, "verification_reasoning_effort": "high"}))


class AutonomousOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"
        self.config = bot.load_config("config-v2.json")
        self.item = article()
        self.config["feeds"] = [{k: self.item[k] for k in ("source_name", "feed_url", "language")}]
        self.client = FakeBluesky()
        self.key = common.article_id(self.item)
        self.state = {"version": 2, "account_did": self.client.did, "feeds": [self.item["feed_url"]],
                      "seen": [], "decisions": {}, "posted": {}}
        output = patch("sys.stdout", new_callable=io.StringIO)
        output.start()
        self.addCleanup(output.stop)
        preparation = patch.object(bot, "prepare_publication", return_value={"format": "text-only"})
        preparation.start()
        self.addCleanup(preparation.stop)

    def run_bot(self, feeds=None):
        report = {"articles": []}
        bot.select_and_publish(feeds if feeds is not None else {self.item["feed_url"]: [deepcopy(self.item)]},
                               self.config, "key", report, self.client, self.state, self.path)
        return report

    def test_technical_failure_waits_then_expires_without_manual_review(self):
        with patch.object(bot, "classify", side_effect=common.SetupError("Publisher unavailable")) as classify:
            self.run_bot()
            self.run_bot()
            self.assertEqual(classify.call_count, 1)
            for _ in range(2):
                self.state["decisions"][self.key]["retry_after"] = "2000-01-01T00:00:00Z"
                self.run_bot()
            self.assertEqual(classify.call_count, 3)
            self.run_bot()
            self.assertEqual(classify.call_count, 3)
        saved = self.state["decisions"][self.key]
        self.assertEqual(saved["decision"], "skip")
        self.assertFalse(saved["retryable"])
        self.assertIn(self.key, self.state["seen"])
        self.assertEqual(self.client.post_count, 0)

    def test_api_outage_does_not_exhaust_article_retry_budget(self):
        with patch.object(bot, "classify", side_effect=common.APIError(503, "Unavailable", "LLM classification")):
            for _ in range(4):
                with self.assertRaises(common.APIError):
                    self.run_bot()
        self.assertNotIn(self.key, self.state["seen"])
        self.assertNotIn("technical_attempts", self.state["decisions"][self.key])

    def test_old_hold_outside_current_feed_is_reassessed_and_excluded(self):
        self.config["feeds"] = [{k: self.item[k] for k in ("source_name", "feed_url", "language")}]
        self.state["decisions"][self.key] = {"decision": "review", "reason": "Old uncertainty", "evidence": [],
                                           "url": self.item["link"], "title": self.item["title"], "source": self.item["source_name"]}
        self.state["seen"] = [self.key]
        with patch.object(bot, "classify", return_value={"decision": "skip", "reason": "No concrete corruption", "evidence": []}) as classify:
            self.run_bot({self.item["feed_url"]: []})
        classify.assert_called_once()
        self.assertEqual(self.state["decisions"][self.key]["decision"], "skip")

    def test_published_articles_and_manual_rejections_stay_untouched(self):
        self.state["posted"][self.key] = "at://existing"
        with patch.object(bot, "classify") as classify:
            self.run_bot()
        classify.assert_not_called()
        self.assertEqual(self.state["posted"][self.key], "at://existing")

    def test_replay_refusal_is_withheld_for_negative_but_not_a_pass_for_positive(self):
        config = bot.load_config("config-v2.json")
        with patch.object(bot, "classify", side_effect=common.SetupError("Classifier refused this article; automatic retry required.")):
            rows = checks.replay_recent(config, "key")
        self.assertTrue(all(row["status"] == "safely_withheld" and not row["semantic_checked"]
                            for row in rows if row["expected"] == "skip"))
        self.assertTrue(all(row["status"] == "unavailable" for row in rows if row["expected"] == "publish"))

    def test_daily_health_failure_stops_posting_and_recovers_automatically(self):
        failed = [{"status": "failed", "case": "boundary"}]
        with patch.object(checks, "self_checks", return_value=failed):
            with self.assertRaisesRegex(common.SetupError, "self-check failed"):
                checks.ensure_ready(self.state, self.config, "key", {}, self.path)
        passed = [{"status": "passed", "case": "boundary"}]
        with patch.object(checks, "self_checks", return_value=passed) as check:
            checks.ensure_ready(self.state, self.config, "key", {}, self.path)
            checks.ensure_ready(self.state, self.config, "key", {}, self.path)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(self.state["classifier_health"]["status"], "passed")
        self.assertEqual(self.client.post_count, 0)
