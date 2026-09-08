"""Global backend lane — worldwide backend/software roles for a learning-first feed.

Companion to ``kenya.py``. Where the Kenya lane is precision-tuned for roles a
junior can actually apply to, this lane casts the widest net: backend and
software-engineering roles from every remote board Scout knows, ALL seniority
levels kept on purpose (a senior JD is a study guide for what to learn next).

Reuses the same public board endpoints as the main scrapers but applies its own
backend filter instead of the global preferences prefilter, and tags every row
``be_<board>`` so the lane stays isolated from the owner's pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup
from rich.console import Console

from src.database import Job, managed_session
from src.scrapers.base import insert_if_new, parse_date
from src.scrapers.kenya import _ENTRY_MARKERS, _is_pollution, lane_hash

console = Console()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Strong signals a title is a backend / software-engineering role.
_BACKEND_STRONG = (
    "backend", "back-end", "back end", "server-side", "server side",
    "java", "spring", "kotlin", "scala", "clojure",
    "node", "node.js", "nodejs", "express",
    "python", "django", "flask", "fastapi",
    "golang", "go developer", "go engineer",
    "ruby", "rails", ".net", "c#", "asp.net",
    "php", "laravel", "symfony", "rust", "elixir",
    "microservice", "microservices", "distributed systems",
    "api engineer", "api developer", "platform engineer", "infrastructure engineer",
    "software engineer", "software developer", "software development engineer", "sde",
    "full stack", "full-stack", "fullstack",
)

# Context tokens that rescue a bare "developer"/"engineer" title via the body.
_BACKEND_CONTEXT = (
    "backend", "server-side", "rest api", "restful", "microservice", "spring",
    "django", "node", "sql", "postgres", "database", "java", "python", "golang",
    "api endpoint",
)

# Off-lane roles that would otherwise sneak past on shared vocabulary. This lane
# is backend-focused, so front-end, mobile, data-analysis, QA and non-eng go.
_WORLD_EXCLUDE = (
    "frontend", "front-end", "front end", "react developer", "angular developer",
    "vue developer", "ios developer", "android developer", "mobile developer",
    "flutter", "react native", "designer", "ux ", "ui/ux",
    "data analyst", "data scientist", "data entry", "bi analyst",
    "qa engineer", "test engineer", "tester", "sdet",
    "sales", "marketing", "recruiter", "account manager", "customer success",
    "wordpress", "seo ",
)


def _is_backend_role(title: str, description: str = "") -> bool:
    tl = title.lower()
    if _is_pollution(title, "") or any(x in tl for x in _WORLD_EXCLUDE):
        return False
    if any(x in tl for x in _BACKEND_STRONG):
        return True
    if any(w in tl for w in ("developer", "engineer", "programmer")) and description:
        return any(tok in description.lower() for tok in _BACKEND_CONTEXT)
    return False


def is_entry_level(title: str) -> bool:
    return any(m in title.lower() for m in _ENTRY_MARKERS)


def _date(value) -> datetime | None:
    """Coerce a board date to datetime. Some boards (Arbeitnow, Himalayas) send
    integer epoch seconds; parse_date only handles strings and would raise."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    return parse_date(str(value))


def _text(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)[:3000]


def _add(session, *, company, title, location, source, url, description, posted) -> int:
    """Insert one row if it passes the backend filter. Returns 1 if new, else 0."""
    title = (title or "").strip()
    company = (company or "Unknown").strip()
    if not title or not url:
        return 0
    if not _is_backend_role(title, description):
        return -1  # filtered
    location = location or "Remote"
    jid = lane_hash(company, title, location, url)
    row = Job(
        id=jid,
        title=title,
        company=company,
        location=location,
        source=source,
        url=url,
        jd_text=_text(description),
        posted_at=posted,
        status="scraped",
        scraped_at=datetime.now(UTC),
    )
    return 1 if insert_if_new(session, row) else 0


