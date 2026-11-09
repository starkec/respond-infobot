# RESPOND Infobot

The Infobot is a proof of concept for sharing corruption-related news on Bluesky
within WP8 of the RESPOND project. The repository contains this version only.
Its existing v2 filenames and history format are retained to preserve the
configuration and posting history.

**Status as of 9 November 2026.** The UvA gateway and English source update
is prepared while public posting remains paused. Reactivation is a separate
operator action (`INFOBOT_V2_ENABLED=true`). Code pushes run read-only checks,
never a publication run. Proof-of-concept posting began on 19 October 2026 and
ran successfully for three days. Existing publication history is retained.

The bot reads ICIJ, Bellingcat, CORRECTIV (English), EDJNet, Mongabay and
Global Voices. OCCRP has been removed because permission was not granted.
Historical OCCRP records remain solely for audit and duplicate protection;
pending OCCRP approvals cannot pass the configured-publisher check.

An LLM selects articles substantially concerning corruption. Public posts contain
the original headline (shortened only if needed), attribution and article link;
no LLM-generated summary is published. EDJNet, Mongabay and Global Voices get
text-only link cards with author, publisher and licence credits, not uploaded
photographs. The existing image behaviour for the three retained sources is
unchanged; their permissions are managed by the research team.
All six configured feeds are English. CORRECTIV's English feed is a less frequent
selection of translations, rather than the full German feed.

### Added sources and reuse terms

| Source | English feed | Text reuse | Image handling |
| --- | --- | --- | --- |
| EDJNet | https://www.europeandatajournalism.eu/feed/?post_type=cp_data_news | CC BY 4.0 by default; credit the originating outlet and EDJNet; article-specific alternatives are held | No thumbnails |
| Mongabay | https://news.mongabay.com/feed/ | Default article-text licence CC BY-ND 4.0; credit author and Mongabay; explicit republication restrictions are held | No thumbnails; photo-caption licences do not license the article text |
| Global Voices | https://globalvoices.org/feed/ | CC BY 3.0 by default; author, source, original link and licence credit; require a licence signal on the page | No thumbnails |

Licence labels in post text are clickable links. Link-card descriptions preserve
full credits and, for EDJNet, the original publisher link. Credits are never
removed to fit a headline; incomplete or overlong credits create review holds.
Mongabay's new template does not repeat its default text licence on every article;
the bot uses its published default policy and checks for explicit exceptions.
Open licensing is not blanket permission for third-party material. Operational
checks cannot independently establish rights ownership or reporting accuracy.

Policies checked for this update:
- https://www.europeandatajournalism.eu/about/licence/
- https://news.mongabay.com/copyright/creative-commons/
- https://globalvoices.org/about/global-voices-attribution-policy/

## About RESPOND and this deliverable

The Infobot is Deliverable 8.1 of RESPOND, developed by researchers at the
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
Members of RESPOND's UvA research team working on Subtask 8.3.2 share
responsibility for manual checks once a week on a rotating basis. The assigned
researcher reviews uncertain articles and checks the wider output, failed runs
and persistent technical holds. Automatic publication does not require approval
of every post; uncertain relevance decisions are held for manual review.
The workflow's automated checks do not independently verify the truth of the
publisher's reporting.

### Funding acknowledgement

This project has received funding from the European Union’s Horizon Europe research and innovation programme under Grant Agreement No 101132405.

Views and opinions expressed are however those of the author(s) only and do not
necessarily reflect those of the European Union. Neither the European Union nor
the granting authority can be held responsible for them.

## Visibility and project links

