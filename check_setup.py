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


def instruction_probes(config, key):
    rows = []
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    for channel in ("instructions", "system_message"):
        marker = "RESPOND_PROMPT_DELIVERY_24NOV_" + channel.upper()
        instruction = "Return JSON with the answer field set to exactly " + marker + ". This is a configuration check."
        user_input = "Please return an object with an answer field for this configuration check."
        payload = {"model": config["model"], "store": False, "max_output_tokens": 2048,
                   "reasoning": {"effort": "low"},
                   "text": {"format": {"type": "json_schema", "name": "delivery_probe", "strict": True, "schema": schema}}}
        if channel == "instructions":
            payload.update(instructions=instruction, input=user_input)
        else:
            payload["input"] = [{"role": "system", "content": instruction}, {"role": "user", "content": user_input}]
        request = Request(config["api_url"], data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        response = json.loads(common.read_response(request, "UvA prompt-delivery probe", timeout=config["api_timeout_seconds"], allow_redirects=False))
        output = "".join(part.get("text", "") for item in response.get("output", []) if item.get("type") == "message"
                         for part in item.get("content", []) if part.get("type") == "output_text")
        try:
            observed = json.loads(output).get("answer", "")
        except (ValueError, AttributeError):
            observed = "invalid output"
        row = {"probe": channel, "status": "passed" if observed == marker else "failed", "observed": observed[:120]}
        rows.append(row)
        print("Prompt delivery " + channel + ": " + row["status"], flush=True)
    return rows


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
        return results  # Retain the failing case in the saved report.
    for sample in samples:
        if sample:
            decision = bot.classify(sample, config, key)
            results.append({"source": sample["source_name"], "url": sample["link"], "decision": decision["decision"],
                            "checks": decision["checks"], "api_usage": decision.get("api_usage", {}), "status": "passed"})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feeds-only", action="store_true")
    parser.add_argument("--prompt-probe-only", action="store_true")
    parser.add_argument("--report", default="reports/setup-check.json")
    args = parser.parse_args()
    config = bot.load_config("config-v2.json")
    report = {"created_at": common.utc_now(), "provider": config["provider"], "model": config["model"], "posted": 0}
    try:
        if args.prompt_probe_only:
            report["check_kind"] = "prompt_delivery_only"
            report["prompt_delivery"] = instruction_probes(config, os.environ.get("UVAAI_API_KEY", "").strip())
            if any(row["status"] != "passed" for row in report["prompt_delivery"]):
                raise common.SetupError("UvA prompt delivery failed; inspect instructions/system-message probe results.")
            report["status"] = "passed"
            return
        checks = check_feeds(config)
        report["feeds"] = [row for row, _ in checks]
        if not args.feeds_only:
            key = os.environ.get("UVAAI_API_KEY", "").strip()
            report["prompt_delivery"] = instruction_probes(config, key)
            if any(row["status"] != "passed" for row in report["prompt_delivery"]):
                raise common.SetupError("UvA prompt delivery failed; inspect instructions/system-message probe results.")
            report["uva"] = check_uva(config, key, [sample for _, sample in checks])
            if any(row["status"] != "passed" for row in report["uva"]):
                raise common.SetupError("UvA autonomous relevance self-check failed; inspect the saved cases.")
            report["recent_post_replay"] = relevance_checks.replay_recent(config, key)
            if any(row["status"] not in ("passed", "safely_withheld") for row in report["recent_post_replay"]):
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
