# RESPOND Infobot

**Multi-feed v2 trial:** [V2 setup and operation](V2.md) describes the new
LLM corruption filter and original publisher-image cards for OCCRP, ICIJ,
Bellingcat and CORRECTIV. V2 posts headlines, sources, images and links without
generated summaries. The original
bot below keeps its existing configuration, workflow and history. V2 is opt-in
and defaults to preview; merging its files does not enable v2 posting.

A small Python bot that shares headlines, source attribution and links from
OCCRP's corruption RSS feed on a dedicated Bluesky account. It uses Python's
standard library and GitHub Actions. It does not use an LLM, copy article bodies,
or automatically reply to, message, mention or follow other users.

This update adds real publishing and persistent article history. The first
guided action is a single test post. Scheduled publishing stays off until the
repository variable `INFOBOT_ENABLED` is set to the exact value `true`.

## Upgrade from the preview

1. Extract `respond-infobot-live.zip`. In the existing GitHub repository, use
   **Add file > Upload files** to upload its six files, directly alongside the
   current README. Replace the earlier `infobot.py`, `config.json`,
   `test_infobot.py`, and `README.md`, and add `test_publishing.py` and
   `infobot-live.yml`. Commit to the default branch, usually `main`.
2. Open the new `infobot-live.yml`, click the pencil icon, and change its path
   in the filename field to `.github/workflows/infobot-live.yml`. Keep its
   contents unchanged and commit. This path must be the actual file location,
   not just a comment inside the file.

The earlier `.github/workflows/infobot-preview.yml` can stay in place. It is
manual only and still works with this version. It never runs the publishing
modes. The new workflow appears in Actions as **Infobot**.

## Publish the first test article

Your existing GitHub Actions secrets remain the same:

| Name | Value |
| --- | --- |
| `BSKY_HANDLE` | The full account handle, without `@` |
| `BSKY_APP_PASSWORD` | A Bluesky app password for that account |

Open **Actions > Infobot > Run workflow**. Select the default branch and choose
`test-post` for the mode, then click **Run workflow**. This action:

- records the articles currently in the feed as the initial baseline;
- adds Bluesky's bot self-label while preserving your existing profile fields;
- publishes the first (most recent) article in the feed, or recognises an
  existing post of that same article without creating a duplicate;
- saves progress in `data/state.json` in the repository.

Open the run's **infobot** job and check **Run the Infobot** and
**Save article history to GitHub**. Both should be green. The log includes a
direct Post URL. Check the visible post on Bluesky: readable headline,
`Source: OCCRP`, and a clickable article link. There is no image or preview
card in this simple version.

If you select `test-post` again while the same story remains first in the feed,
it should report **Already published; duplicate skipped**. If a different
article has become first, another manual test can publish that article.

`preview` remains the default mode in the manual workflow form. It displays
sample posts, checks the login and makes no profile or post changes.

## Enable automatic posting after the test succeeds

In the repository, open **Settings > Secrets and variables > Actions > Variables**.
Click **New repository variable**, set the name to `INFOBOT_ENABLED` and the
value to `true`, then save. This is an ordinary configuration variable, not a
password or secret.

The workflow is scheduled twice an hour, at 17 and 47 minutes past each hour
(UTC). Each successful check publishes up to `max_posts_per_run` unseen items,
oldest first among the feed's currently returned entries. No approval is needed
for individual automatic posts. GitHub may delay or occasionally miss a
scheduled run; the next check catches up with entries still in the feed.

To verify activation, wait for a scheduled run and check that the **infobot**
job actually runs. **No new articles. Nothing published.** is a normal successful
result. A skipped scheduled job means the enable variable or branch needs
checking. A manual `run` can also check for new articles immediately; it can
publish unseen articles even while the automatic enable variable is off.

## Pause the bot

Change `INFOBOT_ENABLED` to `false` to skip future scheduled jobs. Manual modes
remain available. An already running job can finish; cancel it from Actions if
you need an immediate stop. Disabling the **Infobot** workflow in Actions also
stops future manual and scheduled runs until it is re-enabled.

## How duplicate protection works

- `data/state.json` records the account, feed, article IDs and published post
  URIs. No password or API token is written there. Do not delete or edit it.
- An article ID comes from its HTTPS link after removing tracking parameters
  and fragments. The bot keeps the full non-tracking article URL in the post.
