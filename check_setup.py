"""Read-only feed and UvA integration checks. Never logs into or writes to Bluesky."""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request

import bot_common as common
import infobot_v2 as bot


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
            if feed.get("image_policy") == "omit":
                card = bot.prepare_link_card(sample)
                row["post_preview"] = common.preview_text(sample, sample["source_name"])
                row["link_card"] = bot.publisher_images.card_preview(card)
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
    synthetic = {"source_name": "Synthetic integration test", "title": "Officials charged over procurement kickbacks",
                 "link": "https://example.org/synthetic-test", "language": "en",
                 "feed_content": ("Prosecutors charged the mayor with taking private kickbacks from a contractor in exchange for steering public procurement contracts. "
                                  "The alleged bribes were paid to the mayor's personal bank account. The investigation concerns abuse of the mayor's official authority for personal financial gain. ") * 3}
    decision = bot.classify(synthetic, config, key)
    if decision["decision"] != "publish" or not all(decision["checks"].values()) or not decision["evidence"]:
        raise common.SetupError("UvA structured-output smoke check did not recognise the explicit synthetic corruption case.")
    results = [{"source": "Synthetic integration test", "decision": decision["decision"], "status": "passed"}]
    for sample in samples:
        if sample and sample.get("image_policy") == "omit":
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
            report["uva"] = check_uva(config, os.environ.get("UVAAI_API_KEY", "").strip(), [sample for _, sample in checks])
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
