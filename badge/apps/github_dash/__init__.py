"""
GitHub Dash: a live GitHub dashboard and small GitHub client over Wi-Fi.

Everything centres on GITHUB_USERNAME from the Settings app. Pages (LEFT/RIGHT):
Home, PRs, Feed, Inbox, Repos (open a repo to read its README) and Find
(search repositories, users and code, followers and following).

With an optional GITHUB_TOKEN that belongs to the same username you can also
follow/unfollow people and change your repositories' visibility, each after an
on-screen confirmation.

Reads run one at a time through the firmware's non-blocking fetch and are
cached in /state/github_dash.json. Confirmed write actions use a short blocking
request because the non-blocking fetch only supports GET.
"""

import gc
import json
import os
import time

import fetch
import missing_details

try:
    import secrets
except ImportError:
    secrets = None

badge.mode(HIRES | VSYNC)
screen.antialias = image.X2

W, H = screen.width, screen.height

# ---------------------------------------------------------------- settings


def setting(key):
    return str(getattr(secrets, key, "") or "").strip()


def valid_handle(name):
    if not name or len(name) > 39 or name[0] == "-":
        return False
    for ch in name:
        if not (ch.isalpha() or ch.isdigit() or ch == "-"):
            return False
    return True


HANDLE = setting("GITHUB_USERNAME").lstrip("@")
TOKEN = setting("GITHUB_TOKEN")
MISSING = missing_details.missing("WIFI_SSID")

WIFI_TIMEOUT = 10
WIFI_RETRIES = 100000  # keep trying quietly; the footer reports progress

if not MISSING:
    import wifi
    try:
        wifi.connect(timeout=WIFI_TIMEOUT, retries=WIFI_RETRIES)
    except Exception as e:  # noqa: BLE001 - network stack errors vary
        print("GitHub Dash: wifi", e)

fetch.AsyncFetch.MAX_HEADER_BYTES = 8192

# ---------------------------------------------------------------- colours

BG = color.rgb(13, 17, 23)
PANEL = color.rgb(22, 27, 34)
BORDER = color.rgb(48, 54, 61)
TEXT = color.rgb(230, 237, 243)
MUTED = color.rgb(125, 133, 144)
GREEN = color.rgb(63, 185, 80)
BLUE = color.rgb(88, 166, 255)
PURPLE = color.rgb(163, 113, 247)
ORANGE = color.rgb(210, 153, 34)
RED = color.rgb(248, 81, 73)
LEVELS = (
    color.rgb(33, 38, 45),
    color.rgb(14, 68, 41),
    color.rgb(0, 109, 50),
    color.rgb(38, 166, 65),
    color.rgb(57, 211, 83),
)

SMALL = font.winds
BODY = font.sins
HEAD = font.absolute
BIG = font.ziplock

# ---------------------------------------------------------------- network

