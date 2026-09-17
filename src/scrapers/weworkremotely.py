"""We Work Remotely scraper — RSS feed, no key needed."""

from lxml import etree as ET
from datetime import UTC, datetime

import httpx
from rich.console import Console

from src.database import Job, managed_session
from src.preferences import load_preferences
from src.scrapers.base import insert_if_new, job_hash, parse_date
from src.scrapers.prefilter import prefilter_job

console = Console()

# Multiple category feeds to cast a wider net
RSS_FEEDS = [
    ("Programming", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("DevOps & SysAdmin", "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"),
]


def scrape_weworkremotely() -> tuple[int, int, int]:
    """Fetch jobs from We Work Remotely RSS feeds. Returns (new_count, skipped_count, filtered_count)."""
    prefs = load_preferences()
    new_count = 0
    skipped = 0
    filtered = 0

    with managed_session() as session:
        for category, feed_url in RSS_FEEDS:
            try:
                console.print(f"  [dim]Fetching WWR: {category}...[/dim]")
                resp = httpx.get(feed_url, timeout=30)
                resp.raise_for_status()

                root = ET.fromstring(resp.content)  # nosec B314 - RSS feed from known source
                if root is None:
                    continue
                items = root.findall(".//item")

                for item in items:
                    title_raw = item.findtext("title", "Unknown")
                    # WWR titles are formatted as "Company: Job Title"
                    if ": " in title_raw:
                        company, title = title_raw.split(": ", 1)
                    else:
                        company = "Unknown"
                        title = title_raw

                    region = item.findtext("region", "Remote")
                    if not region:
                        region = "Remote"
                    description = item.findtext("description", "")
                    url = item.findtext("link", "") or item.findtext("guid", "")

                    result = prefilter_job(title, company, region, description, prefs)
                    if not result.passed:
                        filtered += 1
                        continue

                    jid = job_hash(company, title, region, url)
                    job = Job(
                        id=jid,
                        title=title,
                        company=company,
                        location=region,
                        source="weworkremotely",
                        url=url,
                        jd_text=description,
                        posted_at=parse_date(item.findtext("pubDate")),
                        status="scraped",
                        scraped_at=datetime.now(UTC),
                    )

                    if insert_if_new(session, job):
                        new_count += 1
                    else:
                        skipped += 1

            except Exception as e:
                console.print(f"  [red]WWR error ({category}): {e}[/red]")

    return new_count, skipped, filtered
