"""Kenya entry-level backend lane — MyJobMag (RSS + curated title pages).

A self-contained sourcing lane for entry-level Java / Spring / backend roles in
Kenya. Deliberately independent of the global ``preferences.yaml`` prefilter,
which is tuned for a different profile: this lane carries its own filter so it
can run alongside the main pipeline without repointing anything.

Jobs are tagged with source ``"myjobmag_ke"`` so they are easy to list
(``scout jobs --source myjobmag_ke``) and stay out of the main apply queue
(the apply bots only touch Greenhouse/Lever/Workday).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup
from rich.console import Console

from src.database import Job, managed_session
from src.scrapers.base import insert_if_new, job_hash, parse_date

console = Console()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

def lane_hash(company: str, title: str, location: str, url: str = "") -> str:
    """Namespaced job id for the personal backend lane.

    Prefixing keeps lane rows from colliding with the owner's own scraped jobs
    (some boards, e.g. Arbeitnow, are shared): a shared id would merge into the
    owner's row and vanish from the lane. Same company+title+location still
    dedups WITHIN the lane, so a role on two boards is stored once.
    """
    return "lane_" + job_hash(company, title, location, url)


_RSS_URL = "https://www.myjobmag.co.ke/jobsxml.xml"

# Fuzu exposes a stable JSON feed at this endpoint. Its private filter params
# (category_ids[]/seniority) are undocumented and get ignored, so we page the
# latest feed and filter on the structured fields each job already carries
# (category + seniority_level), which is robust to their front-end changes.
_FUZU_API = "https://www.fuzu.com/api/v1/browse/jobs/search"
_FUZU_COUNTRY_KENYA = 1
_FUZU_MAX_PAGES = 15
_FUZU_IT_CATEGORY = "information technology"  # substring of the IT/software category name

# Curated MyJobMag title-listing pages. These are noisy (the board matches
# loosely), so the lane filter below does the real work.
_TITLE_PAGES = (
    "https://www.myjobmag.co.ke/jobs-by-title/junior-java-developer",
    "https://www.myjobmag.co.ke/jobs-by-title/software-developer-intern",
    "https://www.myjobmag.co.ke/jobs-by-title/graduate-trainee-program",
    "https://www.myjobmag.co.ke/jobs-by-title/software-engineer",
    "https://www.myjobmag.co.ke/jobs-by-title/fullstack-software-developer-java-springboot",
)

# Strong signals that a title is a software-engineering role. Plain "developer"
# is intentionally NOT here — it drags in "Business Developer" / "Java House" —
# it only counts when paired with a tech qualifier (see _looks_like_dev_role).
_STRONG_DEV = (
    "java", "spring", "backend", "back end", "back-end",
    "software engineer", "software developer", "software development",
    "web developer", "programmer", "full stack", "fullstack", "full-stack",
    "python developer", "node developer", ".net developer", "golang", "devops",
    "api developer",
)

# Tech tokens used to rescue a bare "developer" title when a description is
# available (RSS lane only).
_TECH_CONTEXT = (
    "spring", "spring boot", "java", "rest api", "restful", "microservice",
    "postgres", "postgresql", "mysql", "sql", "hibernate", "docker", "git",
    "backend", "api", "software",
)

# Explicit entry markers — a title that says it is junior, whatever the tag.
_ENTRY_MARKERS = ("intern", "graduate", "junior", "trainee", "entry", "attach")

# Explicit seniority markers — exclude, this lane is for entry level.
_SENIOR = (
    "senior", "snr", " sr ", "sr.", "lead ", " lead", "principal", "staff engineer",
    "head of", "manager", "architect", "director", "vp ", "chief",
    "team lead", "tech lead", "5+ years", "6+ years", "7+ years", "8+ years",
)

# Obvious non-tech pollution that shares vocabulary with the lane, plus
# front-end-only roles (this lane is backend; "fullstack" is kept since it
# includes backend work).
_POLLUTION = (
    "java house", "barista", "cook", "waiter", "cashier", "restaurant",
    "business developer", "fundraising", "relationship", "sales",
    "real estate", "learning and development", "learning & development",
    "frontend", "front-end", "front end", "ui/ux", "ui designer",
    # Fuzu's IT category name contains "data", which drags in clerical
    # data-entry roles that are not software engineering.
    "data entry", "data capture", "data clerk", "data officer",
)


def _looks_senior(title: str) -> bool:
    t = f" {title.lower()} "
    return any(s in t for s in _SENIOR)


def _is_pollution(title: str, company: str) -> bool:
    blob = f"{title.lower()} {company.lower()}"
    return any(p in blob for p in _POLLUTION)


def _looks_like_dev_role(title: str, description: str = "") -> bool:
    """True if this is a software-engineering role, precision over recall."""
    title_l = title.lower()
    if any(s in title_l for s in _STRONG_DEV):
        return True
    # Rescue a bare "developer"/"programmer" title only with tech context.
    if ("developer" in title_l or "programmer" in title_l) and description:
        desc_l = description.lower()
        return any(tok in desc_l for tok in _TECH_CONTEXT)
    return False


def _split_title_company(raw: str) -> tuple[str, str]:
    """MyJobMag titles read '<Role> at <Company>'. Split on the last ' at '."""
    raw = re.sub(r"\s+", " ", raw).strip()
    m = re.search(r"^(.*)\bat\b\s+(.+)$", raw)
    if m:
        return m.group(1).strip(" -–"), m.group(2).strip()
    return raw, "Unknown"


def _passes_lane(title: str, company: str, description: str = "") -> bool:
    if _is_pollution(title, company):
        return False
    if _looks_senior(title):
        return False
    return _looks_like_dev_role(title, description)


def _fetch(url: str) -> str | None:
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        console.print(f"  [red]fetch failed {url}: {e}[/red]")
        return None


def _scrape_rss(session) -> tuple[int, int, int]:
    """Latest jobs feed — fresh, stable XML. Descriptions available here."""
    new = skipped = filtered = 0
    body = _fetch(_RSS_URL)
    if not body:
        return new, skipped, filtered

    soup = BeautifulSoup(body, "xml")
    for item in soup.find_all("item"):
        raw_title = (item.find("title").text if item.find("title") else "").strip()
        link = (item.find("link").text if item.find("link") else "").strip()
        desc = (item.find("description").text if item.find("description") else "").strip()
        pub = item.find("pubDate").text if item.find("pubDate") else None
        if not raw_title or not link:
            continue

        title, company = _split_title_company(raw_title)
        if not _passes_lane(title, company, desc):
            filtered += 1
            continue

        jid = lane_hash(company, title, "Kenya", link)
        job = Job(
            id=jid,
            title=title,
            company=company,
            location="Kenya",
            source="myjobmag_ke",
            url=link,
            jd_text=desc,
            posted_at=parse_date(pub),
            status="scraped",
            scraped_at=datetime.now(UTC),
        )
        if insert_if_new(session, job):
            new += 1
        else:
            skipped += 1
    return new, skipped, filtered


def _scrape_title_page(session, url: str) -> tuple[int, int, int]:
    """Curated listing page — title + company only, no description."""
    new = skipped = filtered = 0
    body = _fetch(url)
    if not body:
        return new, skipped, filtered

    soup = BeautifulSoup(body, "lxml")
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/job/" not in href:
            continue
        raw_title = a.get_text(strip=True)
        if not raw_title or len(raw_title) < 12 or raw_title in seen:
            continue
        seen.add(raw_title)

        full_url = href if href.startswith("http") else f"https://www.myjobmag.co.ke{href}"
        title, company = _split_title_company(raw_title)
        if not _passes_lane(title, company):
            filtered += 1
            continue

        jid = lane_hash(company, title, "Kenya", full_url)
        job = Job(
            id=jid,
            title=title,
            company=company,
            location="Kenya",
            source="myjobmag_ke",
            url=full_url,
            jd_text="",
            status="scraped",
            scraped_at=datetime.now(UTC),
        )
        if insert_if_new(session, job):
            new += 1
        else:
            skipped += 1
    return new, skipped, filtered


def scrape_myjobmag_ke() -> tuple[int, int, int]:
    """Scrape MyJobMag's Kenya entry-level backend lane. Returns (new, skipped, filtered)."""
    new = skipped = filtered = 0
    with managed_session() as session:
        for fn in (lambda: _scrape_rss(session), *[
            (lambda u=u: _scrape_title_page(session, u)) for u in _TITLE_PAGES
        ]):
            n, s, f = fn()
            new += n
            skipped += s
            filtered += f
    return new, skipped, filtered