API = "https://api.github.com"
CACHE_FILE = "/state/github_dash.json"
TMP_FILE = "/state/github_dash.tmp"
HEADERS = {
    "User-Agent": "GitHub Universe Badge 2026 (github_dash)",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

MIN = 60
# key, url, refresh seconds, needs token, is api.github.com
SOURCES = (
    ("profile", API + "/users/{u}", 30 * MIN, False, True),
    ("contribs", "https://github.com/{u}.contribs", 30 * MIN, False, False),
    ("reviews", API + "/search/issues?q=review-requested:{u}+type:pr+state:open&sort=updated&per_page=8", 10 * MIN, False, True),
    ("prs", API + "/search/issues?q=author:{u}+type:pr+state:open&sort=updated&per_page=8", 10 * MIN, False, True),
    ("events", API + "/users/{u}/events/public?per_page=12", 10 * MIN, False, True),
    ("notifs", API + "/notifications?per_page=15", 2 * MIN, True, True),
    ("me", API + "/user", 30 * MIN, True, True),
    ("repos", API + "/users/{u}/repos?sort=updated&per_page=20", 15 * MIN, False, True),
)
# with a token that belongs to HANDLE, list private repos too
OWN_REPOS_URL = API + "/user/repos?affiliation=owner&sort=updated&per_page=20"
PAGE_SOURCES = (
    ("profile", "contribs", "me"),
    ("reviews", "prs"),
    ("events",),
    ("notifs",),
    ("repos",),
    (),
)
NPAGES = len(PAGE_SOURCES)
QTMP_FILE = "/state/github_dash.q"
README_BYTES = 6000
README_LINES = 300
MANUAL_GAP_MS = 60 * 1000        # SELECT refresh is ignored more often than this
RATE_BLOCK_MS = 15 * 60 * 1000   # fallback pause when rate limited
RATE_FLOOR = 3                   # stop using the API with this few calls left
RETRY_MIN_MS = 20 * 1000
RETRY_MAX_MS = 10 * 60 * 1000

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def epoch_of(y, mo, d, h, mi, s):
    try:
        return time.mktime((y, mo, d, h, mi, s, 0, 0))
    except (TypeError, ValueError, OverflowError):
        return time.mktime((y, mo, d, h, mi, s, 0, 0, 0))


def iso_epoch(text):
    try:
        return epoch_of(int(text[0:4]), int(text[5:7]), int(text[8:10]),
                        int(text[11:13]), int(text[14:16]), int(text[17:19]))
    except (TypeError, ValueError, IndexError):
        return None


def http_date_epoch(text):
    # "Wed, 28 Oct 2026 23:06:39 GMT"
    try:
        parts = text.split()
        hh, mm, ss = parts[4].split(":")
        return epoch_of(int(parts[3]), MONTHS.index(parts[2]) + 1, int(parts[1]),
                        int(hh), int(mm), int(ss))
    except (AttributeError, ValueError, IndexError):
        return None


SANE_EPOCH = iso_epoch("2025-01-01T00:00:00Z")


def short(text, limit):
    text = str(text or "").replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[:limit - 1] + "~"


def thousands(n):
    s = str(int(n or 0))
    out = ""
    while len(s) > 3:
        out = "," + s[-3:] + out
        s = s[:-3]
    return s + out


# ---------------------------------------------------------------- data

data = {
    "user": HANDLE.lower(),
    "page": 0,
    "fetched": {},   # key -> epoch seconds when last refreshed
    "etags": {},
    "skew": 0,       # server clock minus RTC, applied when the RTC is sane
}


def load_cache():
    global data
    try:
        with open(CACHE_FILE, "r") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(cached, dict):
        return
    if cached.get("user") != HANDLE.lower():
        data["page"] = cached.get("page", 0) if isinstance(cached.get("page"), int) else 0
        return  # a different user's cache: start fresh
    for key in ("fetched", "etags"):
        if not isinstance(cached.get(key), dict):
            cached[key] = {}
    data = cached


def save_cache():
    try:
        with open(CACHE_FILE + ".new", "w") as f:
            json.dump(data, f)
        try:
            os.remove(CACHE_FILE)
        except OSError:
            pass
        os.rename(CACHE_FILE + ".new", CACHE_FILE)
    except OSError as e:
        print("GitHub Dash: cache", e)


try:
    os.mkdir("/state")
except OSError:
    pass
load_cache()
if not isinstance(data.get("page"), int) or not 0 <= data["page"] < NPAGES:
    data["page"] = 0

server_ref = None  # (server epoch, badge.ticks) from the last Date header


def now_epoch():
    if server_ref:
        return server_ref[0] + (badge.ticks - server_ref[1]) // 1000
    t = time.time()
    if SANE_EPOCH and t > SANE_EPOCH:
        return t + data.get("skew", 0)
    return None


def ago(epoch):
    now = now_epoch()
    if not epoch or not now:
        return ""
    s = int(max(0, now - epoch))
    if s < 60:
        return "now"
    if s < 3600:
        return str(s // 60) + "m"
    if s < 86400:
        return str(s // 3600) + "h"
    if s < 86400 * 60:
        return str(s // 86400) + "d"
    return str(s // (86400 * 30)) + "mo"


# --------------------------------------------------------------- parsers


def repo_of(url):
    # https://api.github.com/repos/owner/name -> owner/name
    parts = (url or "").split("/repos/")
    return parts[-1] if len(parts) > 1 else ""


def parse_profile(raw):
    return {
        "login": raw.get("login") or HANDLE,
        "name": short(raw.get("name") or "", 40),
        "followers": raw.get("followers") or 0,
        "following": raw.get("following") or 0,
        "repos": raw.get("public_repos") or 0,
    }


def parse_contribs(raw):
    weeks = raw.get("weeks") or []
    weeks = weeks[-53:]
    grid = []
    counts = []
    for week in weeks:
        col = [" "] * 7
        for day in week.get("contribution_days") or []:
            wd = day.get("weekday", 0)
            if 0 <= wd < 7:
                level = day.get("level", 0) or 0
                col[wd] = str(min(4, max(0, level)))
                counts.append(day.get("count", 0) or 0)
        grid.append("".join(col))
    streak = 0
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1  # today may simply not have started yet
    while i >= 0 and counts[i] > 0:
        streak += 1
        i -= 1
    return {
        "grid": grid,
        "total": raw.get("total_contributions") or sum(counts),
        "today": counts[-1] if counts else 0,
        "streak": streak,
        "best": max(counts) if counts else 0,
    }


def parse_search(raw):
    items = []
    for item in (raw.get("items") or [])[:8]:
        items.append({
            "r": repo_of(item.get("repository_url")),
            "n": item.get("number") or 0,
            "t": short(item.get("title"), 90),
            "d": bool(item.get("draft")),
            "c": item.get("comments") or 0,
            "u": iso_epoch(item.get("updated_at") or ""),
        })
    return {"total": raw.get("total_count") or len(items), "items": items}


def describe_event(ev):
    kind = ev.get("type") or ""
    p = ev.get("payload") or {}
    action = p.get("action") or ""
    num = p.get("number") or (p.get("pull_request") or {}).get("number") or (p.get("issue") or {}).get("number")
    tag = "#" + str(num) if num else ""
    if kind == "PushEvent":
        ref = (p.get("ref") or "").split("/")[-1]
        size = p.get("size")
        if size:
            return GREEN, "pushed {} commit{} to {}".format(size, "" if size == 1 else "s", ref)
        return GREEN, "pushed to " + (ref or "a branch")
    if kind == "PullRequestEvent":
        pr = p.get("pull_request") or {}
        if action == "closed" and pr.get("merged"):
            action = "merged"
        return PURPLE, "{} PR {}".format(action or "updated", tag)
    if kind == "PullRequestReviewEvent":
        return PURPLE, "reviewed PR " + tag
    if kind == "PullRequestReviewCommentEvent":
        return PURPLE, "commented on PR " + tag
    if kind == "IssuesEvent":
        return ORANGE, "{} issue {}".format(action or "updated", tag)
    if kind == "IssueCommentEvent":
        return ORANGE, "commented on " + tag
    if kind == "CreateEvent":
        what = p.get("ref_type") or "repository"
        ref = p.get("ref") or ""
        return GREEN, "created {} {}".format(what, ref).strip()
    if kind == "DeleteEvent":
        return RED, "deleted {} {}".format(p.get("ref_type") or "", p.get("ref") or "").strip()
    if kind == "ForkEvent":
        return BLUE, "forked"
    if kind == "WatchEvent":
        return ORANGE, "starred"
    if kind == "ReleaseEvent":
        rel = (p.get("release") or {}).get("tag_name") or ""
        return BLUE, "released " + rel
    if kind == "PublicEvent":
        return BLUE, "made public"
    if kind == "MemberEvent":
        return BLUE, "added a collaborator"
    if kind == "GollumEvent":
        return BLUE, "edited the wiki"
    return MUTED, kind.replace("Event", "").lower() or "activity"


def parse_events(raw):
    events = []
    if not isinstance(raw, list):
        return events
    for ev in raw[:12]:
        if not isinstance(ev, dict):
            continue
        _, text = describe_event(ev)
        events.append({
            "k": ev.get("type") or "",
            "x": short(text, 60),
            "r": (ev.get("repo") or {}).get("name") or "",
            "u": iso_epoch(ev.get("created_at") or ""),
        })
    return events


def parse_notifs(raw):
    items = []
    if not isinstance(raw, list):
        return {"total": 0, "items": items}
    for n in raw[:15]:
        subject = n.get("subject") or {}
        items.append({
            "k": subject.get("type") or "",
            "t": short(subject.get("title"), 90),
            "r": (n.get("repository") or {}).get("full_name") or "",
            "why": (n.get("reason") or "").replace("_", " "),
            "u": iso_epoch(n.get("updated_at") or ""),
        })
    return {"total": len(raw), "items": items}


def parse_me(raw):
    return {"login": raw.get("login") or ""}


def parse_repo(r):
    return {
        "f": r.get("full_name") or "",
        "d": short(r.get("description") or "", 140),
        "s": r.get("stargazers_count") or 0,
        "k": r.get("forks_count") or 0,
        "l": r.get("language") or "",
        "p": bool(r.get("private")),
        "fk": bool(r.get("fork")),
        "u": iso_epoch(r.get("pushed_at") or r.get("updated_at") or ""),
    }


def parse_repos(raw):
    if isinstance(raw, dict):
        raw = raw.get("items") or []
    if not isinstance(raw, list):
        return []
    return [parse_repo(r) for r in raw[:20] if isinstance(r, dict)]


def parse_users(raw):
    if isinstance(raw, dict):
        raw = raw.get("items") or []
    if not isinstance(raw, list):
        return []
    return [{"login": u.get("login") or "", "type": u.get("type") or ""} for u in raw[:30] if isinstance(u, dict)]


def parse_code(raw):
    items = []
    for c in (raw.get("items") or [])[:15]:
        repo = c.get("repository") or {}
        items.append({"path": short(c.get("path") or "", 80), "repo": parse_repo(repo)})
    return items


PARSERS = {
    "me": parse_me,
    "repos": parse_repos,
    "profile": parse_profile,
    "contribs": parse_contribs,
    "reviews": parse_search,
    "prs": parse_search,
    "events": parse_events,
    "notifs": parse_notifs,
}

# ------------------------------------------------------------- scheduler


class Net:
    def __init__(self):
        self.active = None        # (source, request)
        self.loaded_at = {}       # key -> badge.ticks for this session
        self.retry_at = {}        # key -> badge.ticks before which not to retry
        self.failures = {}        # key -> consecutive failures
        self.forced = set()
        self.api_block_until = 0
        self.last_manual = -MANUAL_GAP_MS
        self.status = ""          # transient footer text
        self.problem = None       # persistent footer problem
        self.offline = False
        self.user_missing = False
        self.token_bad = False
        self.notif_error = None
        self.rate_left = None
        self.last_ok_ticks = None

    def token_owner(self):
        return (data.get("me") or {}).get("login") or ""

    def verified(self):
        login = self.token_owner()
        return bool(TOKEN and not self.token_bad and "me" in self.loaded_at
                    and login and login.lower() == HANDLE.lower())

    def headers_for(self, src):
        key, _, _, _, is_api = src
        h = dict(HEADERS)
        etag = data["etags"].get(key)
        if etag and key in data:
            h["If-None-Match"] = etag
        if is_api and TOKEN and not self.token_bad:
            h["Authorization"] = "Bearer " + TOKEN
        return h

    def age(self, key):
        now = now_epoch()
        stamp = data["fetched"].get(key)
        if now and stamp:
            return now - stamp
        if key in self.loaded_at:
            return (badge.ticks - self.loaded_at[key]) // 1000
        return None

    def is_due(self, src):
        key, _, every, needs_token, is_api = src
        if needs_token and (not TOKEN or self.token_bad):
            return False
        if self.user_missing and key != "notifs":
            return False
        if is_api and badge.ticks < self.api_block_until:
            return False
        if badge.ticks < self.retry_at.get(key, 0):
            return False
        if key in self.forced:
            return True
        if key == "me" and key not in self.loaded_at:
            return True   # always re-check who the token belongs to
        age = self.age(key)
        return age is None or age >= every or key not in data

    def next_source(self, page):
        due = [s for s in SOURCES if self.is_due(s)]
        if not due:
            return None
        for s in due:
            if s[0] in PAGE_SOURCES[page]:
                return s
        return due[0]

    def refresh(self):
        if badge.ticks - self.last_manual < MANUAL_GAP_MS:
            self.status = "just refreshed - wait a minute"
            return
        self.last_manual = badge.ticks
        for s in SOURCES:
            self.forced.add(s[0])
            self.retry_at.pop(s[0], None)
        self.status = "refreshing..."

    def pump(self, page):
        if self.problem and self.problem.startswith("rate") and badge.ticks >= self.api_block_until:
            self.problem = None
        if self.active:
            self.poll()
            return
        if query.busy():
            return
        if MISSING or not valid_handle(HANDLE):
            return
        src = self.next_source(page)
        if src is None:
            return
        if not wifi_ready():
            self.offline = True
            return
        self.offline = False
        url = src[1].format(u=HANDLE)
        if src[0] == "repos" and self.verified():
            url = OWN_REPOS_URL
        try:
            try:
                os.remove(TMP_FILE)
            except OSError:
                pass
            req = fetch.url(url, headers=self.headers_for(src)).to(TMP_FILE)
            self.active = (src, req)
            self.status = "fetching " + src[0] + "..."
        except Exception as e:  # noqa: BLE001
            self.fail(src, None, str(e))

    def poll(self):
        src, req = self.active
        try:
            ok = bool(req)
            err = req.error
        except Exception as e:  # noqa: BLE001
            ok, err = False, str(e) or "fetch failed"
        if not ok and not err:
            return
        self.active = None
        raw = getattr(req, "_fetch", None)
        code = getattr(raw, "http_status", None)
        headers = getattr(raw, "http_response_headers", None) or {}
        self.read_headers(src, headers)
        if not code and err and "HTTP error" in err:
            try:
                code = int(err.split()[-1])
            except ValueError:
                code = None
        if code == 304:
            self.done(src, None, headers)
        elif ok and (code is None or 200 <= code < 300):
            self.done(src, TMP_FILE, headers)
        else:
            self.fail(src, code, err or "HTTP error {}".format(code))
        try:
            os.remove(TMP_FILE)
        except OSError:
            pass
        gc.collect()

    def read_headers(self, src, headers):
        global server_ref
        date = http_date_epoch(headers.get("Date") or headers.get("date") or "")
        if date:
            server_ref = (date, badge.ticks)
            rtc = time.time()
            if SANE_EPOCH and rtc > SANE_EPOCH:
                data["skew"] = date - rtc
        if src[4]:
            try:
                left = int(headers.get("X-RateLimit-Remaining"))
                reset = int(headers.get("X-RateLimit-Reset"))
            except (TypeError, ValueError):
                return
            if "search" in src[1]:
                return  # separate, per-minute search bucket
            self.rate_left = left
            if left <= RATE_FLOOR and date:
                wait = max(60, reset - date) * 1000
                self.api_block_until = badge.ticks + wait
                self.problem = "rate limit low - pausing {}m".format(wait // 60000 + 1)

    def done(self, src, path, headers):
        key = src[0]
        if path:
            was_verified = self.verified()
            try:
                with open(path, "r") as f:
                    raw = json.load(f)
                data[key] = PARSERS[key](raw)
                del raw
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                self.fail(src, None, "bad data: " + str(e))
                return
            etag = headers.get("ETag") or headers.get("etag")
            if etag:
                data["etags"][key] = etag
            if key == "me" and self.verified() != was_verified:
                # repo list switches between public-only and owner (incl. private)
                data["etags"].pop("repos", None)
                self.forced.add("repos")
        if key == "notifs":
            self.notif_error = None
        self.loaded_at[key] = badge.ticks
        now = now_epoch()
        if now:
            data["fetched"][key] = now
        self.failures[key] = 0
        self.forced.discard(key)
        if self.problem and not self.problem.startswith("rate"):
            self.problem = None
        self.status = ""
        self.last_ok_ticks = badge.ticks
        rebuild()
        save_cache()

    def fail(self, src, code, err):
        key, _, _, _, is_api = src
        print("GitHub Dash:", key, err)
        self.forced.discard(key)
        n = self.failures.get(key, 0) + 1
        self.failures[key] = n
        delay = min(RETRY_MAX_MS, RETRY_MIN_MS * (2 ** min(n - 1, 6)))
        self.status = ""
        if code == 401 and is_api and TOKEN and not self.token_bad:
            self.token_bad = True
            self.notif_error = "GitHub rejected the token (401)."
            self.retry_at[key] = 0
            return
        if code in (403, 429):
            if key == "notifs" and TOKEN:
                self.notif_error = "Token can't read notifications. Use a classic token with the 'notifications' scope."
                self.retry_at[key] = badge.ticks + 30 * MIN * 1000
                return
            if is_api and "search" not in src[1]:
                if not (badge.ticks < self.api_block_until):
                    self.api_block_until = badge.ticks + RATE_BLOCK_MS
                self.problem = "rate limited - using cache"
            delay = max(delay, RATE_BLOCK_MS if "search" not in src[1] else 2 * MIN * 1000)
        elif code == 404 and key == "profile":
            self.user_missing = True
            self.problem = "user @" + HANDLE + " not found"
            return
        elif code in (404, 422):
            delay = 30 * MIN * 1000
        elif code is None:
            self.problem = "network error - using cache"
        else:
            self.problem = "GitHub error {} - using cache".format(code)
        self.retry_at[key] = badge.ticks + delay


net = Net()
wifi_text = ""


def wifi_ready():
    global wifi_text
    try:
        if wifi.connect():
            return True
        code, text = wifi.status()
        wifi_text = text
    except Exception as e:  # noqa: BLE001
        wifi_text = str(e)
    return False


# --------------------------------------------------------------- drawing

TABS = ("Home", "PRs", "Feed", "Inbox", "Repos", "Find")
TOP = 22
FOOT = 15
BODY_RECT = (0, TOP, W, H - TOP - FOOT)
ROW_H = 28
HEAD_H = 18
SELECTABLE = (4, 5)

scroll = [0] * NPAGES
rows = [[] for _ in range(NPAGES)]   # per page: (kind, ...) tuples ready to draw


def measure(text):
    return screen.measure_text(text)[0]


def fit(text, width):
    text = str(text)
    if measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid] + "...") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "..."


def wrap(text, width, max_lines=4):
    words = str(text).split(" ")
    lines = []
    line = ""
    for word in words:
        trial = (line + " " + word) if line else word
        if measure(trial) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
        if len(lines) >= max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    return lines


EVENT_COLOURS = {
    "PushEvent": GREEN, "CreateEvent": GREEN, "PullRequestEvent": PURPLE,
    "PullRequestReviewEvent": PURPLE, "PullRequestReviewCommentEvent": PURPLE,
    "IssuesEvent": ORANGE, "IssueCommentEvent": ORANGE, "WatchEvent": ORANGE,
    "DeleteEvent": RED,
}


def rebuild():
    """Pre-measure and truncate list text so frames only draw."""
    screen.font = BODY
    text_w = W - 20
    pr_rows = []
    for key, label in (("reviews", "Review requested"), ("prs", "Your open PRs")):
        block = data.get(key)
        if block is None:
            pr_rows.append(("head", label, "loading..."))
            continue
        pr_rows.append(("head", label, str(block.get("total", 0))))
        if not block.get("items"):
            pr_rows.append(("note", "nothing here - nice!" if key == "reviews" else "no open pull requests"))
        for item in block.get("items", []):
            colour = MUTED if item.get("d") else GREEN
            meta = "{}#{}".format(item.get("r", ""), item.get("n", 0))
            extra = (" draft" if item.get("d") else "") + (" {}c".format(item["c"]) if item.get("c") else "")
            pr_rows.append(("item", colour, fit(meta + extra, text_w - 30), item.get("u"), fit(item.get("t", ""), text_w)))
    rows[1] = pr_rows

    ev_rows = []
    events = data.get("events")
    if events is None:
        ev_rows.append(("note", "loading your public activity..."))
    elif not events:
        ev_rows.append(("note", "no public activity in the last 90 days"))
    for ev in events or []:
        colour = EVENT_COLOURS.get(ev.get("k"), BLUE)
        ev_rows.append(("item", colour, fit(ev.get("r", ""), text_w - 30), ev.get("u"), fit(ev.get("x", ""), text_w)))
    rows[2] = ev_rows

    n_rows = []
    notifs = data.get("notifs")
    for item in (notifs or {}).get("items", []):
        kind = item.get("k", "")
        colour = PURPLE if kind == "PullRequest" else ORANGE if kind == "Issue" else BLUE
        meta = "{} - {}".format(item.get("r", ""), item.get("why", ""))
        n_rows.append(("item", colour, fit(meta, text_w - 30), item.get("u"), fit(item.get("t", ""), text_w)))
    if notifs is not None and not n_rows:
        n_rows.append(("note", "inbox zero - no unread notifications"))
    rows[3] = n_rows

    repo_rows = []
    repos = data.get("repos")
    if repos is None:
        repo_rows.append(("note", "loading repositories..."))
    elif not repos:
        repo_rows.append(("note", "no repositories yet"))
    for r in repos or []:
        repo_rows.append(repo_row(r, text_w))
    rows[4] = repo_rows

    rows[5] = [("item", c, sub, None, label, ("find", k)) for label, sub, k, c in FIND_MENU]

    for page in range(NPAGES):
        scroll[page] = min(scroll[page], max(0, len(rows[page]) - 1))


FIND_MENU = (
    ("Search repositories", "find repos by name or topic", "repos", GREEN),
    ("Search users", "find people and organisations", "users", BLUE),
    ("Search code", "text inside files (needs a token)", "code", PURPLE),
    ("Your followers", "people following you", "followers", ORANGE),
    ("Who you follow", "people you follow", "following", ORANGE),
)


def repo_meta(r):
    bits = ["private" if r.get("p") else "public"]
    if r.get("fk"):
        bits.append("fork")
    if r.get("l"):
        bits.append(r["l"])
    if r.get("s"):
        bits.append("{} stars".format(thousands(r["s"])))
    return "  ".join(bits)


def repo_row(r, text_w):
    colour = ORANGE if r.get("p") else GREEN
    name = r.get("f", "")
    if name.lower().startswith(HANDLE.lower() + "/"):
        name = name[len(HANDLE) + 1:]
    title = name + ("  - " + r["d"] if r.get("d") else "")
    return ("item", colour, fit(repo_meta(r), text_w - 30), r.get("u"), fit(title, text_w), ("repo", r))


def user_row(u, text_w):
    return ("item", BLUE, u.get("type", "").lower() or "user", None, fit("@" + u.get("login", ""), text_w), ("user", u.get("login", "")))


def code_row(c, text_w):
    r = c.get("repo") or {}
    return ("item", PURPLE, fit(r.get("f", ""), text_w - 30), None, fit(c.get("path", ""), text_w), ("repo", r))


def row_height(row):
    return HEAD_H if row[0] == "head" else (16 if row[0] == "note" else ROW_H)


def draw_rows(page):
    draw_list(rows[page], scroll[page], page in SELECTABLE)


def draw_list(items, top, cursor=False, y0=None):
    y = TOP + 4 if y0 is None else y0
    bottom = H - FOOT
    i = top
    screen.clip = rect(0, y - 2, W, bottom - y + 2)
    while i < len(items) and y < bottom:
        row = items[i]
        kind = row[0]
        if cursor and i == top and kind == "item":
            screen.pen = PANEL
            screen.rectangle(4, y - 2, W - 10, ROW_H)
            screen.pen = BORDER
            screen.rectangle(4, y - 2, 1, ROW_H)
        if kind == "head":
            screen.font = HEAD
            screen.pen = TEXT
            screen.text(row[1], 8, y)
            screen.font = BODY
            label = row[2]
            screen.pen = MUTED
            screen.text(label, W - 8 - measure(label), y + 3)
        elif kind == "note":
            screen.font = BODY
            screen.pen = MUTED
            screen.text(row[1], 14, y + 1)
        else:
            colour, meta, stamp, title = row[1], row[2], row[3], row[4]
            screen.pen = colour
            screen.rectangle(8, y + 3, 3, ROW_H - 7)
            screen.font = SMALL
            screen.pen = MUTED
            screen.text(meta, 16, y)
            when = ago(stamp)
            if when:
                screen.text(when, W - 8 - measure(when), y)
            screen.font = BODY
            screen.pen = TEXT
            screen.text(title, 16, y + 13)
        y += row_height(row)
        i += 1
    screen.clip = rect(0, 0, W, H)
    if len(items) > 1:
        # scrollbar
        track = H - FOOT - TOP - 8
        knob = max(10, track // max(1, len(items)) * 3)
        pos = TOP + 4 + (track - knob) * top // max(1, len(items) - 1)
        screen.pen = BORDER
        screen.rectangle(W - 3, TOP + 4, 2, track)
        screen.pen = MUTED
        screen.rectangle(W - 3, pos, 2, knob)


def draw_tabs(page):
    screen.pen = PANEL
    screen.rectangle(0, 0, W, TOP - 1)
    screen.pen = BORDER
    screen.rectangle(0, TOP - 1, W, 1)
    tab_w = W // len(TABS)
    screen.font = BODY
    for i, name in enumerate(TABS):
        label = name
        if i == 1 and data.get("reviews"):
            label += " " + str(data["reviews"].get("total", 0))
        if i == 3 and data.get("notifs"):
            label += " " + str(data["notifs"].get("total", 0))
        x = i * tab_w + (tab_w - measure(label)) // 2
        screen.pen = TEXT if i == page else MUTED
        screen.text(label, x, 5)
        if i == page:
            screen.pen = color.rgb(247, 129, 102)
            screen.rectangle(i * tab_w + 10, TOP - 3, tab_w - 20, 2)


def footer_text():
    if net.problem:
        return RED, net.problem
    if net.offline:
        return ORANGE, "wifi: " + (wifi_text or "connecting...")
    if query.busy():
        return BLUE, query.status or "loading..."
    if net.active:
        return BLUE, net.status
    if net.status:
        return MUTED, net.status
    newest = None
    for key in PAGE_SOURCES[page_index()]:
        stamp = data["fetched"].get(key)
        if stamp and (newest is None or stamp > newest):
            newest = stamp
    when = ago(newest)
    if when:
        return MUTED, "updated " + (when if when == "now" else when + " ago")
    return MUTED, "@" + HANDLE


def draw_footer():
    colour, text = footer_text()
    y = H - FOOT
    screen.pen = PANEL
    screen.rectangle(0, y, W, FOOT)
    screen.font = SMALL
    hint = view_hint() if views else ("SELECT open" if page_index() in SELECTABLE else "SELECT refresh")
    screen.pen = MUTED
    screen.text(hint, W - 6 - measure(hint), y + 2)
    screen.pen = colour
    screen.text(fit(text, W - 20 - measure(hint)), 6, y + 2)
    if net.active:
        # little activity pulse
        dots = (badge.ticks // 250) % 4
        screen.pen = BLUE
        for d in range(dots):
            screen.rectangle(W - 10 - measure(hint) - d * 5, y + 7, 3, 3)


GRAPH_STEP = 6
GRAPH_CELL = 5


try:
    MARK = image.load("/system/apps/github_dash/assets/mark.png")
except Exception:
    MARK = None


def draw_home():
    profile = data.get("profile") or {}
    contribs = data.get("contribs")
    y = TOP + 6
    screen.font = BIG
    name = profile.get("name") or profile.get("login") or HANDLE
    screen.pen = TEXT
    nx = 8
    if MARK:
        screen.blit(MARK, rect(8, y + 1, 20, 20))
        nx = 34
    screen.text(fit(name, W - nx - 8), nx, y)
    y += 23
    screen.font = BODY
    screen.pen = MUTED
    login = "@" + (profile.get("login") or HANDLE)
    screen.text(login, 8, y)
    if profile:
        stats = "{} followers  {} following  {} repos".format(
            thousands(profile.get("followers")), thousands(profile.get("following")), thousands(profile.get("repos")))
        stats = fit(stats, W - 24 - measure(login))
        screen.text(stats, W - 8 - measure(stats), y)
    y += 18

    # contribution graph: 53 weeks x 7 days
    grid = (contribs or {}).get("grid") or []
    weeks = len(grid) or 53
    x0 = (W - weeks * GRAPH_STEP) // 2
    for wx in range(weeks):
        col = grid[wx] if wx < len(grid) else "0000000"
        for d in range(7):
            ch = col[d] if d < len(col) else " "
            if ch == " ":
                continue
            level = ord(ch) - 48
            if contribs is None:
                level = 0
            screen.pen = LEVELS[level if 0 <= level < 5 else 0]
            screen.rectangle(x0 + wx * GRAPH_STEP, y + d * GRAPH_STEP, GRAPH_CELL, GRAPH_CELL)
    y += 7 * GRAPH_STEP + 6

    screen.font = HEAD
    if contribs:
        screen.pen = TEXT
        total = thousands(contribs.get("total")) + " contributions"
        screen.text(total, 8, y)
        screen.font = BODY
        screen.pen = MUTED
        screen.text("in the last year", 12 + measure_head(total), y + 3)
        y += 20
        streak = contribs.get("streak", 0)
        line = "streak {} day{}   today {}   best day {}".format(
            streak, "" if streak == 1 else "s", contribs.get("today", 0), contribs.get("best", 0))
        screen.pen = GREEN if streak else MUTED
        screen.text(line, 8, y)
    else:
        screen.pen = MUTED
        screen.text("loading contributions...", 8, y)
        y += 20
    y += 18

    # summary tiles
    tiles = (
        ("reviews", "to review", PURPLE),
        ("prs", "open PRs", GREEN),
        ("notifs", "unread", BLUE),
    )
    tile_w = (W - 16 - 2 * 6) // 3
    for i, (key, label, colour) in enumerate(tiles):
        x = 8 + i * (tile_w + 6)
        screen.pen = PANEL
        screen.rectangle(x, y, tile_w, 40)
        screen.pen = colour
        screen.rectangle(x, y, 3, 40)
        block = data.get(key)
        if key == "notifs" and not TOKEN:
            value = "-"
            label = "add token"
        else:
            value = "..." if block is None else str(block.get("total", 0))
        screen.font = BIG
        screen.pen = TEXT
        screen.text(value, x + 10, y + 2)
        screen.font = SMALL
        screen.pen = MUTED
        screen.text(label, x + 10, y + 25)

    # sign-in status
    y += 46
    screen.font = SMALL
    colour, text = signin_status()
    screen.pen = colour
    screen.text(fit(text, W - 16), 8, y)


def signin_status():
    if not TOKEN:
        return MUTED, "read-only: public data for @" + HANDLE + " (token optional)"
    if net.token_bad:
        return RED, "token rejected by GitHub - using public data"
    owner = net.token_owner()
    if not owner:
        return MUTED, "checking token..."
    if owner.lower() != HANDLE.lower():
        return RED, "token is for @{}, not @{} - write actions off".format(owner, HANDLE)
    return GREEN, "signed in as @" + owner + " - follow and visibility enabled"


def measure_head(text):
    old = screen.font
    screen.font = HEAD
    width = measure(text)
    screen.font = old
    return width


TOKEN_HELP = (
    "Notifications, code search, private repos, follow and visibility need a personal access token. Everything else works without one.",
    "1. github.com > Settings > Developer settings > Tokens (classic) > Generate.",
    "2. Tick only what you want: 'notifications', 'user:follow', 'repo'.",
    "3. Open Mass Storage, edit secrets.py on BADGER and set GITHUB_TOKEN = \"...\"",
    "The token must belong to your Settings username. It stays on the badge.",
)
help_lines = []


def draw_inbox():
    if TOKEN and not net.token_bad and not net.notif_error:
        if data.get("notifs") is None:
            screen.font = BODY
            screen.pen = MUTED
            screen.text("loading notifications...", 14, TOP + 8)
            return
        draw_rows(3)
        return
    y = TOP + 6
    screen.font = HEAD
    screen.pen = TEXT
    title = "Optional: notifications"
    if TOKEN:
        title = "Token problem"
    screen.text(title, 8, y)
    y += 20
    screen.font = BODY
    if TOKEN:
        screen.pen = RED
        for line in wrap(net.notif_error or "GitHub rejected the token.", W - 16, 3):
            screen.text(line, 8, y)
            y += 13
        y += 4
    if not help_lines:
        for i, para in enumerate(TOKEN_HELP):
            for line in wrap(para, W - 16, 3):
                help_lines.append((i, line))
            help_lines.append((i, ""))
    for i, line in help_lines:
        screen.pen = TEXT if 1 <= i <= 3 else MUTED
        if line:
            screen.text(line, 8, y)
            y += 13
        else:
            y += 4


def draw_message(title, lines, colour=TEXT):
    screen.pen = BG
    screen.clear()
    screen.font = HEAD
    screen.pen = colour
    tw = measure(title)
    y = 60
    screen.text(title, (W - tw) // 2, y)
    y += 26
    screen.font = BODY
    screen.pen = MUTED
    for para in lines:
        for line in wrap(para, W - 32, 4):
            screen.text(line, (W - measure(line)) // 2, y)
            y += 14
        y += 6


def page_index():
    return data["page"]


# ---------------------------------------------------------------- client


def quote(text):
    out = ""
    for ch in text:
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in "-_.~":
            out += ch
        elif ch == " ":
            out += "+"
        else:
            for b in ch.encode("utf-8"):
                out += "%{:02X}".format(b)
    return out


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def err_text(code, err):
    if code == 401:
        return "GitHub rejected the token (401)."
    if code in (403, 429):
        return "GitHub refused (rate limit or permissions). Try again in a minute."
    if code == 404:
        return "Not found (it may be private or renamed)."
    if code == 422:
        return "GitHub couldn't run that query."
    if code:
        return "GitHub error {}.".format(code)
    return "Network problem: " + short(err or "no connection", 60)


class Query:
    """One on-demand GET at a time (README, search, profiles), never blocking."""

    def __init__(self):
        self.req = None
        self.pending = None   # (url, accept, callback, label, owner)
        self.cb = None
        self.url = ""
        self.owner = None
        self.status = ""

    def busy(self):
        return self.req is not None or self.pending is not None

    def ask(self, url, callback, accept=None, label="loading", owner=None):
        self.cancel()
        self.pending = (url, accept, callback, label, owner)
        self.owner = owner
        self.status = label + "..."

    def cancel(self):
        if self.req is not None:
            try:
                self.req._fetch._close_socket()
            except Exception:  # noqa: BLE001
                pass
        self.req = None
        self.pending = None
        self.cb = None
        self.owner = None
        self.status = ""

    def pump(self):
        if self.req is not None:
            self.poll()
            return
        if self.pending is None or net.active:
            return
        if not wifi_ready():
            self.status = "waiting for wifi..."
            return
        url, accept, cb, label, owner = self.pending
        self.pending = None
        h = dict(HEADERS)
        if accept:
            h["Accept"] = accept
        if TOKEN and not net.token_bad:
            h["Authorization"] = "Bearer " + TOKEN
        try:
            os.remove(QTMP_FILE)
        except OSError:
            pass
        self.url, self.cb, self.owner = url, cb, owner
        try:
            self.req = fetch.url(url, headers=h).to(QTMP_FILE)
            self.status = label + "..."
        except Exception as e:  # noqa: BLE001
            self.cb = None
            self.status = ""
            cb(None, None, str(e))

    def poll(self):
        req = self.req
        try:
            ok = bool(req)
            err = req.error
        except Exception as e:  # noqa: BLE001
            ok, err = False, str(e) or "fetch failed"
        if not ok and not err:
            return
        self.req = None
        raw = getattr(req, "_fetch", None)
        code = getattr(raw, "http_status", None)
        headers = getattr(raw, "http_response_headers", None) or {}
        net.read_headers(("query", self.url, 0, False, True), headers)
        if not code and err and "HTTP error" in err:
            try:
                code = int(err.split()[-1])
            except ValueError:
                code = None
        if code == 401 and TOKEN:
            net.token_bad = True
        cb, self.cb = self.cb, None
        self.status = ""
        success = ok and (code is None or 200 <= code < 300)
        try:
            if cb:
                cb(QTMP_FILE if success else None, code, None if success else (err or "HTTP error {}".format(code)))
        except Exception as e:  # noqa: BLE001 - bad data must not crash the app
            print("GitHub Dash: query", e)
        try:
            os.remove(QTMP_FILE)
        except OSError:
            pass
        gc.collect()


query = Query()
views = []   # stack of overlay screens; the last one is shown


def push_view(v):
    views.append(v)
    return v


def pop_view():
    v = views.pop()
    if query.owner is v:
        query.cancel()


def write_block():
    """Why write actions are unavailable, or None when they are allowed."""
    if not TOKEN:
        return "Sign in first: add GITHUB_TOKEN to secrets.py (see the Inbox page)."
    if net.token_bad:
        return "GitHub rejected the token, so write actions are off."
    owner = net.token_owner()
    if not owner or "me" not in net.loaded_at:
        return "Still checking who the token belongs to - try again in a moment."
    if owner.lower() != HANDLE.lower():
        return "Token is for @{}, not @{} from Settings - write actions are off.".format(owner, HANDLE)
    return None


def write_request(method, path, body=None):
    """Blocking write, only ever run after the user confirms on screen."""
    if not wifi_ready():
        return None, "Wi-Fi is not connected."
    import requests
    h = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": HEADERS["Accept"],
        "X-GitHub-Api-Version": HEADERS["X-GitHub-Api-Version"],
        "Authorization": "Bearer " + TOKEN,
    }
    if body is None:
        h["Content-Length"] = "0"
    else:
        h["Content-Type"] = "application/json"
    resp = None
    try:
        resp = requests.request(method, API + path, data=body, headers=h)
        code = resp.status_code
        if code == 401:
            net.token_bad = True
        return code, None
    except Exception as e:  # noqa: BLE001
        return None, str(e) or "request failed"
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
        gc.collect()


def write_error(code, err):
    if code == 401:
        return "GitHub rejected the token (401)."
    if code is None:
        return "Network problem: " + short(err or "no connection", 60)
    return "GitHub error {}.".format(code)


def confirm(title, lines, go):
    push_view({"t": "confirm", "title": title, "lines": lines, "go": go, "state": "ask", "drawn": False, "result": None})


# ---- README


def clean_md(s):
    while True:   # drop images, including badge images inside links
        a = s.find("![")
        b = s.find("](", a) if a >= 0 else -1
        c = s.find(")", b) if b >= 0 else -1
        if c < 0:
            break
        s = s[:a] + s[c + 1:]
    out = ""
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "<":
            j = s.find(">", i)
            if j > 0:
                i = j + 1
                continue
        if ch == "[":
            j = s.find("]", i)
            if j > 0:
                out += s[i + 1:j]
                i = j + 1
                if i < n and s[i] == "(":
                    k = s.find(")", i)
                    if k > 0:
                        i = k + 1
                continue
        if ch in "*`|":
            i += 1
            continue
        out += ch
        i += 1
    return out.strip()


def readme_lines(text):
    out = []
    in_code = False
    screen.font = BODY
    width = W - 22
    for line in text.split("\n"):
        line = line.rstrip("\r").replace("\t", "    ")
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append(("c", fit(line, width)))
        elif not s:
            if out and out[-1][1]:
                out.append(("t", ""))
        else:
            kind = "t"
            if s.startswith(">"):
                s = s.lstrip("> ").strip()
            if s.startswith("#"):
                kind = "h"
                s = s.lstrip("#").strip()
            s = clean_md(s)
            if s and not s.replace("-", "").replace("=", "").strip() == "":
                for part in wrap(s, width, 12):
                    out.append((kind, part))
        if len(out) >= README_LINES:
            break
    while out and not out[0][1]:
        out.pop(0)
    return out[:README_LINES]


def open_repo(r):
    v = push_view({"t": "repo", "r": r, "lines": None, "msg": "loading README...", "top": 0, "note": None})

    def got(path, code, err):
        if path:
            with open(path, "rb") as f:
                raw = f.read(README_BYTES)
            truncated = len(raw) >= README_BYTES
            text = bytes(b if 32 <= b < 127 or b in (9, 10, 13) else 32 for b in raw).decode()
            del raw
            lines = readme_lines(text)
            if truncated:
                lines.append(("n", "... README shortened - read the rest on github.com"))
            v["lines"] = lines
            v["msg"] = None
        elif code == 404:
            v["msg"] = "This repository has no README."
        else:
            v["msg"] = err_text(code, err)

    query.ask(API + "/repos/" + r.get("f", "") + "/readme", got,
              accept="application/vnd.github.raw", label="loading README", owner=v)


def visibility_action(v):
    r = v["r"]
    full = r.get("f", "")
    reason = write_block()
    if not reason and full.split("/")[0].lower() != HANDLE.lower():
        reason = "Only repositories owned by @" + HANDLE + " can be changed here."
    if reason:
        v["note"] = reason
        return
    make_private = not r.get("p")
    word = "private" if make_private else "public"
    if make_private:
        warn = "Only you and collaborators will see it. Stars and watchers from others may be lost."
    else:
        warn = "Everyone on the internet will be able to see its code and history."

    def go():
        code, err = write_request("PATCH", "/repos/" + full, json.dumps({"private": make_private}))
        if code == 200:
            r["p"] = make_private
            for other in data.get("repos") or []:
                if other.get("f") == full:
                    other["p"] = make_private
            rebuild()
            save_cache()
            return GREEN, full + " is now " + word + "."
        if code in (403, 404):
            return RED, "Not allowed. The token needs the 'repo' scope and admin rights on this repository."
        if code == 422:
            return RED, "GitHub refused the change (for example, forks of public repos can't be private)."
        return RED, write_error(code, err)

    confirm("Make it " + word + "?", (full, warn), go)


# ---- users


def check_follow(v):
    login = v["login"]
    if not net.verified() or login.lower() == HANDLE.lower():
        return

    def got(path, code, err):
        if code == 404:
            v["follow"] = False
        elif path:
            v["follow"] = True
        else:
            v["note"] = "Couldn't check follow status: " + err_text(code, err)

    query.ask(API + "/user/following/" + login, got, label="checking follow", owner=v)


def open_user(login):
    v = push_view({"t": "user", "login": login, "p": None, "msg": "loading profile...", "follow": None, "note": None})

    def got(path, code, err):
        if not path:
            v["msg"] = ("No GitHub user called @" + login) if code == 404 else err_text(code, err)
            return
        raw = load_json(path)
        p = parse_profile(raw)
        p["bio"] = short(raw.get("bio") or "", 160)
        place = [short(raw.get(k) or "", 30) for k in ("company", "location") if raw.get(k)]
        p["where"] = "  ".join(place)
        del raw
        v["p"] = p
        v["msg"] = None
        check_follow(v)

    query.ask(API + "/users/" + login, got, label="loading @" + login, owner=v)


def follow_action(v):
    login = v["login"]
    reason = write_block()
    if not reason and login.lower() == HANDLE.lower():
        reason = "That's you!"
    if reason:
        v["note"] = reason
        return
    if v["follow"] is None:
        v["note"] = "Checking follow status first..."
        check_follow(v)
        return
    following = v["follow"]

    def go():
        code, err = write_request("DELETE" if following else "PUT", "/user/following/" + login)
        if code == 204:
            v["follow"] = not following
            net.forced.add("profile")
            return GREEN, ("Unfollowed @" if following else "Now following @") + login + "."
        if code in (403, 404):
            return RED, "Not allowed. The token needs the 'user:follow' scope."
        return RED, write_error(code, err)

    confirm(("Unfollow @" if following else "Follow @") + login + "?",
            ("Signed in as @" + net.token_owner() + ".",), go)


# ---- lists, search and keyboard


def open_list(title, url, kind):
    v = push_view({"t": "list", "title": title, "count": "", "rows": [("note", "loading...")], "top": 0})

    def got(path, code, err):
        screen.font = BODY
        if not path:
            v["rows"] = [("note", line) for line in wrap(err_text(code, err), W - 30, 3)]
            return
        raw = load_json(path)
        tw = W - 20
        if kind == "repos":
            items = [repo_row(r, tw) for r in parse_repos(raw)]
        elif kind == "users":
            items = [user_row(u, tw) for u in parse_users(raw)]
        else:
            items = [code_row(c, tw) for c in parse_code(raw)]
        total = raw.get("total_count") if isinstance(raw, dict) else None
        del raw
        v["count"] = thousands(total) if total is not None else str(len(items))
        v["rows"] = items or [("note", "no results")]
        v["top"] = 0

    query.ask(url, got, label="loading " + kind, owner=v)


KB_ROWS = ("1234567890", "qwertyuiop", "asdfghjkl:", "zxcvbnm-_.")
KB_SPECIAL = (("space", 4), ("del", 2), ("search", 4))
KB_TOP = 96
KB_H = 22
KB_GAP = 3
KB_UNIT = 28
SEARCH_LABELS = {"repos": "Search repositories", "users": "Search users", "code": "Search code"}


def open_find(kind):
    if kind == "followers":
        open_list("Your followers", API + "/users/" + HANDLE + "/followers?per_page=30", "users")
    elif kind == "following":
        open_list("You follow", API + "/users/" + HANDLE + "/following?per_page=30", "users")
    elif kind == "code" and (not TOKEN or net.token_bad):
        push_view({"t": "msg", "title": "Code search needs a token", "lines": (
            "GitHub only allows code search when signed in.",
            "Add GITHUB_TOKEN to secrets.py (see the Inbox page), then try again.",
            "Repository and user search work without a token.",
        )})
    else:
        push_view({"t": "kbd", "kind": kind, "value": "", "row": 1, "col": 0, "note": None})


def run_search(v):
    q = v["value"].strip()
    if not q:
        v["note"] = "Type something to search for."
        return
    kind = v["kind"]
    if kind == "repos":
        url = API + "/search/repositories?q=" + quote(q) + "&per_page=15"
    elif kind == "users":
        url = API + "/search/users?q=" + quote(q) + "&per_page=20"
    else:
        if "repo:" not in q and "user:" not in q and "org:" not in q:
            q += " user:" + HANDLE   # default to your own code
        url = API + "/search/code?q=" + quote(q) + "&per_page=15"
    views.pop()
    open_list(short(q, 40), url, kind)


def kb_keys(row):
    if row < len(KB_ROWS):
        return [(c, 1) for c in KB_ROWS[row]]
    return list(KB_SPECIAL)


def kb_layout(row):
    keys = kb_keys(row)
    widths = [u * KB_UNIT + (u - 1) * KB_GAP for _, u in keys]
    total = sum(widths) + KB_GAP * (len(keys) - 1)
    x = (W - total) // 2
    out = []
    for (label, _), w in zip(keys, widths):
        out.append((label, x, w))
        x += w + KB_GAP
    return out


def kbd_input(v):
    row = v["row"]
    keys = kb_layout(row)
    if badge.pressed(BUTTON_RIGHT):
        v["col"] = (v["col"] + 1) % len(keys)
    if badge.pressed(BUTTON_LEFT):
        v["col"] = (v["col"] - 1) % len(keys)
    if badge.pressed(BUTTON_DOWN) or badge.pressed(BUTTON_UP):
        _, x, w = keys[min(v["col"], len(keys) - 1)]
        centre = x + w // 2
        row = (row + (1 if badge.pressed(BUTTON_DOWN) else -1)) % (len(KB_ROWS) + 1)
        nxt = kb_layout(row)
        v["row"] = row
        v["col"] = min(range(len(nxt)), key=lambda i: abs(nxt[i][1] + nxt[i][2] // 2 - centre))
    if badge.pressed(BUTTON_BACK):
        if v["value"]:
            v["value"] = v["value"][:-1]
        else:
            pop_view()
            return
    if badge.pressed(BUTTON_SELECT):
        label = kb_layout(v["row"])[v["col"]][0]
        v["note"] = None
        if label == "search":
            run_search(v)
        elif label == "del":
            v["value"] = v["value"][:-1]
        elif len(v["value"]) < 60:
            v["value"] += " " if label == "space" else label


def open_target(target):
    kind, value = target
    if kind == "repo":
        open_repo(value)
    elif kind == "user":
        open_user(value)
    elif kind == "find":
        open_find(value)


def handle_view_input(v):
    t = v["t"]
    if t == "kbd":
        kbd_input(v)
        return
    if t == "confirm":
        if v["state"] == "ask":
            if badge.pressed(BUTTON_SELECT):
                v["state"] = "busy"
                v["drawn"] = False
            elif badge.pressed(BUTTON_BACK):
                pop_view()
        elif v["state"] == "done" and (badge.pressed(BUTTON_SELECT) or badge.pressed(BUTTON_BACK)):
            pop_view()
        return
    if badge.pressed(BUTTON_BACK):
        pop_view()
        return
    if t == "list":
        n = len(v["rows"])
        if badge.pressed(BUTTON_DOWN):
            v["top"] = min(v["top"] + 1, max(0, n - 1))
        if badge.pressed(BUTTON_UP):
            v["top"] = max(0, v["top"] - 1)
        if badge.pressed(BUTTON_SELECT) and v["top"] < n:
            row = v["rows"][v["top"]]
            if len(row) > 5:
                open_target(row[5])
    elif t == "repo":
        last = max(0, len(v["lines"] or ()) - 4)
        step = 0
        if badge.pressed(BUTTON_DOWN):
            step = 1
        if badge.pressed(BUTTON_UP):
            step = -1
        if badge.pressed(BUTTON_RIGHT):
            step = 10
        if badge.pressed(BUTTON_LEFT):
            step = -10
        v["top"] = max(0, min(last, v["top"] + step))
        if badge.pressed(BUTTON_SELECT):
            visibility_action(v)
    elif t == "user":
        if badge.pressed(BUTTON_SELECT):
            follow_action(v)
        if badge.pressed(BUTTON_RIGHT) and v["p"]:
            login = v["login"]
            open_list("@" + login + " repos", API + "/users/" + login + "/repos?sort=updated&per_page=20", "repos")


def run_pending_write():
    if not views:
        return
    v = views[-1]
    if v["t"] == "confirm" and v["state"] == "busy" and v["drawn"]:
        try:
            v["result"] = v["go"]()
        except Exception as e:  # noqa: BLE001
            v["result"] = (RED, "Failed: " + str(e))
        v["state"] = "done"


def view_hint():
    v = views[-1]
    t = v["t"]
    if t == "kbd":
        return "SELECT type  BACK delete"
    if t == "confirm":
        return "SELECT confirm  BACK cancel" if v["state"] == "ask" else ("" if v["state"] == "busy" else "BACK close")
    if t == "list":
        return "SELECT open  BACK close"
    if t == "repo":
        return "SELECT visibility  BACK close"
    if t == "user":
        return "SELECT follow  RIGHT repos"
    return "BACK close"


def draw_header(title, right=""):
    screen.pen = PANEL
    screen.rectangle(0, 0, W, TOP - 1)
    screen.pen = BORDER
    screen.rectangle(0, TOP - 1, W, 1)
    screen.font = BODY
    screen.pen = MUTED
    screen.text("<", 6, 5)
    if right:
        screen.text(right, W - 8 - measure(right), 5)
    screen.pen = TEXT
    screen.text(fit(title, W - 40 - measure(right)), 18, 5)


def draw_lines(text, x, y, width, colour, max_lines=3):
    screen.pen = colour
    for line in wrap(text, width, max_lines):
        screen.text(line, x, y)
        y += 13
    return y


def draw_repo(v):
    r = v["r"]
    draw_header("Repository")
    y = TOP + 4
    screen.font = HEAD
    screen.pen = TEXT
    screen.text(fit(r.get("f", ""), W - 16), 8, y)
    y += 18
    screen.font = SMALL
    screen.pen = ORANGE if r.get("p") else GREEN
    meta = repo_meta(r) + ("  {} forks".format(thousands(r["k"])) if r.get("k") else "")
    screen.text(fit(meta, W - 16), 8, y)
    y += 13
    screen.font = BODY
    if r.get("d"):
        y = draw_lines(r["d"], 8, y, W - 16, MUTED, 2)
    if v["note"]:
        y = draw_lines(v["note"], 8, y, W - 16, ORANGE, 2)
    screen.pen = BORDER
    screen.rectangle(8, y + 2, W - 16, 1)
    y += 6
    if v["lines"] is None:
        draw_lines(v["msg"] or "", 8, y + 4, W - 16, MUTED)
        return
    bottom = H - FOOT
    screen.clip = rect(0, y, W, bottom - y)
    lines = v["lines"]
    i = v["top"]
    while i < len(lines) and y < bottom:
        kind, text = lines[i]
        screen.pen = BLUE if kind == "h" else (MUTED if kind in ("c", "n") else TEXT)
        screen.text(text, 12 if kind == "c" else 8, y)
        y += 13
        i += 1
    screen.clip = rect(0, 0, W, H)


def draw_user(v):
    draw_header("@" + v["login"])
    p = v["p"]
    y = TOP + 6
    if p is None:
        screen.font = BODY
        draw_lines(v["msg"] or "", 8, y + 4, W - 16, MUTED)
        return
    screen.font = BIG
    screen.pen = TEXT
    screen.text(fit(p.get("name") or p.get("login"), W - 16), 8, y)
    y += 23
    screen.font = BODY
    screen.pen = MUTED
    screen.text("@" + p.get("login", ""), 8, y)
    y += 15
    screen.pen = TEXT
    screen.text("{} followers  {} following  {} repos".format(
        thousands(p.get("followers")), thousands(p.get("following")), thousands(p.get("repos"))), 8, y)
    y += 15
    if p.get("where"):
        screen.pen = MUTED
        screen.text(fit(p["where"], W - 16), 8, y)
        y += 14
    if p.get("bio"):
        y = draw_lines(p["bio"], 8, y + 2, W - 16, TEXT, 3)
    y += 8
    login = v["login"]
    if login.lower() == HANDLE.lower():
        colour, text = MUTED, "This is you."
    elif write_block():
        colour, text = MUTED, write_block()
    elif v["follow"] is None:
        colour, text = MUTED, "checking follow status..."
    elif v["follow"]:
        colour, text = GREEN, "You follow @" + login + "."
    else:
        colour, text = MUTED, "You don't follow @" + login + " yet."
    y = draw_lines(text, 8, y, W - 16, colour, 2)
    if v["note"]:
        draw_lines(v["note"], 8, y + 2, W - 16, ORANGE, 2)


def draw_confirm(v):
    draw_header("Confirm")
    y = TOP + 16
    screen.font = HEAD
    screen.pen = TEXT
    screen.text(fit(v["title"], W - 16), 8, y)
    y += 24
    screen.font = BODY
    for line in v["lines"]:
        y = draw_lines(line, 8, y, W - 16, MUTED, 4) + 6
    y += 6
    if v["state"] == "ask":
        draw_lines("Press SELECT to confirm or BACK to cancel.", 8, y, W - 16, TEXT)
    elif v["state"] == "busy":
        draw_lines("Working... talking to GitHub", 8, y, W - 16, BLUE)
    else:
        colour, text = v["result"]
        draw_lines(text, 8, y, W - 16, colour, 4)


def draw_kbd(v):
    draw_header(SEARCH_LABELS.get(v["kind"], "Search"))
    y = TOP + 8
    screen.font = SMALL
    screen.pen = MUTED
    hint = "your code by default; add repo:owner/name to widen" if v["kind"] == "code" else "type a query, then choose search"
    screen.text(fit(v.get("note") or hint, W - 16), 8, y)
    y += 16
    screen.pen = PANEL
    screen.rectangle(8, y, W - 16, 28)
    screen.font = HEAD
    shown = v["value"]
    while shown and measure_head(shown) > W - 32:
        shown = shown[1:]
    screen.pen = TEXT
    screen.text(shown, 14, y + 5)
    if (badge.ticks // 500) % 2 == 0:
        screen.rectangle(16 + measure_head(shown), y + 6, 2, 16)
    screen.font = BODY
    for row in range(len(KB_ROWS) + 1):
        top = KB_TOP + row * (KB_H + KB_GAP)
        for col, (label, x, w) in enumerate(kb_layout(row)):
            selected = row == v["row"] and col == v["col"]
            screen.pen = BLUE if selected else PANEL
            screen.rectangle(x, top, w, KB_H)
            screen.pen = BG if selected else TEXT
            screen.text(label, x + (w - measure(label)) // 2, top + 4)


def draw_view(v):
    t = v["t"]
    if t == "repo":
        draw_repo(v)
    elif t == "user":
        draw_user(v)
    elif t == "confirm":
        draw_confirm(v)
    elif t == "kbd":
        draw_kbd(v)
    elif t == "list":
        draw_list(v["rows"], v["top"], True)
        draw_header(v["title"], v["count"])
    else:
        draw_header(v["title"])
        y = TOP + 12
        screen.font = BODY
        for line in v["lines"]:
            y = draw_lines(line, 8, y, W - 16, MUTED, 4) + 6


page_changed_at = 0


def handle_input():
    global page_changed_at
    if views:
        handle_view_input(views[-1])
        return
    page = data["page"]
    if badge.pressed(BUTTON_RIGHT):
        data["page"] = (page + 1) % NPAGES
    elif badge.pressed(BUTTON_LEFT):
        data["page"] = (page - 1) % NPAGES
    elif badge.pressed(BUTTON_BACK):
        data["page"] = 0
    if data["page"] != page:
        page_changed_at = badge.ticks
    page = data["page"]
    if badge.pressed(BUTTON_DOWN):
        scroll[page] = min(scroll[page] + 1, max(0, len(rows[page]) - 1))
    if badge.pressed(BUTTON_UP):
        scroll[page] = max(0, scroll[page] - 1)
    if badge.pressed(BUTTON_SELECT):
        if page in SELECTABLE:
            items = rows[page]
            if scroll[page] < len(items) and len(items[scroll[page]]) > 5:
                open_target(items[scroll[page]][5])
        else:
            net.refresh()


saved_page = data["page"]
rebuild()


def update():
    global saved_page
    screen.fill_rule = image.EVEN_ODD

    if MISSING:
        missing_details.show(MISSING, lambda: None)
        return

    if not HANDLE or not valid_handle(HANDLE):
        draw_message("Who are you on GitHub?", (
            "Set your GitHub username in the Settings app (or GITHUB_USERNAME in secrets.py).",
            "No account setup or token is needed for the dashboard.",
        ))
        return

    handle_input()
    run_pending_write()
    query.pump()
    net.pump(data["page"])

    # remember the page, but don't write flash on every key press
    if data["page"] != saved_page and badge.ticks - page_changed_at > 3000:
        saved_page = data["page"]
        save_cache()

    screen.pen = BG
    screen.clear()
    page = data["page"]
    if views:
        draw_view(views[-1])
        if views[-1]["t"] == "confirm" and views[-1]["state"] == "busy":
            views[-1]["drawn"] = True
    elif net.user_missing and page != 3:
        draw_message("User not found", (
            "GitHub has no user called @" + HANDLE + ".",
            "Check GITHUB_USERNAME in the Settings app.",
        ), RED)
    elif page == 0:
        draw_home()
    elif page == 3:
        draw_inbox()
    else:
        draw_rows(page)
    if not views:
        draw_tabs(page)
    draw_footer()


run(update)
