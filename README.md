# RESPOND Infobot — setup preview

This is the first code stage of the RESPOND corruption-news Infobot. It reads
OCCRP's corruption RSS feed, shows three example posts, and optionally checks
the bot's Bluesky login. **It cannot publish posts and has no automatic schedule.**

This is a setup checkpoint, rather than the completed Infobot deliverable.
Publishing, a persistent record of processed articles, the bot profile label,
and the automatic schedule will be added after this check succeeds. The final
PDF guide will describe that tested working version.

## What you already need

- A Bluesky account for the project.
- A GitHub repository with Actions available.
- GitHub Actions repository secrets named `BSKY_HANDLE` and `BSKY_APP_PASSWORD`.
  The handle should be the full handle, such as `example.bsky.social`; the
  password must be a Bluesky app password. Never put either password in a file.

## Step 1 — upload the files

1. Download and extract `respond-infobot-preview.zip` on your computer.
2. Open your GitHub repository and select **Add file > Upload files**.
3. Upload the five files inside the extracted folder: `infobot.py`,
   `config.json`, `test_infobot.py`, `infobot-preview.yml`, and `README.md`.
   Upload the files themselves, not the ZIP or its enclosing folder.
4. Commit the files to the repository's default branch, normally `main`.

The new README replaces the initial repository README. If you have already
added project-specific text there, keep that text and append these instructions.

## Step 2 — place and run the workflow

1. In the repository, open `infobot-preview.yml` and click the pencil icon
   (**Edit this file**).
2. Replace its filename at the top with
   `.github/workflows/infobot-preview.yml`. Typing the slashes creates the
   folders. Leave its contents unchanged.
3. Click **Commit changes** and confirm a commit to the default branch.
4. Open the repository's **Actions** tab. If asked, enable workflows for the
   repository.
5. Select **Infobot preview**, click **Run workflow**, select the default
   branch, and click the green **Run workflow** button.
6. Open the resulting run, open the **preview** job, and expand
   **Preview feed and check Bluesky login**.

Successful output includes:

```text
Feed OK: ... usable articles.
PREVIEW 1 (not published):
...
Bluesky login OK: "your-handle.bsky.social"
Preview finished. No posts were published.
```

The article count can change. The previews are JSON-quoted in the logs, so
`\n` represents a line break in the proposed post. Logging in creates a temporary
API session; the script neither saves nor prints its tokens and never calls a
publishing endpoint. No automatic runs are configured in this version.

## If the run fails

- **Missing GitHub Actions secrets:** check the two secret names exactly.
- **Bluesky rejected the login:** check the handle and create a fresh app password
  if needed. Update the GitHub secret; never paste it into logs or chat.
- **RSS download failed, timed out, or returned invalid RSS:** retry once. If it
  persists, check the official feed directory and `config.json`.
- **Workflow is missing from Actions:** check that its exact path is
  `.github/workflows/infobot-preview.yml` on the default branch.
- **Actions is disabled by an organisation:** ask the repository administrator
  to allow GitHub Actions and the official checkout/setup-python actions.

You can share a non-sensitive error message for troubleshooting. Keep app
passwords, access tokens, and screenshots showing credentials private.

## Configuration

`config.json` sets the source name, RSS URL, and number of preview posts (1–10).
The current URL is `https://www.occrp.org/en/corruption/feed`.
This setup stage supports RSS 2.0 and HTTPS article links. It does not classify
articles with AI; relevance comes from selecting OCCRP's corruption feed.
It does not copy article bodies or images. The headline is shortened when
necessary while keeping the source and complete link within a conservative
300-character preview limit.

## Local use (optional)

Python 3.12 or newer is sufficient; there are no third-party packages to install.
From the directory containing the files:

```bash
python -m unittest -v
python infobot.py
```

`python infobot.py --check-login` also checks credentials supplied through the
`BSKY_HANDLE` and `BSKY_APP_PASSWORD` environment variables. For this guided setup,
use the GitHub secrets workflow rather than placing credentials in commands.

## Official references

- OCCRP RSS directory: https://www.occrp.org/en/rss-listing
- Bluesky bot tutorial: https://atproto.com/guides/bot-tutorial
- Bluesky password authentication: https://atproto.com/guides/sdk-auth
- GitHub manual workflows:
  https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- GitHub Actions secrets:
  https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

Prepared for the guided RESPOND Infobot setup, 19 October 2026.