def _tally(session, source, items, mapper) -> tuple[int, int, int]:
    new = skipped = filtered = 0
    for item in items:
        try:
            fields = mapper(item)
        except Exception:
            continue
        r = _add(session, source=source, **fields)
        if r == 1:
            new += 1
        elif r == 0:
            skipped += 1
        else:
            filtered += 1
    return new, skipped, filtered


def _get_json(url, **params):
    resp = httpx.get(url, headers=_HEADERS, params=params or None, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


# --- per-board fetchers, each returning a flat list of raw items -----------

def _remoteok():
    data = _get_json("https://remoteok.com/api")
    return [i for i in data if isinstance(i, dict) and i.get("position")]


def _arbeitnow(pages=3):
    out = []
    for p in range(1, pages + 1):
        data = _get_json("https://www.arbeitnow.com/api/job-board-api", page=p)
        rows = data.get("data", [])
        out.extend(rows)
        if not data.get("links", {}).get("next"):
            break
    return out


def _jobicy():
    return _get_json("https://jobicy.com/api/v2/remote-jobs", count=50).get("jobs", [])


def _himalayas():
    return _get_json("https://himalayas.app/jobs/api", limit=100).get("jobs", [])


def _workingnomads():
    return _get_json("https://www.workingnomads.com/api/exposed_jobs/")


def _wwr():
    out = []
    for url in (
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ):
        resp = httpx.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")
        out.extend(soup.find_all("item"))
    return out


def _wwr_map(item):
    raw = item.find("title").text if item.find("title") else ""
    company, _, title = raw.partition(": ")
    if not title:
        company, title = "Unknown", raw
    return {
        "company": company,
        "title": title,
        "location": "Remote",
        "url": (item.find("link").text if item.find("link") else ""),
        "description": (item.find("description").text if item.find("description") else ""),
        "posted": _date(item.find("pubDate").text if item.find("pubDate") else None),
    }


_BOARDS = (
    ("be_remoteok", _remoteok, lambda i: {
        "company": i.get("company"), "title": i.get("position"),
        "location": i.get("location") or "Remote", "url": i.get("url"),
        "description": i.get("description"), "posted": _date(i.get("date")),
    }),
    ("be_arbeitnow", _arbeitnow, lambda i: {
        "company": i.get("company_name"), "title": i.get("title"),
        "location": i.get("location") or "Remote", "url": i.get("url"),
        "description": i.get("description"), "posted": _date(i.get("created_at")),
    }),
    ("be_jobicy", _jobicy, lambda i: {
        "company": i.get("companyName"), "title": i.get("jobTitle"),
        "location": i.get("jobGeo") or "Remote", "url": i.get("url"),
        "description": i.get("jobDescription") or i.get("jobExcerpt"),
        "posted": _date(i.get("pubDate")),
    }),
    ("be_himalayas", _himalayas, lambda i: {
        "company": i.get("companyName"), "title": i.get("title"),
        "location": (i.get("locationRestrictions") or ["Remote"])[0]
        if isinstance(i.get("locationRestrictions"), list) else "Remote",
        "url": i.get("applicationLink"), "description": i.get("description"),
        "posted": _date(i.get("pubDate") or i.get("publishedDate")),
    }),
    ("be_workingnomads", _workingnomads, lambda i: {
        "company": i.get("company_name"), "title": i.get("title"),
        "location": i.get("location") or "Remote", "url": i.get("url"),
        "description": i.get("description"), "posted": _date(i.get("pub_date")),
    }),
    ("be_wwr", _wwr, _wwr_map),
)


def scrape_backend_world() -> tuple[int, int, int]:
    """Scrape every global board for backend roles. Returns (new, skipped, filtered)."""
    new = skipped = filtered = 0
    with managed_session() as session:
        for source, fetch, mapper in _BOARDS:
            try:
                items = fetch()
            except Exception as e:  # a dead board must not sink the lane
                console.print(f"  [red]{source} failed: {e}[/red]")
                continue
            n, s, f = _tally(session, source, items, mapper)
            new += n
            skipped += s
            filtered += f
    return new, skipped, filtered
