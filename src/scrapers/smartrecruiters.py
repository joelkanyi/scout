"""SmartRecruiters scraper — public global job search API, no key needed.

SmartRecruiters hosts postings for thousands of companies and exposes a
public search endpoint that returns fresh, structured results with a direct
`applyUrl` and a `releasedDate`. We search per configured job title, keep
only recently posted roles (stale evergreen reposts are dropped), and store
the direct apply link.
"""

from datetime import UTC, datetime, timedelta

import httpx
from rich.console import Console

from src.database import Job, managed_session
from src.preferences import load_preferences
from src.scrapers.base import insert_if_new, job_hash, parse_date
from src.scrapers.prefilter import prefilter_job

console = Console()

SEARCH_URL = "https://jobs.smartrecruiters.com/sr-jobs/search"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Only keep postings released within this window; older ones are evergreen
# reposts whose apply links are usually dead.
_MAX_AGE_DAYS = 120
# Pages of 100 to pull per keyword.
_PAGES_PER_KEYWORD = 5
# Cap keywords per run so the scrape stays fast.
_MAX_KEYWORDS = 6

# Generic role words to strip so multi-word titles collapse to the broad,
# high-recall keyword the API indexes on ("android engineer" -> "android").
_ROLE_NOISE = frozenset({
    "developer", "engineer", "senior", "junior", "mid", "lead", "staff",
    "principal", "sr", "jr", "specialist", "consultant",
})


def _broad_keywords(job_titles: list[str]) -> list[str]:
    """Collapse configured titles to unique broad keywords, preserving order.

    Single-word keywords match far more of the SmartRecruiters index than
    full phrases, so "android developer"/"android engineer" both become
    "android".
    """
    seen: list[str] = []
    for title in job_titles:
        for word in title.lower().split():
            if word in _ROLE_NOISE or len(word) < 2:
                continue
            if word not in seen:
                seen.append(word)
    return seen

# "mobile" is a homograph on SmartRecruiters: it matches security "mobile
# patrol" officers, "mobile seed plant operator", field-sales, etc. Rather
# than blocklist every non-tech role, keep a title only if it carries a real
# software signal: a platform/language token, or "mobile" paired with a
# development word (across the common posting languages).
_DEV_TOKENS = (
    "android", "kotlin", "flutter", " ios", "ios ", "swift", "react",
    ".net", "développeur", "desarrollador", "entwickler", "sviluppatore",
)
_MOBILE_DEV_WORDS = ("developer", "engineer", "software", "programmer", "développeur")


def _is_software_role(title: str) -> bool:
    low = f" {title.lower()} "
    if any(tok in low for tok in _DEV_TOKENS):
        return True
    if "mobile" in low and any(w in low for w in _MOBILE_DEV_WORDS):
        return True
    return False


def _location_text(item: dict) -> str:
    """Build a human-readable location, tagging remote/hybrid so the
    downstream location prefilter and scorer can see it.

    Prefer the API's `shortLocation` ("Berlin, Germany") over the raw
    location object, which only carries an ISO country code ("DE") that the
    location prefilter cannot match against full country names.
    """
    loc = item.get("location") or {}
    base = (item.get("shortLocation") or "").strip()
    if not base and isinstance(loc, dict):
        city = (loc.get("city") or "").strip()
        country = (loc.get("country") or "").upper()
        base = f"{city}, {country}".strip(", ") if city or country else ""
    if isinstance(loc, dict):
        if loc.get("remote") and "remote" not in base.lower():
            base = f"{base} (remote)".strip()
        elif loc.get("hybrid") and "hybrid" not in base.lower():
            base = f"{base} (hybrid)".strip()
    return base or "Unknown"


def scrape_smartrecruiters() -> tuple[int, int, int]:
    """Search SmartRecruiters per configured job title.

    Returns (new_count, skipped_count, filtered_count).
    """
    prefs = load_preferences()
    keywords = _broad_keywords(prefs.job_titles or [])[:_MAX_KEYWORDS]
    if not keywords:
        keywords = ["android"]

    cutoff = datetime.now(UTC) - timedelta(days=_MAX_AGE_DAYS)
    new_count = 0
    skipped = 0
    filtered = 0

    with managed_session() as session:
        for keyword in keywords:
            for page in range(_PAGES_PER_KEYWORD):
                offset = page * 100
                try:
                    resp = httpx.get(
                        SEARCH_URL,
                        params={"limit": 100, "offset": offset, "keyword": keyword},
                        headers=_HEADERS,
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, ValueError) as e:
                    console.print(f"  [dim]'{keyword}' stopped at offset {offset}: {e}[/dim]")
                    break

                content = data.get("content", []) if isinstance(data, dict) else []
                if not content:
                    break

                for item in content:
                    posted = parse_date(item.get("releasedDate"))
                    if posted and posted < cutoff:
                        filtered += 1
                        continue

                    title = item.get("name", "Unknown")
                    if not _is_software_role(title):
                        filtered += 1
                        continue

                    company = (item.get("company") or {}).get("name", "Unknown")
                    location = _location_text(item)
                    url = item.get("applyUrl", "")

                    result = prefilter_job(title, company, location, "", prefs)
                    if not result.passed:
                        filtered += 1
                        continue

                    jid = job_hash(company, title, location, url)
                    job = Job(
                        id=jid,
                        title=title,
                        company=company,
                        location=location,
                        source="smartrecruiters",
                        url=url,
                        jd_text="",
                        posted_at=posted,
                        status="scraped",
                        scraped_at=datetime.now(UTC),
                    )

                    if insert_if_new(session, job):
                        new_count += 1
                    else:
                        skipped += 1

                if len(content) < 100:
                    break

    return new_count, skipped, filtered