def _fuzu_seniority_key(job: dict) -> str | None:
    sl = job.get("seniority_level")
    if isinstance(sl, dict):
        return sl.get("key")
    return None


def _fuzu_category_name(job: dict) -> str:
    cat = job.get("category")
    if isinstance(cat, dict):
        return cat.get("name", "")
    return cat or ""


def _fuzu_passes(job: dict) -> bool:
    """Fuzu lane gate: IT/software category or a dev title, entry-friendly."""
    title = job.get("title", "") or ""
    company = job.get("company_name", "") or ""
    description = job.get("description", "") or ""
    if _is_pollution(title, company):
        return False
    # Seniority: Fuzu tags every job, so keep entry-level only, unless the
    # title itself explicitly says junior/intern/graduate.
    title_l = title.lower()
    entry_title = any(m in title_l for m in _ENTRY_MARKERS)
    if not entry_title:
        if _looks_senior(title) or _fuzu_seniority_key(job) in ("senior", "middle"):
            return False
    # Relevance: trust Fuzu's own IT category, else fall back to the dev filter.
    is_it = _FUZU_IT_CATEGORY in _fuzu_category_name(job).lower()
    return is_it or _looks_like_dev_role(title, description)


def scrape_fuzu_ke() -> tuple[int, int, int]:
    """Scrape Fuzu's Kenya feed, filtering to entry-level software roles."""
    new = skipped = filtered = 0
    headers = {**_HEADERS, "Accept": "application/json"}
    with managed_session() as session:
        for page in range(1, _FUZU_MAX_PAGES + 1):
            try:
                resp = httpx.get(
                    _FUZU_API,
                    headers=headers,
                    params={"country_id": _FUZU_COUNTRY_KENYA, "page": page},
                    timeout=30,
                )
                resp.raise_for_status()
                jobs = resp.json().get("jobs", [])
            except (httpx.HTTPError, ValueError) as e:
                console.print(f"  [red]fuzu page {page} failed: {e}[/red]")
                break
            if not jobs:
                break

            for job in jobs:
                if not _fuzu_passes(job):
                    filtered += 1
                    continue
                title = job.get("title", "").strip()
                company = (job.get("company_name") or "Unknown").strip()
                path = job.get("path") or ""
                url = f"https://www.fuzu.com{path}" if path.startswith("/") else path
                desc_html = job.get("description") or ""
                desc = BeautifulSoup(desc_html, "lxml").get_text(" ", strip=True)[:2000]
                location = job.get("location") or "Kenya"

                jid = lane_hash(company, title, location, url)
                row = Job(
                    id=jid,
                    title=title,
                    company=company,
                    location=location,
                    source="fuzu_ke",
                    url=url,
                    jd_text=desc,
                    status="scraped",
                    scraped_at=datetime.now(UTC),
                )
                if insert_if_new(session, row):
                    new += 1
                else:
                    skipped += 1
    return new, skipped, filtered


def scrape_kenya_lane() -> tuple[int, int, int]:
    """Run every Kenya-lane source (MyJobMag + Fuzu). Returns (new, skipped, filtered)."""
    totals = [0, 0, 0]
    for fn in (scrape_myjobmag_ke, scrape_fuzu_ke):
        try:
            for i, v in enumerate(fn()):
                totals[i] += v
        except Exception as e:  # one board failing must not sink the lane
            console.print(f"  [red]{fn.__name__} failed: {e}[/red]")
    return tuple(totals)
