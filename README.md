# RESPOND Infobot

The currently running bot shares corruption-related news on Bluesky for WP8 of
the RESPOND project. The repository contains this version only. Its existing
v2 filenames and history format are retained so scheduled operation continues
with the same configuration and posting history.

The bot reads OCCRP, ICIJ, Bellingcat and CORRECTIV, with an LLM deciding whether
each article substantially concerns corruption. It shares the original
headline, source, publisher image and article link. The picture appears in a
clickable Bluesky link card. There is no generated summary or description text.
All four configured feeds are English, including CORRECTIV's English-only feed
at `https://correctiv.org/en/feed/`. CORRECTIV publishes a less frequent selection
of English translations rather than every story from its main German feed.
The parser also supports German feeds if explicitly configured later.

## About RESPOND and this deliverable

The Infobot is Deliverable 9 of RESPOND, developed by researchers at the
University of Amsterdam's Amsterdam School of Communication Research (ASCoR)
and Amsterdam Institute for Social Science Research (AISSR), within Work Package 8.
It provides a public stream of corruption-related reporting and a tool for
studying the effects of repeated exposure to that reporting over time.

[RESPOND — Rescuing Democracy from Political Corruption in Digital Societies](https://www.eu-respond.eu/)
is an EU-funded research project running from 2024 to 2029, coordinated by the
University of Bologna, Italy. Its consortium comprises 14 partners and three
affiliated entities (17 organisations in total). The project investigates
political corruption, digital technologies, democratic participation and
approaches to strengthening integrity.

The bot's public account is [Corruption Bot on Bluesky](https://bsky.app/profile/corruptionbot.bsky.social).
The three principal investigators of WP8 share responsibility for manual checks
once a week on a rotating basis. Automatic publication does not require approval
of every post; uncertain relevance decisions are held for manual review.
The workflow's automated checks do not independently verify the truth of the
publisher's reporting.

### Funding acknowledgement

This project has received funding from the European Union’s Horizon Europe research and innovation programme under Grant Agreement No 101132405.

Views and opinions expressed are however those of the author(s) only and do not
necessarily reflect those of the European Union. Neither the European Union nor
the granting authority can be held responsible for them.

## Current files

| File | Purpose |
| --- | --- |
| `infobot_v2.py` | Feed collection, corruption classification, review and publishing |
| `bot_common.py` | Shared text, URL identity, history and Bluesky API helpers |
| `publisher_images.py` | Original publisher images and Bluesky link cards |
| `config-v2.json` | Four feeds, model and processing limits |
| `requirements-v2.txt` | Pinned image-processing dependency |
| `.github/workflows/infobot-v2.yml` | Checks, manual actions and scheduled posting |
| `data/state-v2.json` | Production article, publication and review history; do not delete or reset |
| `data/review-queue.md` | Current stories held for manual review |
| `test_*.py` | Offline regression tests using mocked services |

## Operation in GitHub Actions

Open **Actions > Infobot v2**. The workflow checks twice an hour, at 17 and
47 minutes past the hour UTC, when the repository variable
`INFOBOT_V2_ENABLED` is exactly `true`. GitHub may delay or miss scheduled runs;
the next check processes unseen articles that remain available in the feeds.
When posting is enabled, code changes on `main` also trigger a live check. Pull requests run
offline tests without publishing. Publishing jobs share a concurrency group.

The existing repository secrets remain `OPENAI_API_KEY`, `BSKY_HANDLE` and
`BSKY_APP_PASSWORD`. Keep credentials out of files, variables and logs.

Use **Run workflow** on `main` to choose:

| Mode | Behavior |
| --- | --- |
| `preview` (default) | Classify current feed articles without publishing or changing posting history |
| `run` | Publish eligible unseen articles and pending manual approvals; save history |
| `review` | Approve or reject a known held story or a current-feed article; this action publishes nothing |
| `initialise` | Baseline feeds for a new installation only; refuses to overwrite existing history |

The running account is already initialised. Do not initialise it again or delete
its history. Live runs stop if history is missing or invalid; restore the latest
valid `data/state-v2.json` from Git history. The history already contains the
previous bot's seen article IDs and published post IDs, preserving duplicate
protection after cleanup.

To pause scheduled and push-triggered posting, set `INFOBOT_V2_ENABLED=false`.
Manual `run` can still publish. A current run may finish; cancel it in Actions
when an immediate stop is needed. Disabling the workflow also stops future
manual and scheduled runs until it is re-enabled.

## Preview and classification reports

Preview checks up to 20 articles, sampled across sources in feed order, and
shows publish/review/skip decisions with short reasons and supporting excerpts.
Selected articles include a `link_card` entry with the original image URL and
prepared thumbnail dimensions. Preview downloads and validates those images but
does not upload them to Bluesky. Missing or unusable pictures create retryable
review holds; these stories will not be posted without their publisher image.
It does not log into Bluesky, change the profile, publish posts or write posting
history. It writes only `reports/latest.json`, uploaded as an Actions artifact
retained for 14 days. That report includes article metadata, model, policy hash
and decisions, not full article bodies or API keys. Repeating preview repeats
the LLM requests; it deliberately evaluates current articles afresh.

The checked-in default model is `gpt-5-mini`, configurable in `config-v2.json`.
The integration uses the OpenAI Responses API with a strict JSON schema and
`store: false`. Article content is sent to the API for classification. This
setting controls response storage; it is not a claim of zero data retention.
Image preparation uses Pillow, pinned in `requirements-v2.txt`; the v2 workflow
installs it automatically. The LLM is used only for corruption selection.
Exact API spend depends on model and article length; inspect usage and set an
API project budget during operation.

## What qualifies

The policy in `infobot_v2.py` defines corruption as abuse of entrusted power for
private gain. It includes bribery, kickbacks, embezzlement, public procurement
rigging, nepotism, illicit enrichment and corrupt political financing, in public
or private institutions. Investigations, allegations, prosecutions and convictions
can all be relevant; a publish decision is not a finding of guilt.

Money laundering, offshore secrecy, influence buying and corporate misconduct
qualify only when the text establishes a concrete corruption connection.
General crime, war reporting, disinformation, ordinary legal lobbying or tax
planning, organisational news and training do not qualify automatically.

Every source, including OCCRP's corruption feed, passes the same classifier.
There is no keyword-only exclusion: investigations need not use the word
"corruption". Publisher text is supplied as untrusted data without tools.
The model must separately establish abuse of entrusted power, improper private
gain, and substantive coverage of corruption. The code holds an attempted
publish decision if any of these conditions is false or unknown. Those checks
are included in the report. They are still model judgments, not verified facts.

For a publish decision the model must select 1-3 numbered supporting passages
from the supplied article. The application copies their text verbatim and
checks that each is an exact substring of the supplied text. The model never
writes the quotations itself. This prevents invented quotations; it does not
prove that the model interpreted a real passage correctly. Inspect a labelled sample across all four sources
before trusting unattended selection. False positives and missed stories
remain possible. `review` never publishes automatically.

## Fetching and limits

`config-v2.json` lists HTTPS RSS/Atom URLs, source names and post languages.
RSS content fields are used when sufficiently substantial; short feeds trigger
an article-page download. The HTML reader prefers article/main text and otherwise
paragraphs, excluding navigation, scripts and sidebars. It is intentionally a
conservative extractor: paywalls, changed markup, short pages and JavaScript-only
pages may be held rather than classified. It does not bypass access restrictions.

RSS summaries alone are not treated as full articles. The classifier is told
when the supplied content comes from an RSS content field and may be partial,
and when text is truncated. The default minimum is 400 characters and maximum
24,000 characters per story. Downloads are limited to 2 MB and same-publisher
HTTPS URLs/redirects; a publisher's offsite syndication links are skipped.

There are at most 20 classification attempts and five publication attempts
per run, with sources interleaved so a high-volume feed does not monopolise a
check. Entries are visited oldest-first within each feed during publishing,
not globally sorted across publishers. A URL repeated across feeds is considered
once. Different publishers' articles about the same investigation remain
separate stories; cross-outlet story clustering is not implemented.

## History, review holds and failures

V2 records seen URLs, posted URIs and editorial decisions in `data/state-v2.json`.
Publish/skip decisions and model review holds are not reclassified automatically.
An editorial review hold enters history without a post. The persistent,
human-readable list is **[data/review-queue.md](data/review-queue.md)**, created
after initialisation. It includes each original URL, the model's reason,
three corruption criteria, supporting excerpts when available, and image errors.
The same list appears in each live workflow's job summary. Reports are available
under **Actions > Infobot v2 > completed run > infobot-v2-decisions** for 14 days.

### Review and approve or reject a held story

1. Open the original article from `data/review-queue.md` and read it. Check who
   allegedly abused an entrusted role, who gained improperly, and whether this
   connection is a substantial subject of the story. Check the publisher's
   headline, image, date, any corrections and the model's excerpts. A model
   excerpt is evidence of what the source said, not independent fact verification.
2. Open **Actions > Infobot v2 > Run workflow**, select **main**, and choose
   **review**. Copy the exact article URL, choose **approve** or **reject**,
   and write a 10-1000 character note explaining the editorial judgment. Leave
   a story pending if the available evidence is insufficient.
3. Click **Run workflow** and wait for the history-saving step to succeed.
   GitHub records the reviewing account, time and note. This action changes only
   the review history; it publishes nothing and makes no OpenAI request.
4. Approved stories join the next enabled live run, ahead of new feed entries.
   They are still processed if they have disappeared from the rolling RSS feed.
   The existing publisher-image, account and duplicate guards still apply, and
   approvals share the five-post run limit with automatic selections. An image
   failure keeps the approval pending for a later retry. To process sooner,
   dispatch **run** on `main` after reviewing; this can also publish other newly
   eligible articles. A rejected story stays unposted and is not reclassified.

Approvals explicitly override the classifier's relevance judgment; they do not
rewrite its original decision or reason. A pending approval can be changed to
reject before publication. Published posts cannot be edited or removed through
this workflow. Manual review accepts known live holds from a currently configured
publisher. A **preview-only** article can also be explicitly reviewed using the
same action while it is still present in its configured RSS feed: its original
title and source are imported from that feed, the reviewer supplies the editorial
decision, and the action still publishes nothing. The original preview reasoning
remains in its downloadable artifact. An arbitrary URL outside the configured
feeds is rejected. A live hold already saved in history remains reviewable after
leaving the feed; an unsaved preview-only story must still be in the feed.
Initialisation baselines existing feed articles, including previously previewed
stories, without posting them automatically. A manual approval explicitly releases
the selected story from that baseline.
There is no need to edit `seen`, `posted` or the JSON history manually.

Download failures, insufficient text or invalid model output are retryable review
holds, stored with `retryable: true` without marking the article seen. These are
retried while the article is still in the feed. API connection, authentication,
quota and rate-limit failures stop the run visibly. An unavailable feed is
reported as a failed check while successful sources can still be processed.
Unprocessed articles are not marked seen. Saved decisions make failed publication
retries economical; changes to model or policy invalidate a pending cached
decision. Already processed stories are not automatically reconsidered.

The workflow saves partial state even when a later operation fails. Stable post
keys and absent-record guards allow recovery after lost responses or failed
history commits. Existing posts are never overwritten.
Reports contain short publisher excerpts, so they should remain operational
records rather than be used as a republication feed.

## Publisher image cards

The bot reads the source article's Open Graph sharing image (`og:image`, with
`og:image:secure_url` preferred), then the publisher's Twitter-card image as a
fallback. It never invents a picture, substitutes an unrelated page image or
asks an LLM to write post text. The full article URL stays clickable in the post
and in the card. The card description is empty. Long headlines are shortened
only where Bluesky's text/title limits require it.

