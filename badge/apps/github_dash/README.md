# GitHub Dash

GitHub Dash is a live GitHub dashboard and small GitHub client for the user set in Settings, with your contribution graph, pull requests, repos, READMEs and search over Wi-Fi.

## Requirements

- Wi-Fi details (`WIFI_SSID`, `WIFI_PASSWORD`) and your GitHub username
  (`GITHUB_USERNAME`). Enter them with the **Settings** app or in `secrets.py`.
  Everything in the app is about that user. Without a username it asks you to
  set one in Settings.
- No account, key, payment or server is needed. Public data works without
  signing in.
- Optional: `GITHUB_TOKEN` in `secrets.py` signs you in for notifications, code
  search, private repositories, follow/unfollow and visibility changes (see
  below). GitHub does not allow creating accounts from apps.

## Usage

| Control | Action |
| --- | --- |
| LEFT / RIGHT | Switch page: Home, PRs, Feed, Inbox, Repos, Find |
| UP / DOWN | Scroll or move the selection |
| SELECT | Open the selected item (Repos, Find); refresh elsewhere |
| BACK | Close the current screen, or jump to Home |

- **Home**: display name, @username, followers, following, the year's
  contribution graph, streak, PR and notification counts, and sign-in status.
- **PRs**: open pull requests waiting for your review, then your own.
- **Feed**: your latest public events.
- **Inbox**: unread notifications with a token, otherwise setup steps.
- **Repos**: your repositories, newest push first (including private ones when
  signed in). SELECT opens a repository with its README. UP/DOWN scroll and
  LEFT/RIGHT page through the README. SELECT on your own repository offers to
  make it public or private.
- **Find**: search repositories, users or code with the on-screen keyboard
  (code search needs a token and searches your own code unless you add
  `repo:`, `user:` or `org:`), or list your followers and who you follow. Open
  a user to see their profile, press RIGHT for their repositories, or SELECT
  to follow or unfollow.

Follow/unfollow and visibility changes always ask for confirmation first. They
only work when the token belongs to the same username as Settings. Otherwise
the app explains the mismatch.

The footer shows when the page was last updated, Wi-Fi progress, or problems
such as being offline or rate limited. Data is cached in
`/state/github_dash.json`, so the app opens instantly and keeps working
offline.

## Optional token (sign in)

1. On github.com open **Settings > Developer settings > Personal access tokens >
   Tokens (classic)** and choose **Generate new token (classic)**.
2. Tick only the scopes you want:
   - `notifications` for the Inbox
   - `user:follow` for follow and unfollow
   - `repo` for private repositories and visibility changes. This scope gives
     full control of your repositories, so skip it if you only want to browse.
3. Open the **Mass Storage** app on the badge, edit `secrets.py` on the
   `BADGER` drive and set `GITHUB_TOKEN = "your token"`, then eject.

The token stays on your badge, is never shown on screen, and is only sent to
`api.github.com`. Never commit or share a `secrets.py` that contains it. On each
launch the app checks who the token belongs to (`GET /user`). If GitHub rejects
the token, the app falls back to public data.

## Network use

Background reads and on-demand reads (READMEs, search, profiles) run one at a
time through the firmware's non-blocking fetch, so the screen never freezes.
READMEs are cut to 6 KB and lists to 15-30 items. Conditional requests (ETags)
and GitHub's rate-limit headers keep the app inside the 60 requests per hour
allowed without a token. Search allows 10 queries a minute. Confirmed write
actions pause the screen for a second or two, because the firmware's
non-blocking fetch only supports GET.