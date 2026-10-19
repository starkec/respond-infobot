"""One explicitly authorised live post; never enables schedules or drains a feed."""

import json
import os
from pathlib import Path
import sys

import infobot as v1
import infobot_v2 as v2
import publisher_images


TARGET = "https://www.occrp.org/en/scoop/a-23-year-old-kazakh-owns-two-new-state-backed-universities-hes-the-presidents-great-nephew"


def verify_record(client, article):
    record = client.get_record(v1.POST_COLLECTION, v1.record_key(article))
    if not record:
        raise v1.SetupError("The test post could not be read back from Bluesky.")
    uri = v1.existing_post_uri(record, article, client)
    value = record["value"]
    external = value.get("embed", {}).get("external", {})
    if (value.get("text") != v1.preview_text(article, article["source_name"])
            or value.get("embed", {}).get("$type") != "app.bsky.embed.external"
            or external.get("uri") != article["link"]
            or external.get("description") != ""
            or not external.get("thumb", {}).get("ref", {}).get("$link")):
        raise v1.SetupError("The existing post does not match the expected title, source, image and article link. No replacement was attempted.")
    return uri, external


def run_one(client, article, config, api_key):
    if client.get_record(v1.POST_COLLECTION, v1.record_key(article)):
        uri, external = verify_record(client, article)
        return {"created": False, "post_uri": uri, "image_blob": external["thumb"]}
    decision = v2.classify(article, config, api_key)
    if decision["decision"] != "publish":
        raise v1.SetupError("The fresh classifier did not approve this article. No post was published.")
    card = v2.prepare_link_card(article)
    v1.ensure_bot_label(client)
    _, created = v2.publish_article(client, article, card)
    uri, external = verify_record(client, article)
    return {"created": created, "post_uri": uri, "image_blob": external["thumb"],
            "link_card": publisher_images.card_preview(card), "classification": decision}


def main():
    config = v2.load_config("config-v2.json")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise v1.SetupError("The one-post test needs the OPENAI_API_KEY secret.")
    feed = next(item for item in config["feeds"] if item["source_name"] == "OCCRP")
    articles = v2.parse_feed(v2.download(feed["feed_url"]), feed)
    article = next((item for item in articles if v1.canonical_url(item["link"]) == TARGET), None)
    if article is None:
        raise v1.SetupError("The chosen test article is no longer in the feed. Nothing published.")
    client = v1.login()
    # The established history identifies the intended account without exposing
    # credentials. This test never modifies either v1 or v2 article history.
    legacy = v1.load_state("data/state.json", client, v1.load_config("config.json"))
    if legacy is None:
        raise v1.SetupError("Established account history is required. Nothing published.")
    report = run_one(client, article, config, api_key)
    report.update(title=article["title"], source=article["source_name"], article_url=article["link"],
                  post_url="https://bsky.app/profile/" + client.did + "/post/" + v1.record_key(article))
    v1.save_state("reports/live-test.json", report)
    print("LIVE TEST VERIFIED: " + json.dumps(report, ensure_ascii=False))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write("## Single Bluesky test post\n\n")
            output.write("[Open the verified live post](" + report["post_url"] + ")\n\n")
            output.write("Original headline, source, publisher image and article link verified by read-back.\n")
            output.write("V2 automatic posting settings and both history files were unchanged.\n")


if __name__ == "__main__":
    try:
        main()
    except v1.SetupError as exc:
        print("Single-post test stopped: " + str(exc), file=sys.stderr)
        sys.exit(1)