The picture content and aspect ratio are preserved, with downscaling/compression
when required for Bluesky's 1 MB card-thumbnail limit. JPEG, PNG and WebP source
images are supported; embedded metadata is stripped and EXIF orientation is
applied. Downloads are capped at 10 MB and decoded images at 40 million pixels.
Publisher-hosted image CDNs (such as `media.icij.org`) are supported through
HTTPS URLs on the publisher's own domain or subdomains; redirects are validated.
Third-party image-hosting domains are held rather than followed automatically.

If all publisher image candidates fail, the story remains unposted and is
retried while it is in the feed. Its LLM decision stays cached, avoiding repeated
classification charges just because an image was temporarily unavailable.
Previously accepted posts are recovered by their stable record key even if the
publisher's image has subsequently disappeared. Existing text-only posts are not
rewritten retroactively. A real upload and visible card should be checked when
live posting is deliberately enabled; preview itself never uploads a blob.

## Local verification

```bash
python -m pip install -r requirements-v2.txt
python -m unittest -v
python infobot_v2.py --help
python infobot_v2.py --mode preview
```

Tests mock the LLM, publishers and Bluesky; they do not establish live model
classification accuracy. A real preview needs `OPENAI_API_KEY` in the environment
and API connectivity. Repeated previews classify current articles afresh and
incur API usage. Reports include token counts for successful new classifications;
consult the API usage dashboard for actual billing and configure a project budget.

Initialisation, live publishing and review also need the Bluesky credentials.
For a new installation only, run `python infobot_v2.py --mode initialise` once
before the first live run. Initialisation baselines all currently returned
articles without posting them; every configured feed must download successfully.
Production history belongs to its recorded Bluesky account and must stay
synchronised. Avoid running independent local publishing copies alongside Actions.

## References

- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Configured model](https://developers.openai.com/api/docs/models/gpt-5-mini)
- [API usage](https://platform.openai.com/usage)
- [Model deprecations](https://developers.openai.com/api/docs/deprecations)