The Infobot's profile will link to [RESPOND's website](https://www.eu-respond.eu/)
and [RESPOND on Bluesky (@respondeu.bsky.social)](https://bsky.app/profile/respondeu.bsky.social).
The aim is to reach **250 followers in the first year**.

S-COM will coordinate promotion through RESPOND's communication channels and
website, with further outreach through the
[Interdisciplinary Corruption Research Network (ICRN)](https://www.icrnetwork.org/)
and the researchers' professional networks. Planned outreach includes an
introduction to the bot, links inviting readers to follow it and follow-up
updates. These are planned communication activities, not claims that posts
have already been published.

| Channel | RESPOND account or address |
| --- | --- |
| Bluesky | [@respondeu.bsky.social](https://bsky.app/profile/respondeu.bsky.social) |
| LinkedIn | [RESPOND_EU (company/respond-eu)](https://www.linkedin.com/company/respond-eu) |
| X | [@RESPOND_EU](https://x.com/RESPOND_EU) |
| YouTube | [@RESPOND_EU](https://www.youtube.com/@RESPOND_EU) |
| Project website | [eu-respond.eu](https://www.eu-respond.eu/) |

RESPOND's [Communication, Dissemination and Exploitation Plan, pp. 14-16](https://www.eu-respond.eu/wp-content/uploads/2025/06/RESPOND_Deliverable-12.2.pdf)
documents the LinkedIn, X and YouTube accounts and S-COM/Tele Radio City's role
in managing project channels. It also names Facebook as RESPOND-EU and Mastodon
as RESPOND_EU, but does not give a complete Mastodon address. Confirm the
current Facebook URL and Mastodon server with S-COM before publishing direct
links. The Instagram strategy in that plan uses partners' accounts.

## Current files

| File | Purpose |
| --- | --- |
| `infobot_v2.py` | Feed collection, corruption classification, review and publishing |
| `bot_common.py` | Shared text, URL identity, history and Bluesky API helpers |
| `publisher_images.py` | Original publisher images and Bluesky link cards |
| `config-v2.json` | Six English feeds, UvA endpoint/model and processing limits |
| `publication.py` | Attribution, licence checks and cards without photographs |
| `check_setup.py` | Read-only live feed and UvA integration checks |
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
Code changes on `main` run offline tests plus read-only integration checks. Pull
requests run offline tests only and have no API credentials. Publishing jobs
share a concurrency group.

The repository secrets are `UVAAI_API_KEY`, `BSKY_HANDLE` and
`BSKY_APP_PASSWORD`. `OPENAI_API_KEY` is no longer read or passed to any job.
Keep credentials out of files, variables and logs.

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

To pause scheduled posting, set `INFOBOT_V2_ENABLED=false`.
Manual `run` can still publish. A current run may finish; cancel it in Actions
when an immediate stop is needed. Disabling the workflow also stops future
manual and scheduled runs until it is re-enabled.

## Preview and classification reports

Preview checks up to 20 articles, sampled across sources in feed order, and
shows publish/review/skip decisions with short reasons and supporting excerpts.
Selected articles include a `link_card` entry. For the three added sources it
contains attribution and `image_policy: omit`. For retained sources it contains
the publisher image URL and thumbnail dimensions; image failures hold those
stories. Preview never uploads a photograph.
It does not log into Bluesky, change the profile, publish posts or write posting
history. It writes only `reports/latest.json`, uploaded as an Actions artifact
retained for 14 days. That report includes article metadata, model, policy hash
and decisions, not full article bodies or API keys. Repeating preview repeats
the LLM requests; it deliberately evaluates current articles afresh.

The configured model remains `gpt-5-mini`. Requests now go exclusively to
`https://llmproxy.uva.nl/v1/responses` using `UVAAI_API_KEY`, Bearer authentication,
strict JSON schema output and `store: false`. No direct OpenAI endpoint or
commercial-provider fallback is used. The UvA gateway may route to external
model infrastructure; this change is not a claim of university-only hosting or
zero data retention. Confirm the selected backend and terms with UvA.

The UvA key must have access to the exact configured model ID. Read-only checks
query `/v1/models`, submit a synthetic corruption example and classify one
current story from each added source. A missing key, unavailable model or invalid
structured output fails visibly. No automatic model substitution occurs.

LLM requests have a separate 180-second timeout, a 4,096-token output ceiling
(including reasoning) and low reasoning effort for GPT-5 models. The endpoint,
provider, model, schema and reasoning configuration form a cache identity.
Authenticated API redirects are refused. Keys, headers and response bodies are
never logged. Provider/endpoint/model metadata and token counts are reported.

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

Every configured source passes the same classifier.
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
prove that the model interpreted a real passage correctly. The research team already inspected the adaptation during the proof of concept.
No new numerical accuracy estimate is claimed by this software migration. False positives and missed stories
remain possible. `review` never publishes automatically.

## Classifier development and checks

The Infobot builds on a political-corruption classification approach developed
for another WP8 task. In that earlier task, researchers used a zero-shot
LLAMA3-70B classifier to remove irrelevant articles retrieved by a keyword
search. "Zero-shot" means applying written classification instructions without
providing labelled examples in the prompt. The prompt was iteratively refined
and evaluated against 201 manually annotated articles. The project team reports
F1 = 0.87, precision = 0.87 and recall = 0.87, with manual inspection showing
strong alignment between model decisions/rationales and human judgment.

The related project's [repository](https://github.com/annekroon/RESPOND-victims-of-corruption)
and [political-corruption annotation instructions](https://github.com/annekroon/RESPOND-victims-of-corruption/blob/main/political_classifier/scripts/_impl/label_silver_batch.py)
document the narrower focus on political decision-makers. The reported
LLAMA3-70B evaluation belongs to that earlier WP8 task; the linked script alone
does not reproduce the evaluation or establish which historical prompt/model
revision was scored.

Using explicit classification criteria, refining instructions and comparing
outputs with human annotations is a standard approach to LLM-assisted text
classification. See, for example, [Gilardi, Alizadeh and Kubli (2023)](https://doi.org/10.1073/pnas.2305016120)
for zero-shot text annotation evaluated against human-coded data. The
Infobot-specific instructions remain a task-specific adaptation rather than
a universally validated Infobot template.

For the Infobot, the scope is deliberately broader. We use Transparency
International's definition of corruption as ["the abuse of entrusted power
for private gain"](https://www.transparency.org/en/what-is-corruption), including
political, administrative, judicial and private-sector corruption. Restricting
the feed to political officeholders would exclude many articles relevant to
the awareness, fatigue and trust outcomes studied in Subtask 8.3.2. The
three relevance checks and the requirement to treat allegations as allegations
remain in place.

| Stage | Work undertaken | What the evidence establishes |
| --- | --- | --- |
| Earlier WP8 political-corruption classifier | Zero-shot LLAMA3-70B instructions were iteratively refined and evaluated on 201 manually annotated articles. | The earlier task's reported F1, precision and recall were each 0.87. |
| Infobot adaptation | The political-only scope was broadened to Transparency International's definition, with publish/skip/review decisions and supporting article passages. | The selection rules cover corruption in public and private institutions while excluding unrelated crime or misconduct. |
| Three-day proof of concept beginning 19 October 2026 | Researchers inspected the adapted classifier's decisions to check that it worked as intended during operation. | This provides qualitative development and operational checks, not a new numerical accuracy estimate. |
| Scope clarification on 30 October 2026 | The prompt now explicitly names political, administrative, judicial and private-sector corruption and relevant non-political entrusted roles. | The wording makes the intended scope explicit; it does not transfer the earlier classifier's validation scores to this version. |

The earlier F1 score must not be reported as the Infobot's accuracy. Changes
to the scope, model and article sources mean that the adapted classifier needs
its own assessment before accuracy claims can be made. Software regression
tests check program behaviour, not whether the model interprets articles
correctly.

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
   the review history; it publishes nothing and makes no LLM request.
4. Approved stories join the next enabled live run, ahead of new feed entries.
   They are still processed if they have disappeared from the rolling RSS feed.
   The current source-specific rights, image, account and duplicate guards apply, and
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
retries economical; changes to provider, endpoint, model, schema or policy invalidate a pending cached
decision. Already processed stories are not automatically reconsidered.

The workflow saves partial state even when a later operation fails. Stable post
keys and absent-record guards allow recovery after lost responses or failed
history commits. Existing posts are never overwritten.
Reports contain short publisher excerpts, so they should remain operational
records rather than be used as a republication feed.

## Publisher image cards

This section applies to the retained image-enabled sources only. The three added
sources deliberately use cards without thumbnails, as described above.

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
python check_setup.py --feeds-only
# UVAAI_API_KEY must be set securely for the next two commands:
python check_setup.py
python infobot_v2.py --mode preview
```

Tests mock the LLM, publishers and Bluesky; they do not establish live model
classification accuracy. A real preview needs `UVAAI_API_KEY` in the environment
and API connectivity. Repeated previews classify current articles afresh and
incur API usage. Reports include token counts for successful new classifications;
consult the UvA proxy administrators for quotas, access and billing.

Initialisation, live publishing and review also need the Bluesky credentials.
For a new installation only, run `python infobot_v2.py --mode initialise` once
before the first live run. Initialisation baselines all currently returned
articles without posting them; every configured feed must download successfully.
Production history belongs to its recorded Bluesky account and must stay
synchronised. Avoid running independent local publishing copies alongside Actions.

## References

- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Configured model](https://developers.openai.com/api/docs/models/gpt-5-mini)
- [UvA gateway setup and endpoints](https://github.com/uva/UvA-HvA-Agentic-Tools)
- [Model deprecations](https://developers.openai.com/api/docs/deprecations)

## Reactivation after migration

1. Check **Actions > Infobot v2** for the latest code commit. Both **checks** and
   **Read-only UvA and feed checks** should succeed. Download `infobot-setup-check`
   for individual feed, attribution and live API results. No Bluesky credentials
   are available to the read-only integration job.
2. If the workflow itself was disabled, re-enable it while keeping
   `INFOBOT_V2_ENABLED=false`, then dispatch `preview`. A manual preview uses the
   UvA key and never posts.
3. Once satisfied, set `INFOBOT_V2_ENABLED=true`. Do not delete history or run
   `initialise`: the first live run baselines the three added feeds without
   dumping their current backlog. New stories are eligible on subsequent runs.

The integration check is a connectivity/schema/software check, not a new manual
validation study or a measurement of the classifier's accuracy.
