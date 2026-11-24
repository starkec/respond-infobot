"""Read-only feed and UvA integration checks. Never logs into or writes to Bluesky."""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request

import bot_common as common
import infobot_v2 as bot
import relevance_checks


def check_feeds(config):
    def check(feed):
        try:
            articles = bot.parse_feed(bot.download(feed["feed_url"]), feed)
            if not articles:
                raise common.SetupError("Feed returned no articles; check the feed URL.")
            row = {"source": feed["source_name"], "feed_url": feed["feed_url"], "articles": len(articles), "status": "passed"}
            sample = articles[0]
            text, origin, truncated = bot.article_text(sample, config)
            row.update(sample_url=sample["link"], text_chars=len(text), text_origin=origin, truncated=truncated)
            row["publication"] = bot.prepare_publication(sample)
            row["post_preview"] = common.preview_text(sample, sample["source_name"])
            return row, sample
        except common.SetupError as exc:
            return {"source": feed["source_name"], "status": "failed", "error": str(exc)}, None
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(check, config["feeds"]))


def check_uva(config, key, samples):
    if not key:
        raise common.SetupError("UVAAI_API_KEY is missing. Set the repository Actions secret before running integration checks.")
    request = Request("https://llmproxy.uva.nl/v1/models", headers={"Authorization": "Bearer " + key})
    try:
        models = json.loads(common.read_response(request, "UvA model discovery", timeout=60, allow_redirects=False))
        available = {row["id"] for row in models["data"]}
    except (ValueError, TypeError, KeyError):
        raise common.SetupError("UvA returned invalid model-discovery data.") from None
    if config["model"] not in available:
        raise common.SetupError("The configured model is not available to this UvA key. Choose an exact ID from /v1/models; no provider/model fallback was used.")
    results = relevance_checks.self_checks(config, key)
    if any(row["status"] != "passed" for row in results):
        raise common.SetupError("UvA autonomous relevance self-check failed; publication is held by the same daily check.")
    for sample in samples:
        if sample:
            decision = bot.classify(sample, config, key)
            results.append({"source": sample["source_name"], "url": sample["link"], "decision": decision["decision"],
                            "checks": decision["checks"], "api_usage": decision.get("api_usage", {}), "status": "passed"})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feeds-only", action="store_true")
    parser.add_argument("--report", default="reports/setup-check.json")
    args = parser.parse_args()
    config = bot.load_config("config-v2.json")
    report = {"created_at": common.utc_now(), "provider": config["provider"], "model": config["model"], "posted": 0}
    try:
        checks = check_feeds(config)
        report["feeds"] = [row for row, _ in checks]
        if not args.feeds_only:
            key = os.environ.get("UVAAI_API_KEY", "").strip()
            report["uva"] = check_uva(config, key, [sample for _, sample in checks])
            report["recent_post_replay"] = relevance_checks.replay_recent(config, key)
            if any(row["status"] != "passed" for row in report["recent_post_replay"]):
                raise common.SetupError("Recent-post replay failed or an article was unavailable; inspect the read-only report.")
        if any(row["status"] != "passed" for row, _ in checks):
            raise common.SetupError("One or more feed/article/attribution checks failed; see setup-check.json.")
        report["status"] = "passed"
    except common.SetupError as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        common.save_state(args.report, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except common.SetupError as exc:
        print("Setup check failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