- Each article gets a stable post record key in AT Protocol TID syntax. Its
  encoded timestamp is not a publication date; the post's `createdAt` is the
  actual time of posting. Stable keys let a rerun recognise a post even when
  an earlier response was lost or saving history to GitHub failed.
- Writes require the post record to be absent. If a key belongs to different
  content, publishing stops rather than overwriting it.
- After each successful post, progress is saved locally. The workflow commits
  history even if a later article fails. Publishing jobs cannot overlap.

The guarantee applies to this bot's account, keys and URL identity. It cannot
recognise manually posted copies, aliases with entirely different URLs, or
stories separately published by other outlets. Deleting both a public post
and its matching saved history can allow the article to be posted again.

## Monitoring and maintenance

Check the Actions page periodically and keep GitHub notifications for failed
runs enabled. Posting on schedule is unattended, but account credentials,
publisher feeds, GitHub service behaviour and API rules can change.

The history includes `last_checked_date` (UTC), updated after successful checks.
It changes at most once per day when there are no new articles. These saved
checks also create repository activity; GitHub can disable public-repository
schedules after 60 days without activity. Avoid relying on a bot with no owner
to review failures, and re-enable the workflow if GitHub disables it.

The corruption RSS endpoint currently returns a small rolling list (ten items
when checked during setup). During a long outage, stories may disappear from
the feed before the bot sees them. RSS alone does not provide a complete
historical archive. The first baseline intentionally suppresses existing
stories, apart from the one explicitly selected by `test-post`.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Login rejected | Check the two secrets; replace a revoked app password. |
| New workflow missing | Confirm `.github/workflows/infobot-live.yml` is on the default branch. |
| Scheduled job skipped | Set the Actions repository **variable** `INFOBOT_ENABLED` to `true`; use the default branch. |
| No article history | Run `test-post` before using `run` or enabling the schedule. |
| GitHub cannot save history | Check Actions write permissions and branch protection. The token needs permission to commit `data/state.json`. Rerun after fixing this; stable record keys avoid reposting already accepted stories. |
| Wrong account/feed in history | Stop and review the configuration. Do not delete history to bypass the check. |
| Invalid history | Restore the last valid `data/state.json` from GitHub history. |
| API or feed unavailable | Check the failure message and retry later. Successful earlier posts remain recorded. |

The workflow requests `contents: write` only to save article history. On an
organisation repository, its policies may require an administrator's help.
If branch rules require reviews or signed commits, this simple default-branch
state storage needs a separate design before enabling unattended operation.

## Configuration and future feeds

`config.json` contains `source_name`, `feed_url`, `preview_count` (1–10), and
`max_posts_per_run` (1–10). The default maximum is five new articles per run.
This version supports one RSS 2.0 feed. Adding more feeds and optional corruption
classification is a later extension; other outlets' broad feeds should not be
swapped in without adding the relevance-filtering step and a state migration.

The headline is shortened when needed to keep the source and full link within
a conservative 300-code-point limit. The URL is linked through a UTF-8 byte
facet. Posts identify English as their language. Only the title and source
link are shared; source publisher and platform conditions still apply.

## Local commands (optional)

Python 3.12 or newer is sufficient. There are no external packages to install.

```bash
python -m unittest -v
python infobot.py
python infobot.py --check-login
python infobot.py --mode test-post
python infobot.py --mode run
```

The last two commands can publish real posts and update history. Credential
values come from `BSKY_HANDLE` and `BSKY_APP_PASSWORD` environment variables;
for the guided setup, use the existing GitHub secrets instead. Local runs and
GitHub runs must not use separate unsynchronised histories at the same time.

## Documentation status

This README documents the implementation. The final installation and operating
guide PDF will follow after a real post and the automatic schedule have been
verified, so that it describes the tested delivered version. The project's
code licence and any required funding acknowledgement remain to be supplied
by the project before its final release.

## Official references

- OCCRP RSS directory: https://www.occrp.org/en/rss-listing
- Bluesky bot tutorial: https://atproto.com/guides/bot-tutorial
- SDK password authentication: https://atproto.com/guides/sdk-auth
- Record keys: https://atproto.com/specs/record-key
- TID syntax: https://atproto.com/specs/tid
- Put-record API definition: https://github.com/bluesky-social/atproto/blob/main/lexicons/com/atproto/repo/putRecord.json
- GitHub manual workflows: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- GitHub scheduled workflows: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- GitHub Actions variables: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/store-information-in-variables

Prepared for the guided RESPOND Infobot setup, 19 October 2026.
