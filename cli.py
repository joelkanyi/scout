"""Scout CLI — Typer entry point."""

import json
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.database import Job, get_session, init_db, managed_session
from src.preferences import load_preferences
from src.scrapers.arbeitnow import scrape_arbeitnow
from src.scrapers.greenhouse import scrape_greenhouse_boards
from src.scrapers.himalayas import scrape_himalayas
from src.scrapers.jobicy import scrape_jobicy
from src.scrapers.backend_world import scrape_backend_world
from src.scrapers.kenya import scrape_kenya_lane
from src.scrapers.landingjobs import scrape_landingjobs
from src.scrapers.remoteok import scrape_remoteok
from src.scrapers.remotive import scrape_remotive
from src.scrapers.smartrecruiters import scrape_smartrecruiters
from src.scrapers.themuse import scrape_themuse
from src.scrapers.weworkremotely import scrape_weworkremotely
from src.scrapers.workingnomads import scrape_workingnomads


# Words that suggest a tech/software role — used to decide whether to run tech-only scrapers
_TECH_TITLE_WORDS = frozenset({
    "software", "developer", "engineer", "android", "ios", "mobile",
    "frontend", "backend", "fullstack", "full-stack", "devops", "data",
    "ml", "ai", "cloud", "sre", "platform", "infrastructure", "web",
    "react", "python", "java", "kotlin", "flutter", "kmp", "golang",
    "rust", "node", "typescript", "javascript", "php", "ruby", "scala",
    "embedded", "firmware", "security", "cybersecurity", "devsecops",
    "qa", "sdet", "automation", "database", "dba",
})


def _has_tech_titles(prefs) -> bool:
    """Return True if any preferred job title suggests a tech role."""
    for title in prefs.job_titles:
        if any(word in _TECH_TITLE_WORDS for word in title.lower().split()):
            return True
    return False

app = typer.Typer(name="scout", help="Scout — Automated Job Application Platform")
console = Console()


@app.command()
def scrape() -> None:
    """Run all scrapers and store new jobs in the database."""
    init_db()
    prefs = load_preferences()

    console.print(Panel("[bold cyan]Scout — Scraping Jobs[/bold cyan]", expand=False))
    console.print(f"  Preferences loaded: {', '.join(prefs.job_titles)}")
    console.print()

    total_new = 0
    total_skipped = 0
    total_filtered = 0

    # JobSpy requires special import (optional heavy dependency)
    console.print("[bold]JobSpy (LinkedIn, Indeed)[/bold]")
    try:
        from src.scrapers.jobspy_scraper import scrape_jobspy
        new, skipped, filtered = scrape_jobspy()
        total_new += new
        total_skipped += skipped
        total_filtered += filtered
        console.print(f"  [green]+{new} new[/green]  [yellow]{filtered} filtered[/yellow]  [dim]{skipped} duplicates[/dim]")
    except Exception as e:
        console.print(f"  [red]JobSpy error: {e}[/red]")
    console.print()

    # General scrapers — work for any profession
    scrapers: list[tuple[str, callable]] = [
        ("Arbeitnow", scrape_arbeitnow),
        ("RemoteOK", scrape_remoteok),
        ("Remotive", scrape_remotive),
        ("We Work Remotely", scrape_weworkremotely),
        ("Himalayas", scrape_himalayas),
        ("Jobicy", scrape_jobicy),
        ("Greenhouse Boards", scrape_greenhouse_boards),
        ("SmartRecruiters", scrape_smartrecruiters),
        ("Landing.jobs", scrape_landingjobs),
        ("The Muse", scrape_themuse),
        ("Working Nomads", scrape_workingnomads),
    ]

    # Tech-specific scrapers — only run if user has tech-related job titles
    if _has_tech_titles(prefs):
        from src.scrapers.androidjobs import scrape_androidjobs
        from src.scrapers.echojobs import scrape_echojobs
        from src.scrapers.hn_hiring import scrape_hn_hiring

        scrapers.extend([
            ("AndroidJobs.io", scrape_androidjobs),
            ("EchoJobs", scrape_echojobs),
            ("HN Who is Hiring", scrape_hn_hiring),
        ])

    for name, scraper_fn in scrapers:
        console.print(f"[bold]{name}[/bold]")
        try:
            new, skipped, filtered = scraper_fn()
            total_new += new
            total_skipped += skipped
            total_filtered += filtered
            console.print(f"  [green]+{new} new[/green]  [yellow]{filtered} filtered[/yellow]  [dim]{skipped} duplicates[/dim]")
        except Exception as e:
            console.print(f"  [red]{name} error: {e}[/red]")
        console.print()

    console.print(
        Panel(
            f"[bold green]{total_new} new jobs saved[/bold green]  ·  "
            f"[yellow]{total_filtered} filtered out[/yellow]  ·  "
            f"[dim]{total_skipped} duplicates skipped[/dim]",
            title="Scrape Complete",
            expand=False,
        )
    )


@app.command()
def status() -> None:
    """Show today's stats from the database."""
    init_db()
    prefs = load_preferences()
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    with managed_session() as session:
        total_jobs = session.query(Job).count()
        today_jobs = session.query(Job).filter(Job.scraped_at >= today_start).count()
        sources = (
            session.query(Job.source)
            .filter(Job.scraped_at >= today_start)
            .distinct()
            .all()
        )
        source_names = [s[0] for s in sources]

        scored = session.query(Job).filter(Job.match_score.isnot(None)).count()
        unscored = session.query(Job).filter(Job.match_score.is_(None)).count()
        above_threshold = session.query(Job).filter(
            Job.match_score >= prefs.min_match_score
        ).count()
        manual_review = session.query(Job).filter(Job.status == "manual_review").count()

    table = Table(title="Scout Status", show_header=False, expand=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Total jobs in DB", str(total_jobs))
    table.add_row("Scraped today", str(today_jobs))
    table.add_row("Sources today", ", ".join(source_names) if source_names else "none")
    table.add_row("Scored", str(scored))
    table.add_row("Unscored", str(unscored))
    table.add_row(f"Above threshold (≥{prefs.min_match_score})", str(above_threshold))
    table.add_row("Flagged for manual review", str(manual_review))

    console.print()
    console.print(table)
    console.print()


@app.command()
def jobs(
    source: str = typer.Option(None, help="Filter by source (arbeitnow, remoteok, indeed, etc)"),
    status_filter: str = typer.Option(None, "--status", help="Filter by status (scraped, scored, apply_queue)"),
    limit: int = typer.Option(50, help="Max jobs to show"),
) -> None:
    """List all scraped jobs."""
    init_db()
    with managed_session() as session:
        query = session.query(Job)
        if source:
            query = query.filter(Job.source == source)
        if status_filter:
            query = query.filter(Job.status == status_filter)
        query = query.order_by(Job.scraped_at.desc()).limit(limit)

        results = query.all()

        if not results:
            console.print("[yellow]No jobs found.[/yellow]")
            return

        table = Table(title=f"Jobs ({len(results)} shown)", show_lines=False, expand=False)
        table.add_column("#", style="dim", width=4)
        table.add_column("Job ID", style="yellow", no_wrap=True)
        table.add_column("Company", style="cyan")
        table.add_column("Title")
        table.add_column("Score", width=6)
        table.add_column("Status", width=12)
        table.add_column("Scraped", style="dim", width=10)

        for i, j in enumerate(results, 1):
            score_str = f"{j.match_score:.0%}" if j.match_score is not None else "—"
            scraped_str = j.scraped_at.strftime("%Y-%m-%d") if j.scraped_at else "—"
            table.add_row(
                str(i), j.id[:12], j.company[:20], j.title[:40],
                score_str, j.status or "scraped",
                scraped_str,
            )

    console.print()
    console.print(table)
    console.print()


_LANE_KENYA = ("myjobmag_ke", "fuzu_ke")
_LANE_WORLD = ("be_remoteok", "be_arbeitnow", "be_jobicy", "be_himalayas", "be_workingnomads", "be_wwr")


@app.command(name="backend-jobs")
def backend_jobs(
    kenya_only: bool = typer.Option(False, "--kenya-only", help="Only Kenyan sources (skip the global lane)"),
    export: bool = typer.Option(True, help="Write a shareable shortlist to the Desktop"),
) -> None:
    """Backend jobs for Margaret — Kenya entry-level roles plus a worldwide backend feed to learn from.

    Self-contained: own backend filter, jobs tagged be_*/myjobmag_ke/fuzu_ke, never
    touches the main preferences or apply queue. Global lane keeps all seniority
    levels on purpose (senior JDs are a study guide for what to learn next).
    """
    init_db()
    console.print(Panel("[bold cyan]Scout — Backend Jobs for Margaret[/bold cyan]", expand=False))

    console.print("[bold]Kenya lane[/bold]")
    new, skipped, filtered = scrape_kenya_lane()
    console.print(f"  [green]+{new}[/green]  [yellow]{filtered} filtered[/yellow]  [dim]{skipped} dup[/dim]")

    sources = list(_LANE_KENYA)
    if not kenya_only:
        console.print("[bold]Global lane[/bold]")
        wn, ws, wf = scrape_backend_world()
        console.print(f"  [green]+{wn}[/green]  [yellow]{wf} filtered[/yellow]  [dim]{ws} dup[/dim]")
        sources += list(_LANE_WORLD)
    console.print()

    from src.scrapers.backend_world import is_entry_level

    with managed_session() as session:
        rows = (
            session.query(Job)
            .filter(Job.source.in_(sources))
            .order_by(Job.scraped_at.desc())
            .all()
        )
        results = [
            {
                "company": j.company or "",
                "title": j.title or "",
                "location": j.location or "",
                "url": j.url or "",
                "posted_at": j.posted_at,
                "kenya": j.source in _LANE_KENYA,
                "entry": is_entry_level(j.title or ""),
            }
            for j in rows
        ]

    entry = [r for r in results if r["entry"] or r["kenya"]]
    console.print(
        f"[cyan]{len(results)}[/cyan] backend roles in the lane  "
        f"([green]{len(entry)}[/green] entry-level / Kenya)"
    )

    if export:
        path = _export_backend_share(results)
        console.print(f"[green]Shortlist written:[/green] {path}")


@app.command(name="kenya-junior", hidden=True)
def kenya_junior(
    export: bool = typer.Option(True, help="Write a shareable shortlist to the Desktop"),
) -> None:
    """Alias for `backend-jobs --kenya-only` (kept for muscle memory)."""
    backend_jobs(kenya_only=True, export=export)


def _export_backend_share(results: list) -> Path:
    """Write a share-ready shortlist: apply-now (Kenya/entry) then learn-from (world)."""
    today = datetime.now(UTC).strftime("%d %b %Y")
    kenya = [r for r in results if r["kenya"]]
    world_entry = [r for r in results if not r["kenya"] and r["entry"]]
    world_all = [r for r in results if not r["kenya"] and not r["entry"]]

    def block(items, cap=None):
        out = []
        for r in (items[:cap] if cap else items):
            posted = r["posted_at"].strftime("%d %b") if r.get("posted_at") else ""
            loc = f" · {r['location']}" if r.get("location") else ""
            suffix = f" _(posted {posted})_" if posted else ""
            out.append(f"- **{r['title']}** at {r['company']}{loc}{suffix}\n  {r['url']}")
        return out or ["_None this run._"]

    lines = [
        "# Backend Developer Jobs for Margaret Njoki",
        "",
        f"Auto-generated by Scout on {today}. Two parts: roles to APPLY to now, and a worldwide",
        "backend feed to LEARN from (read the JDs to see what skills to pick up next).",
        "",
        "## Apply now — Kenya (entry-level)",
        "",
        "### Always-on internship / graduate track (her best fit as a student)",
        "- Safaricom Internship & Attachment (Tech): https://careers.safaricom.com/",
        "- Zeraki careers (Nairobi ed-tech): https://www.zeraki.app/jobs",
        "- MyJobMag Software Developer Intern: https://www.myjobmag.co.ke/jobs-by-title/software-developer-intern",
        "",
        "### Fresh Kenyan roles this run",
        *block(kenya),
        "",
        f"## Apply / stretch — entry-level backend, worldwide ({len(world_entry)}, mostly remote)",
        *block(world_entry),
        "",
        f"## Learn from — backend roles worldwide, all levels ({len(world_all)})",
        "_You may not get these yet. Read the JDs to map what to learn._",
        "",
        *block(world_all),
        "",
    ]

    path = Path.home() / "Desktop" / "Margaret - Backend Jobs (Scout).md"
    path.write_text("\n".join(lines))
    return path


@app.command()
def score(
    limit: int = typer.Option(0, help="Max jobs to score (0 = all)"),
) -> None:
    """AI-score all unscored jobs."""
    init_db()

    from src.ai.tailor import load_master_resume

    try:
        master = load_master_resume()
        resume_summary = master.get("summary", "")
    except FileNotFoundError:
        console.print("[red]Master resume not found at resume/master.json[/red]")
        console.print("Fill in your resume data before scoring.")
        raise typer.Exit(1)

    console.print(Panel("[bold cyan]Scout — AI Scoring[/bold cyan]", expand=False))

    from src.ai.scorer import score_all_unscored
    scored, above, errors, pre_filtered = score_all_unscored(resume_summary, limit=limit)

    console.print()
    console.print(
        Panel(
            f"[bold green]{scored} jobs scored[/bold green]  ·  "
            f"[cyan]{above} above threshold[/cyan]  ·  "
            f"[yellow]{pre_filtered} auto-skipped[/yellow]  ·  "
            f"[dim]{errors} errors[/dim]",
            title="Scoring Complete",
            expand=False,
        )
    )


@app.command("resume")
def resume_build(
    job_id: str = typer.Argument(help="Job ID (SHA256 hash) to build resume for"),
) -> None:
    """Build a tailored resume (PDF + DOCX) for a specific job."""
    init_db()

    session = get_session()
    # Support partial job IDs (prefix matching)
    job = session.get(Job, job_id)
    if not job:
        matches = session.query(Job).filter(Job.id.like(f"{job_id}%")).all()
        if len(matches) == 1:
            job = matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]Ambiguous ID '{job_id}' -- matches {len(matches)} jobs:[/yellow]")
            for m in matches[:5]:
                console.print(f"  {m.id[:16]}  {m.company} -- {m.title}")
            session.close()
            raise typer.Exit(1)
        else:
            console.print(f"[red]Job not found: {job_id}[/red]")
            session.close()
            raise typer.Exit(1)

    # Use the resolved full ID from here on
    job_id = job.id

    console.print(Panel(f"[bold cyan]Building resume for:[/bold cyan]\n{job.title} at {job.company}", expand=False))

    # Get ATS keywords
    ats_keywords = []
    if job.ats_keywords:
        try:
            ats_keywords = json.loads(job.ats_keywords)
        except json.JSONDecodeError:
            pass

    if not ats_keywords:
        console.print("[yellow]No ATS keywords found — run 'scout score' first.[/yellow]")
        console.print("[dim]Using empty keywords for tailoring...[/dim]")

    # Tailor resume
    research_notes = job.research_notes or ""
    if research_notes:
        console.print(f"  [dim]Including research notes ({len(research_notes)} chars)[/dim]")
    console.print("  Tailoring resume with Haiku...")
    from src.ai.tailor import tailor_resume
    tailored = tailor_resume(job.jd_text or "", ats_keywords, research_notes=research_notes)

    # ATS score (keyword-aware: uses Haiku-extracted ats_keywords as authoritative list)
    from src.resume.ats_scorer import score_resume, extract_resume_text
    tailored_text = extract_resume_text(tailored)
    score_breakdown = score_resume(tailored_text, job.jd_text or "", keywords=ats_keywords or None)
    score_val = score_breakdown["overall"]
    s = score_breakdown["stats"]
    console.print(
        f"  ATS overall: [cyan]{score_val:.0%}[/cyan]  "
        f"[dim](skills {score_breakdown['skills_match']:.0%}, "
        f"matched {s['matched_required_count']}/{s['required_count']} required, "
        f"{s['matched_preferred_count']}/{s['preferred_count']} preferred)[/dim]"
    )
    if score_breakdown["missing_required"]:
        console.print(f"  [yellow]Missing required:[/yellow] {', '.join(score_breakdown['missing_required'][:8])}")

    # Generate cover letter
    console.print("  Generating cover letter...")
    skills_for_cover = tailored.get("skills", [])
    if isinstance(skills_for_cover, dict):
        flat_skills = []
        for items in skills_for_cover.values():
            flat_skills.extend(items)
        skills_for_cover = flat_skills
    from src.ai.cover_letter import generate_cover_letter
    cover_letter = generate_cover_letter(
        title=job.title,
        company=job.company,
        jd_text=job.jd_text or "",
        summary=tailored.get("summary", ""),
        skills=skills_for_cover,
    )

    # Build PDF + DOCX
    console.print("  Building PDF + DOCX...")
    from src.resume.builder import build_resume, OUTPUT_DIR
    resume = build_resume(tailored, job_id, score_val)

    # Save cover letter
    cover_path = OUTPUT_DIR / job_id / "cover_letter.txt"
    cover_path.write_text(cover_letter)

    # Update job with resume_id
    job.resume_id = resume.id
    session.commit()
    session.close()

    console.print()
    console.print(
        Panel(
            f"[bold green]Resume built![/bold green]\n"
            f"  PDF:   {resume.pdf_path}\n"
            f"  DOCX:  {resume.docx_path}\n"
            f"  Cover: {cover_path}\n"
            f"  ATS:   {score_val:.0%}",
            title="Resume Ready",
            expand=False,
        )
    )


@app.command("apply")
def apply_jobs(
    dry_run: bool = typer.Option(True, "--dry-run/--run", help="Dry run fills forms without submitting"),
    job_id: str = typer.Option(None, help="Apply to a specific job ID"),
    limit: int = typer.Option(5, help="Max jobs to apply to in this run"),
) -> None:
    """Apply to jobs in the apply queue (Greenhouse, Lever, Workday only — no LinkedIn)."""
    init_db()

    from src.apply.base_bot import (
        check_daily_cap,
        check_duplicate,
        check_regulated_domain,
        create_browser_page,
        detect_portal,
        new_page_for_job,
        record_application,
    )
    from src.apply.apply_logger import log_action
    from src.apply.greenhouse import apply_greenhouse
    from src.apply.lever import apply_lever
    from src.apply.workday import apply_workday
    from src.resume.builder import OUTPUT_DIR

    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[red]LIVE[/red]"
    console.print(Panel(f"[bold cyan]Scout — Apply Bot[/bold cyan] ({mode})", expand=False))

    # Block auto-apply for regulated professions (medical, education)
    if not dry_run and check_regulated_domain():
        return

    if not dry_run and check_daily_cap():
        return

    with managed_session() as session:
        # Get jobs to apply to
        if job_id:
            job = session.get(Job, job_id)
            if not job:
                # Try partial ID match
                matches = session.query(Job).filter(Job.id.like(f"{job_id}%")).all()
                if len(matches) == 1:
                    job = matches[0]
                elif len(matches) > 1:
                    console.print(f"[yellow]Ambiguous ID '{job_id}' -- matches {len(matches)} jobs[/yellow]")
                    raise typer.Exit(1)
                else:
                    console.print(f"[red]Job not found: {job_id}[/red]")
                    raise typer.Exit(1)
            target_jobs = [job]
        else:
            target_jobs = (
                session.query(Job)
                .filter(Job.status.in_(["apply_queue", "manual_review"]))
                .filter(Job.dismissed_at.is_(None))
                .order_by(Job.match_score.desc())
                .limit(limit)
                .all()
            )

        if not target_jobs:
            console.print("[yellow]No jobs in apply queue. Run 'scout score' first.[/yellow]")
            return

        # Gather job data before closing session
        jobs_data = []
        for j in target_jobs:
            jobs_data.append({
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "url": j.url or "",
                "jd_text": j.jd_text or "",
                "resume_id": j.resume_id,
            })

    console.print(f"  Found {len(jobs_data)} jobs to process")
    console.print()

    # Launch browser — context is shared, but each job gets a FRESH page
    pw = browser = context = None
    applied = 0
    skipped = 0
    no_resume = 0

    try:
        pw, browser, context = create_browser_page()

        for jd in jobs_data:
            if not dry_run and check_daily_cap():
                break

            # Duplicate guard
            if check_duplicate(jd["id"]):
                console.print(f"  [dim]Skipping (already applied): {jd['company']} — {jd['title']}[/dim]")
                skipped += 1
                continue

            portal = detect_portal(jd["url"])
            if not portal:
                console.print(f"  [dim]Skipping (unknown portal): {jd['company']} — {jd['title']}[/dim]")
                log_action(jd["id"], "unknown", "skipped_unknown_portal", {"url": jd["url"]}, dry_run)
                skipped += 1
                continue

            # Require resume before applying
            resume_path = OUTPUT_DIR / jd["id"] / "resume.pdf"
            if not resume_path.exists():
                console.print(f"  [yellow]Skipping (no resume): {jd['company']} — {jd['title']}[/yellow]")
                console.print(f"    [dim]Run: scout resume {jd['id'][:12]}...[/dim]")
                no_resume += 1
                continue
            resume_str = str(resume_path.resolve())

            # Load cover letter if available
            cover_path = OUTPUT_DIR / jd["id"] / "cover_letter.txt"
            cover_letter = cover_path.read_text() if cover_path.exists() else None

            console.print(f"  [bold]{jd['company']}[/bold] — {jd['title']} [dim]({portal})[/dim]")

            # Create a FRESH page for each job (avoids state leaking between forms)
            page = new_page_for_job(context)

            try:
                success = False
                if portal == "greenhouse":
                    success = apply_greenhouse(page, jd["url"], jd["id"], resume_str, cover_letter, dry_run)
                elif portal == "lever":
                    success = apply_lever(page, jd["url"], jd["id"], resume_str, cover_letter, dry_run)
                elif portal == "workday":
                    success = apply_workday(page, jd["url"], jd["id"], resume_str, cover_letter, dry_run)

                if success:
                    applied += 1
                    record_application(jd["id"], portal, dry_run, submitted=True)

            except Exception as e:
                console.print(f"    [red]Error: {e}[/red]")
                log_action(jd["id"], portal, "error", {"error": str(e)}, dry_run)
            finally:
                page.close()
            console.print()

    finally:
        if context:
            context.close()
        if browser:
            browser.close()
        if pw:
            pw.stop()

    summary_parts = [
        f"[bold green]{applied} {'filled (dry run)' if dry_run else 'submitted'}[/bold green]",
        f"[dim]{skipped} skipped[/dim]",
    ]
    if no_resume:
        summary_parts.insert(1, f"[yellow]{no_resume} need resume[/yellow]")
    console.print(Panel("  ·  ".join(summary_parts), title="Apply Complete", expand=False))


@app.command()
def setup(
    reconfigure: bool = typer.Option(
        False, "--reconfigure", help="Re-run the AI provider step even if one is already set (e.g. to switch to Qwen)"
    ),
) -> None:
    """First-run setup wizard — gets you from zero to scraping in 3 minutes."""
    import subprocess
    import sys

    from src.paths import PROJECT_ROOT, CONFIG_DIR, RESUME_DIR

    console.print()
    console.print(Panel(
        "[bold cyan]Scout — Setup Wizard[/bold cyan]\n"
        "[dim]Let's get you set up. This takes about 3 minutes.[/dim]",
        expand=False,
    ))
    console.print()

    # ── Step 1: Python check ────────────────────────────────────────
    v = sys.version_info
    if v.major == 3 and v.minor >= 12:
        console.print(f"  [green]\u2713[/green] Python {v.major}.{v.minor}.{v.micro}")
    else:
        console.print(f"  [red]\u2717 Python {v.major}.{v.minor}.{v.micro} — need 3.12+[/red]")
        raise typer.Exit(1)

    # ── Step 2: AI Provider ────────────────────────────────────────
    from src.settings import load_settings
    from src.ai.ai_client import reset_provider

    env_path = PROJECT_ROOT / ".env"
    settings = load_settings()

    if settings.effective_provider and not reconfigure:
        provider_name = {
            "anthropic": "Anthropic",
            "gemini": "Google Gemini",
            "ollama": "Ollama",
            "openai_compatible": "OpenAI-compatible",
        }.get(settings.effective_provider, settings.effective_provider)
        console.print(f"  [green]\u2713[/green] AI provider: {provider_name}")
    else:
        console.print()
        console.print("  [bold]Step 1: AI Provider[/bold]")
        console.print("  Scout uses AI to score jobs and tailor your resume.")
        console.print()
        console.print("  Choose your AI provider:")
        console.print("    1) [cyan]Google Gemini[/cyan]        (free, good quality)")
        console.print("    2) [cyan]Ollama[/cyan]               (free, runs locally on your machine)")
        console.print("    3) [cyan]Anthropic Claude[/cyan]     (paid, ~$5/month, best quality)")
        console.print("    4) [cyan]OpenAI-compatible[/cyan]    (Qwen/DashScope, DeepSeek, OpenAI, Groq, ...)")
        console.print()
        choice = typer.prompt("  Select (1/2/3/4)", default="1")

        ai_provider = ""
        ai_api_key = ""
        ai_model = ""
        ai_base_url = ""

        if choice == "1":
            ai_provider = "gemini"
            console.print()
            console.print("  [bold]Google Gemini (free tier)[/bold]")
            console.print("  Get your free API key at: [cyan]https://aistudio.google.com/app/apikey[/cyan]")
            console.print()
            ai_api_key = typer.prompt("  Paste your Gemini API key")
            ai_model = "gemini-3.6-flash"
        elif choice == "2":
            ai_provider = "ollama"
            ai_model = "llama3.2"
            console.print()
            console.print("  [bold]Ollama (free, local)[/bold]")
            console.print("  Make sure Ollama is installed and running:")
            console.print("    Install: [cyan]https://ollama.com/download[/cyan]")
            console.print("    Then run: [cyan]ollama pull llama3.2[/cyan]")
            console.print()
            custom_model = typer.prompt("  Ollama model name (press Enter for llama3.2)", default="llama3.2")
            if custom_model:
                ai_model = custom_model
        elif choice == "3":
            ai_provider = "anthropic"
            console.print()
            console.print("  [bold]Anthropic Claude (~$5/month)[/bold]")
            console.print("  Get your key at: [cyan]https://console.anthropic.com/settings/keys[/cyan]")
            console.print()
            ai_api_key = typer.prompt("  Paste your API key (starts with sk-ant-)")
            ai_model = "claude-haiku-4-5-20251001"
        elif choice == "4":
            ai_provider = "openai_compatible"
            console.print()
            console.print("  [bold]OpenAI-compatible endpoint[/bold]")
            console.print("  Any API that speaks the OpenAI /chat/completions format.")
            console.print("  Alibaba Qwen (DashScope): base URL")
            console.print("    [cyan]https://dashscope-intl.aliyuncs.com/compatible-mode/v1[/cyan]  (or dashscope.aliyuncs.com for China)")
            console.print("    model e.g. [cyan]qwen-plus[/cyan], [cyan]qwen-max[/cyan], [cyan]qwen-turbo[/cyan]")
            console.print()
            ai_base_url = typer.prompt(
                "  Base URL", default="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            )
            ai_api_key = typer.prompt("  Paste your API key")
            ai_model = typer.prompt("  Model name", default="qwen-plus")
        else:
            console.print("  [yellow]Invalid choice, defaulting to Gemini.[/yellow]")
            ai_provider = "gemini"
            console.print("  Get your free API key at: [cyan]https://aistudio.google.com/app/apikey[/cyan]")
            ai_api_key = typer.prompt("  Paste your Gemini API key")
            ai_model = "gemini-3.6-flash"

        # Write .env
        env_lines = [
            "# AI Provider",
            f"AI_PROVIDER={ai_provider}",
            f"AI_API_KEY={ai_api_key}",
            f"AI_MODEL={ai_model}",
            f"AI_BASE_URL={ai_base_url}",
            "",
        ]

        # Keep legacy Anthropic vars for backward compat
        if ai_provider == "anthropic":
            env_lines.extend([
                f"ANTHROPIC_API_KEY={ai_api_key}",
                f"ANTHROPIC_MODEL={ai_model}",
                "",
            ])

        env_lines.extend([
            "# Optional --- Notion (free internal integration)",
            "NOTION_TOKEN=",
            "NOTION_JOBS_DB_ID=",
            "",
            "# Optional --- Adzuna free API (register at developer.adzuna.com)",
            "ADZUNA_APP_ID=",
            "ADZUNA_APP_KEY=",
            "",
            "# Gmail + Sheets OAuth tokens auto-saved to config/credentials/ after scout auth",
        ])

        env_path.write_text("\n".join(env_lines) + "\n")
        reset_provider()  # Clear cached provider so new settings take effect
        console.print(f"  [green]\u2713[/green] AI provider saved ({ai_provider})")

    # ── Step 3: Playwright browser ──────────────────────────────────
    chromium_installed = _check_chromium_installed()

    pw_bin = _find_playwright_bin()
    if not chromium_installed:
        if not pw_bin:
            console.print("  [yellow]\u25cb[/yellow] Playwright not found — auto-apply won't work")
            console.print("    [dim]Fix: pip install playwright && playwright install chromium[/dim]")
        else:
            console.print()
            install_pw = typer.confirm("  Install Chromium browser for auto-apply? (recommended)", default=True)
            if install_pw:
                console.print("  [dim]Installing Chromium (one-time, ~150MB)...[/dim]")
                result = subprocess.run([pw_bin, "install", "chromium"], capture_output=True, text=True)
                if result.returncode == 0:
                    console.print("  [green]\u2713[/green] Chromium installed")
                else:
                    console.print("  [yellow]Chromium install failed — auto-apply won't work, but everything else will.[/yellow]")
                    console.print("  [dim]Try later: playwright install chromium[/dim]")
            else:
                console.print("  [yellow]Skipped.[/yellow] You can install later with: playwright install chromium")
    else:
        console.print("  [green]\u2713[/green] Chromium browser ready")

    # ── Step 4: Database ────────────────────────────────────────────
    init_db()
    console.print("  [green]\u2713[/green] Database ready")

    # ── Step 5: Resume ──────────────────────────────────────────────
    master_path = RESUME_DIR / "master.json"
    if master_path.exists():
        try:
            data = json.loads(master_path.read_text())
            name = data.get("personal", {}).get("name", "")
            if name and name != "Your Name":
                console.print(f"  [green]\u2713[/green] Resume found for {name}")
            else:
                raise ValueError("Template resume")
        except (json.JSONDecodeError, ValueError):
            _setup_resume(master_path)
    else:
        _setup_resume(master_path)

    # ── Step 6: Job preferences ─────────────────────────────────────
    prefs_path = CONFIG_DIR / "preferences.yaml"
    if prefs_path.exists() and prefs_path.read_text().strip():
        prefs = load_preferences()
        console.print(f"  [green]\u2713[/green] Preferences loaded ({', '.join(prefs.job_titles[:3])})")
        console.print("  [dim]Tip: run 'scout profile' anytime to change preferences.[/dim]")
    else:
        console.print()
        console.print("  [bold]Step 3: What jobs are you looking for?[/bold]")
        _setup_preferences()

    # ── Step 7: Build UI if needed ──────────────────────────────────
    static_dir = Path(__file__).parent / "src" / "api" / "static"
    if not (static_dir / "index.html").exists():
        ui_dir = Path(__file__).parent / "ui"
        if (ui_dir / "package.json").exists():
            console.print()
            build_ui = typer.confirm("  Build the web dashboard? (recommended)", default=True)
            if build_ui:
                console.print("  [dim]Building dashboard...[/dim]")
                subprocess.run(["npm", "ci", "--silent"], cwd=str(ui_dir), capture_output=True)
                result = subprocess.run(["npm", "run", "build"], cwd=str(ui_dir), capture_output=True, text=True)
                if result.returncode == 0:
                    console.print("  [green]\u2713[/green] Dashboard built")
                else:
                    console.print("  [yellow]Dashboard build failed — you can still use the CLI.[/yellow]")
                    console.print("  [dim]Fix later: cd ui && npm install && npm run build[/dim]")
            else:
                console.print("  [yellow]Skipped.[/yellow] Build later: cd ui && npm install && npm run build")
    else:
        console.print("  [green]\u2713[/green] Dashboard built")

    # ── All done! ───────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold green]You're all set![/bold green]\n\n"
        "  [cyan]scout scrape[/cyan]    Find jobs now\n"
        "  [cyan]scout score[/cyan]     AI-score your matches\n"
        "  [cyan]scout ui[/cyan]        Open the dashboard\n"
        "  [cyan]scout profile[/cyan]   Change job preferences\n"
        "  [cyan]scout doctor[/cyan]    Check if everything's working",
        title="What's Next",
        expand=False,
    ))


def _find_playwright_bin() -> str | None:
    """Find the playwright CLI binary — checks venv first, then system PATH."""
    import shutil
    import sys

    # Check alongside the current Python interpreter (venv/bin/playwright)
    venv_pw = Path(sys.executable).parent / "playwright"
    if venv_pw.exists():
        return str(venv_pw)
    # Fall back to system PATH
    return shutil.which("playwright")


def _check_chromium_installed() -> bool:
    """Return True if Playwright's Chromium browser is already installed.

    Asks Playwright for the resolved executable path and checks it exists.
    This is version- and platform-independent (it honors
    PLAYWRIGHT_BROWSERS_PATH and the OS cache location automatically). The old
    `playwright install --list` subprocess was not a valid subcommand, so the
    check always failed and setup re-prompted the install on every run.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


def _setup_resume(master_path: Path) -> None:
    """Interactive mini-wizard to create a starter resume."""
    console.print()
    console.print("  [bold]Step 2: Your resume info[/bold]")
    console.print("  [dim]We need the basics to tailor resumes for you.[/dim]")
    console.print()

    name = typer.prompt("  Your full name")
    email = typer.prompt("  Email address")
    phone = typer.prompt("  Phone number (or press Enter to skip)", default="")
    location = typer.prompt("  Current location (e.g. London, UK)", default="")
    linkedin = typer.prompt("  LinkedIn URL (or Enter to skip)", default="")
    github = typer.prompt("  GitHub URL (or Enter to skip)", default="")

    console.print()
    summary = typer.prompt(
        "  Professional summary (2-3 sentences about your experience)",
        default="",
    )

    console.print()
    console.print("  [bold]Most recent job:[/bold]")
    role = typer.prompt("    Job title", default="")
    company = typer.prompt("    Company", default="")
    role_location = typer.prompt("    Location", default="")

    console.print()
    raw_skills = typer.prompt(
        "  Your top skills (comma-separated, e.g. Python, React, AWS)",
        default="",
    )
    skills = [s.strip() for s in raw_skills.split(",") if s.strip()]

    resume_data = {
        "personal": {
            "name": name,
            "email": email,
            "phone": phone,
            "location": location,
            "linkedin": linkedin,
            "github": github,
            "website": "",
        },
        "summary": summary,
        "experience": [],
        "skills": skills,
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": ["English"],
    }

    if role and company:
        resume_data["experience"].append({
            "role": role,
            "company": company,
            "location": role_location,
            "start_date": "",
            "end_date": "present",
            "bullets": [],
        })

    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text(json.dumps(resume_data, indent=2))
    console.print("  [green]\u2713[/green] Resume saved to resume/master.json")
    console.print("  [dim]Tip: edit resume/master.json later to add more details.[/dim]")


def _setup_preferences() -> None:
    """Streamlined preferences wizard for first-run setup."""
    from src.domain import detect_domain, is_regulated
    from src.preferences import Preferences, save_preferences

    console.print()
    console.print("  [bold]What field are you in?[/bold]")
    console.print("    1) Technology (software, data, DevOps)")
    console.print("    2) Healthcare (nursing, medical, clinical)")
    console.print("    3) Hospitality (hotel, restaurant, food service)")
    console.print("    4) Education (teaching, academic)")
    console.print("    5) Other / General")
    domain_choice = typer.prompt("  Select (1-5)", default="5")
    domain_map = {"1": "technology", "2": "medical", "3": "hospitality", "4": "education", "5": "general"}
    domain = domain_map.get(domain_choice.strip(), "general")

    console.print()
    raw = typer.prompt(
        "  Job titles you want (comma-separated)",
    )
    job_titles = [t.strip() for t in raw.split(",") if t.strip()]

    # Auto-detect domain from job titles if user picked "general" but titles suggest otherwise
    if domain == "general" and job_titles:
        detected = detect_domain(job_titles)
        if detected != "general":
            domain = detected
            console.print(f"  [dim]Detected domain: {domain}[/dim]")

    # Set smart defaults based on domain
    default_location = "Remote" if domain == "technology" else ""
    raw = typer.prompt(
        "  Preferred locations (comma-separated)",
        default=default_location if default_location else None,
    )
    locations = [t.strip() for t in raw.split(",") if t.strip()]

    console.print("  Experience: 1) junior  2) mid  3) senior  4) staff  5) lead")
    raw = typer.prompt("  Select levels (numbers, comma-separated)", default="2,3")
    level_map = {"1": "junior", "2": "mid", "3": "senior", "4": "staff", "5": "lead"}
    experience_levels = [level_map[n.strip()] for n in raw.split(",") if n.strip() in level_map]

    raw = typer.prompt(
        "  Required keywords — jobs must mention at least one (comma-separated, or Enter to skip)",
        default="",
    )
    keywords_required = [t.strip() for t in raw.split(",") if t.strip()]

    prefs = Preferences(
        domain=domain,
        job_titles=job_titles,
        locations=locations,
        experience_levels=experience_levels or ["mid", "senior"],
        keywords_required=keywords_required,
    )
    save_preferences(prefs)

    console.print(f"  [green]\u2713[/green] Preferences saved ({domain} — {', '.join(job_titles[:3])})")
    if is_regulated(domain):
        console.print(f"  [yellow]Note: auto-apply is disabled for {domain} roles (manual review required).[/yellow]")
    console.print("  [dim]Tip: run 'scout profile' anytime to change all preferences.[/dim]")


@app.command("profile")
def profile() -> None:
    """Interactive job preferences wizard — tell Scout what roles you want."""
    from src.preferences import Preferences, save_preferences

    console.print(Panel("[bold cyan]Scout — Profile Setup[/bold cyan]", expand=False))
    console.print("  Configure your job search preferences. Press Enter to keep defaults.\n")

    # 1. Job titles
    raw = typer.prompt(
        "  What job titles are you looking for? (comma-separated)",
        default="",
    )
    job_titles = [t.strip() for t in raw.split(",") if t.strip()]

    # 2. Locations
    raw = typer.prompt(
        "  Preferred locations? (comma-separated)",
        default="Remote",
    )
    locations = [t.strip() for t in raw.split(",") if t.strip()]

    # 3. Experience levels
    console.print("\n  Experience levels:")
    console.print("    1) junior   2) mid   3) senior   4) staff   5) lead")
    raw = typer.prompt("  Select levels (comma-separated numbers)", default="2,3")
    level_map = {"1": "junior", "2": "mid", "3": "senior", "4": "staff", "5": "lead"}
    experience_levels = [level_map[n.strip()] for n in raw.split(",") if n.strip() in level_map]

    # 4. Remote preference
    console.print("\n  Remote preference:")
    console.print("    1) Remote First   2) Remote Only   3) Hybrid   4) On-site   5) Any")
    raw = typer.prompt("  Select one", default="1")
    remote_map = {"1": "remote_first", "2": "remote_only", "3": "hybrid", "4": "onsite", "5": "any"}
    remote_preference = remote_map.get(raw.strip(), "remote_first")

    # 5. Employment type
    raw = typer.prompt(
        "\n  Employment type? (comma-separated, e.g. full-time, contract)",
        default="full-time",
    )
    employment_type = [t.strip() for t in raw.split(",") if t.strip()]

    # 6. Industries
    raw = typer.prompt(
        "  Target industries? (comma-separated, or press Enter to skip)",
        default="",
    )
    industries = [t.strip() for t in raw.split(",") if t.strip()]

    # 7. Required keywords
    raw = typer.prompt(
        "\n  Required keywords — jobs must mention at least one (comma-separated)",
        default="",
    )
    keywords_required = [t.strip() for t in raw.split(",") if t.strip()]

    # 8. Excluded keywords
    raw = typer.prompt(
        "  Keywords to exclude — reject jobs containing these (comma-separated)",
        default="sales, unpaid",
    )
    keywords_excluded = [t.strip() for t in raw.split(",") if t.strip()]

    # 9. Company blacklist
    raw = typer.prompt(
        "  Companies to blacklist? (comma-separated, or press Enter to skip)",
        default="",
    )
    company_blacklist = [t.strip() for t in raw.split(",") if t.strip()]

    # 10. Salary minimum
    salary_min = typer.prompt("  Minimum salary (USD)", default=0, type=int)

    # 11. Min match score
    min_match_score = typer.prompt(
        "  Minimum AI match score (0.0–1.0)", default=0.65, type=float,
    )

    prefs = Preferences(
        job_titles=job_titles,
        locations=locations,
        experience_levels=experience_levels,
        salary_min=salary_min,
        remote_preference=remote_preference,
        employment_type=employment_type,
        industries=industries,
        company_blacklist=company_blacklist,
        keywords_required=keywords_required,
        keywords_excluded=keywords_excluded,
        min_match_score=min_match_score,
    )
    save_preferences(prefs)

    console.print()
    table = Table(title="Saved Preferences", show_header=False, expand=False)
    table.add_column("Field", style="bold")
    table.add_column("Value", style="cyan")
    table.add_row("Job Titles", ", ".join(prefs.job_titles))
    table.add_row("Locations", ", ".join(prefs.locations))
    table.add_row("Experience", ", ".join(prefs.experience_levels))
    table.add_row("Remote", prefs.remote_preference)
    table.add_row("Employment", ", ".join(prefs.employment_type))
    table.add_row("Industries", ", ".join(prefs.industries) or "any")
    table.add_row("Required Keywords", ", ".join(prefs.keywords_required) or "none")
    table.add_row("Excluded Keywords", ", ".join(prefs.keywords_excluded) or "none")
    table.add_row("Blacklisted Companies", ", ".join(prefs.company_blacklist) or "none")
    table.add_row("Min Salary", f"${prefs.salary_min:,}")
    table.add_row("Min Match Score", f"{prefs.min_match_score:.0%}")
    console.print(table)
    console.print()
    console.print("[bold green]Profile saved![/bold green] Run [cyan]scout scrape[/cyan] to find matching jobs.")


@app.command("doctor")
def doctor() -> None:
    """Diagnose your Scout installation — checks everything is working."""
    import shutil
    import subprocess
    import sys

    from src.paths import CONFIG_DIR, RESUME_DIR, DATA_DIR

    console.print()
    console.print(Panel("[bold cyan]Scout Doctor[/bold cyan]", expand=False))
    console.print()

    issues = 0

    # Python
    v = sys.version_info
    if v.major == 3 and v.minor >= 12:
        console.print(f"  [green]\u2713[/green] Python {v.major}.{v.minor}.{v.micro}")
    else:
        console.print(f"  [red]\u2717[/red] Python {v.major}.{v.minor}.{v.micro} — need 3.12+")
        issues += 1

    # AI Provider
    from src.settings import load_settings
    settings = load_settings()
    provider = settings.effective_provider

    _provider_labels = {
        "anthropic": "Anthropic",
        "gemini": "Google Gemini",
        "ollama": "Ollama",
        "openai_compatible": "OpenAI-compatible",
    }
    if not provider:
        console.print("  [red]\u2717[/red] No AI provider configured")
        console.print("    [dim]Run: scout setup[/dim]")
        issues += 1
    else:
        label = _provider_labels.get(provider, provider)
        # Live check: a tiny real call. This catches a retired model, a bad
        # key, or a wrong base URL, which a presence-only check misses.
        try:
            from src.ai.ai_client import _get_provider, reset_provider
            reset_provider()
            _get_provider().call("You are a connectivity test.", "Reply with the single word OK.", 8)
            console.print(f"  [green]\u2713[/green] AI: {label} ({settings.effective_model}) \u2014 working")
        except Exception as e:
            console.print(f"  [red]\u2717[/red] AI: {label} ({settings.effective_model}) \u2014 {str(e)[:70]}")
            console.print("    [dim]Check your key and model. Run: scout setup --reconfigure[/dim]")
            issues += 1

    # Database
    db_path = DATA_DIR / "scout.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        with managed_session() as session:
            job_count = session.query(Job).count()
        console.print(f"  [green]\u2713[/green] Database: {job_count} jobs ({size_mb:.1f} MB)")
    else:
        console.print("  [yellow]\u25cb[/yellow] Database not created yet (will be created on first scrape)")

    # Resume
    master_path = RESUME_DIR / "master.json"
    if master_path.exists():
        try:
            data = json.loads(master_path.read_text())
            name = data.get("personal", {}).get("name", "")
            if name and name != "Your Name":
                skill_count = len(data.get("skills", []))
                exp_count = len(data.get("experience", []))
                console.print(f"  [green]\u2713[/green] Resume: {name} ({skill_count} skills, {exp_count} roles)")
            else:
                console.print("  [yellow]\u25cb[/yellow] Resume is a template — needs your info")
                console.print("    [dim]Run: scout setup[/dim]")
                issues += 1
        except json.JSONDecodeError:
            console.print("  [red]\u2717[/red] Resume file is corrupted (invalid JSON)")
            issues += 1
    else:
        console.print("  [red]\u2717[/red] No resume found at resume/master.json")
        console.print("    [dim]Run: scout setup[/dim]")
        issues += 1

    # Preferences
    prefs_path = CONFIG_DIR / "preferences.yaml"
    if prefs_path.exists():
        prefs = load_preferences()
        console.print(f"  [green]\u2713[/green] Preferences: {', '.join(prefs.job_titles[:3])}")
    else:
        console.print("  [yellow]\u25cb[/yellow] No preferences set (using defaults)")
        console.print("    [dim]Run: scout profile[/dim]")

    # Playwright / Chromium
    pw_bin = _find_playwright_bin()
    if pw_bin:
        if _check_chromium_installed():
            console.print("  [green]\u2713[/green] Playwright + Chromium ready")
        else:
            console.print("  [yellow]\u25cb[/yellow] Chromium not installed (needed for auto-apply)")
            console.print("    [dim]Run: playwright install chromium[/dim]")
    else:
        console.print("  [red]\u2717[/red] Playwright not found")
        console.print("    [dim]Run: pip install playwright && playwright install chromium[/dim]")
        issues += 1

    # Web UI
    static_dir = Path(__file__).parent / "src" / "api" / "static"
    if (static_dir / "index.html").exists():
        console.print("  [green]\u2713[/green] Dashboard built and ready")
    else:
        console.print("  [yellow]\u25cb[/yellow] Dashboard not built (CLI still works)")
        console.print("    [dim]Run: cd ui && npm install && npm run build[/dim]")

    # PDF export (WeasyPrint needs the Pango native library)
    try:
        import weasyprint  # noqa: F401  (import triggers the Pango dlopen)
        console.print("  [green]\u2713[/green] PDF export ready (WeasyPrint + Pango)")
    except (ImportError, OSError):
        console.print("  [yellow]\u25cb[/yellow] PDF export unavailable (DOCX still works)")
        console.print("    [dim]macOS: brew install pango  |  Debian/Ubuntu: apt-get install libpango-1.0-0 libpangocairo-1.0-0[/dim]")

    # Node
    if shutil.which("node"):
        node_ver = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
        console.print(f"  [green]\u2713[/green] Node.js {node_ver}")
    else:
        console.print("  [yellow]\u25cb[/yellow] Node.js not found (needed to rebuild dashboard)")

    # Gmail credentials
    gmail_creds = CONFIG_DIR / "credentials" / "gmail_token.json"
    if gmail_creds.exists():
        console.print("  [green]\u2713[/green] Gmail connected")
    else:
        console.print("  [dim]\u25cb[/dim] Gmail not connected (optional — run: scout auth gmail)")

    # Summary
    console.print()
    if issues == 0:
        console.print("[bold green]Everything looks good! Scout is ready to go.[/bold green]")
    else:
        console.print(f"[yellow]{issues} issue(s) found.[/yellow] Run [cyan]scout setup[/cyan] to fix them.")
    console.print()


@app.command("update")
def update() -> None:
    """Update Scout to the latest version."""
    import subprocess
    import sys

    console.print(Panel("[bold cyan]Scout — Update[/bold cyan]", expand=False))

    project_root = Path(__file__).parent

    # Pull latest code
    console.print("  Pulling latest changes...")
    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(project_root), capture_output=True, text=True,
    )
    if result.returncode == 0:
        if "Already up to date" in result.stdout:
            console.print("  [green]\u2713[/green] Already on the latest version")
        else:
            console.print("  [green]\u2713[/green] Code updated")
    else:
        console.print(f"  [red]\u2717[/red] Git pull failed: {result.stderr.strip()}")
        console.print("  [dim]You may have local changes. Run: git stash && scout update[/dim]")
        raise typer.Exit(1)

    # Reinstall Python deps
    console.print("  Updating Python packages...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-e", "."],
        cwd=str(project_root), capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print("  [green]\u2713[/green] Python packages updated")
    else:
        console.print(f"  [yellow]pip install warning: {result.stderr.strip()[:200]}[/yellow]")

    # Rebuild UI
    ui_dir = project_root / "ui"
    if (ui_dir / "package.json").exists():
        console.print("  Rebuilding dashboard...")
        subprocess.run(["npm", "ci", "--silent"], cwd=str(ui_dir), capture_output=True)
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(ui_dir), capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print("  [green]\u2713[/green] Dashboard rebuilt")
        else:
            console.print("  [yellow]Dashboard build failed — CLI still works.[/yellow]")

    console.print()
    console.print("[bold green]Update complete![/bold green]")
    console.print()


# --- Phase 4: Tracking & Integrations ---

auth_app = typer.Typer(help="Authentication commands")
app.add_typer(auth_app, name="auth")

daemon_app = typer.Typer(help="Background daemon commands")
app.add_typer(daemon_app, name="daemon")


@auth_app.command("gmail")
def auth_gmail() -> None:
    """Authenticate with Gmail API (one-time OAuth flow)."""
    console.print(Panel("[bold cyan]Gmail OAuth Setup[/bold cyan]", expand=False))
    try:
        from src.tracking.gmail_reader import authenticate_gmail
        authenticate_gmail()
        console.print("[bold green]Gmail authenticated![/bold green]")
    except FileNotFoundError:
        console.print("[red]Setup client_secret.json first (see instructions above).[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Gmail auth failed: {e}[/red]")
        raise typer.Exit(1)


@auth_app.command("sheets")
def auth_sheets() -> None:
    """Authenticate with Google Sheets API (one-time OAuth flow)."""
    console.print(Panel("[bold cyan]Google Sheets OAuth Setup[/bold cyan]", expand=False))
    try:
        from src.integrations.sheets_sync import authenticate_sheets
        authenticate_sheets()
        console.print("[bold green]Sheets authenticated![/bold green]")
    except FileNotFoundError:
        console.print("[red]Setup client_secret.json first (see instructions above).[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Sheets auth failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("email-sync")
def email_sync() -> None:
    """Scan Gmail for application status emails and update pipeline."""
    init_db()
    console.print(Panel("[bold cyan]Scout — Email Sync[/bold cyan]", expand=False))

    from src.tracking.gmail_reader import sync_emails
    processed, updated = sync_emails()

    console.print()
    console.print(
        Panel(
            f"[bold green]{processed} emails processed[/bold green]  ·  "
            f"[cyan]{updated} statuses updated[/cyan]",
            title="Email Sync Complete",
            expand=False,
        )
    )


@app.command("notion-sync")
def notion_sync() -> None:
    """Sync job pipeline to Notion database."""
    init_db()
    console.print(Panel("[bold cyan]Scout — Notion Sync[/bold cyan]", expand=False))

    try:
        from src.integrations.notion_sync import sync_to_notion
        created, updated = sync_to_notion()
        console.print()
        console.print(
            Panel(
                f"[bold green]{created} pages created[/bold green]  ·  "
                f"[cyan]{updated} pages updated[/cyan]",
                title="Notion Sync Complete",
                expand=False,
            )
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("sheets-sync")
def sheets_sync() -> None:
    """Export applications to Google Sheets."""
    init_db()
    console.print(Panel("[bold cyan]Scout — Sheets Export[/bold cyan]", expand=False))

    try:
        from src.integrations.sheets_sync import sync_to_sheets
        rows = sync_to_sheets()
        console.print()
        console.print(
            Panel(
                f"[bold green]{rows} rows exported[/bold green]",
                title="Sheets Export Complete",
                expand=False,
            )
        )
    except FileNotFoundError:
        console.print("[red]Run 'scout auth sheets' first.[/red]")
        raise typer.Exit(1)


@app.command("api")
def api_server(
    port: int = typer.Option(8000, help="Port to run API on"),
) -> None:
    """Start the FastAPI backend server."""
    import uvicorn
    console.print(Panel(f"[bold cyan]Scout API — localhost:{port}[/bold cyan]", expand=False))
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=port, reload=True)


def _find_free_port(start: int = 8000) -> int:
    """Find a free TCP port starting from `start`."""
    import socket
    for p in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}-{start + 99}")


@app.command("ui")
def start_ui(
    port: int = typer.Option(8000, help="Port to run on"),
    no_browser: bool = typer.Option(False, help="Don't auto-open browser"),
    dev: bool = typer.Option(False, help="Run in dev mode (separate Vite server)"),
) -> None:
    """Start Scout UI. Serves the bundled frontend on a single port."""
    import subprocess
    import sys
    import time
    import webbrowser

    if dev:
        # Dev mode: two servers (uvicorn + vite)
        console.print(Panel("[bold cyan]Scout — Dev Mode[/bold cyan]", expand=False))

        api_port = _find_free_port(port)
        console.print(f"  Starting API server on port {api_port}...")
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", str(api_port), "--reload"],
            cwd=str(Path(__file__).parent),
        )

        console.print("  Starting Vite dev server on port 3000...")
        ui_dir = Path(__file__).parent / "ui"
        vite_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(ui_dir),
        )

        time.sleep(3)
        url = "http://localhost:3000"
        if not no_browser:
            webbrowser.open(url)
        console.print()
        console.print(f"[bold green]Scout UI running at {url}[/bold green]")
        console.print("[dim]Press Ctrl+C to stop both servers[/dim]")

        try:
            api_proc.wait()
        except KeyboardInterrupt:
            api_proc.terminate()
            vite_proc.terminate()
            console.print("\n[dim]Servers stopped.[/dim]")
    else:
        # Production mode: single server serving bundled frontend
        static_dir = Path(__file__).parent / "src" / "api" / "static"
        if not (static_dir / "index.html").exists():
            console.print("[red]Frontend not built.[/red]")
            console.print("  Run: [cyan]cd ui && npm install && npm run build[/cyan]")
            console.print("  Or use dev mode: [cyan]scout ui --dev[/cyan]")
            raise typer.Exit(1)

        actual_port = _find_free_port(port)
        if actual_port != port:
            console.print(f"  [yellow]Port {port} in use, using {actual_port}[/yellow]")

        url = f"http://localhost:{actual_port}"
        console.print(Panel(f"[bold cyan]Scout — {url}[/bold cyan]", expand=False))

        if not no_browser:
            import threading
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()

        import uvicorn
        uvicorn.run("src.api.main:app", host="127.0.0.1", port=actual_port)


@app.command("dedup")
def dedup_jobs(
    aggressive: bool = typer.Option(False, "--aggressive", help="Collapse multi-location variants of the same role into one job."),
    merge: bool = typer.Option(False, "--merge", help="Actually run the merge. Without this flag, only a preview is shown."),
) -> None:
    """Find and remove duplicate jobs.

    By default runs in 'strict' mode (same company+title+location merged).
    Use --aggressive to also collapse multi-location variants.
    """
    init_db()
    mode = "by_role" if aggressive else "strict"

    from src.dedup import preview_duplicates, merge_duplicates

    preview = preview_duplicates(mode=mode)
    console.print(Panel(
        f"[bold cyan]Scout Dedup[/bold cyan] · mode=[yellow]{mode}[/yellow]\n"
        f"Found [bold]{preview['group_count']}[/bold] duplicate group(s) "
        f"covering [bold]{preview['duplicate_count']}[/bold] redundant job rows.",
        expand=False,
    ))

    if preview["group_count"] == 0:
        console.print("[green]Nothing to clean up. Your job list is already deduplicated.[/green]")
        return

    # Show top 10 groups
    table = Table(title="Largest duplicate groups", show_lines=False, expand=False)
    table.add_column("Dupes", style="dim", width=6)
    table.add_column("Company", style="cyan")
    table.add_column("Title")
    table.add_column("Canonical status", style="yellow", width=14)
    for g in preview["groups"][:10]:
        c = g["canonical"]
        table.add_row(
            str(g["loser_count"]),
            (c["company"] or "")[:30],
            (c["title"] or "")[:50],
            (c["status"] or "scraped"),
        )
    console.print(table)

    if not merge:
        console.print()
        console.print("[dim]Preview only. Run with [bold]--merge[/bold] to actually clean up.[/dim]")
        if not aggressive:
            console.print("[dim]Use [bold]--aggressive[/bold] to also collapse multi-location variants of the same role.[/dim]")
        return

    console.print()
    console.print(f"[yellow]Merging {preview['duplicate_count']} duplicates...[/yellow]")
    result = merge_duplicates(mode=mode)
    refs = result["references_migrated"]
    console.print(Panel(
        f"[bold green]Merged {result['groups_processed']} groups, removed {result['jobs_removed']} duplicate jobs.[/bold green]\n"
        f"  Migrated to canonical: "
        f"{refs['resumes']} resume(s), "
        f"{refs['applications']} application(s), "
        f"{refs['events']} event(s).",
        title="Dedup Complete",
        expand=False,
    ))


@app.command("ghosted")
def ghosted_check() -> None:
    """Flag applications with no reply in 21 days."""
    init_db()
    console.print(Panel("[bold cyan]Scout — Ghosted Detector[/bold cyan]", expand=False))

    from src.tracking.gmail_reader import detect_ghosted
    count = detect_ghosted()

    console.print()
    console.print(f"  [bold]{count} applications flagged as ghosted[/bold]")


@daemon_app.command("start")
def daemon_start() -> None:
    """Start the background scheduler daemon."""
    from src.scheduler import is_daemon_running, start_daemon

    if is_daemon_running():
        console.print("[yellow]Daemon is already running.[/yellow]")
        raise typer.Exit(0)

    console.print(Panel("[bold cyan]Scout Daemon[/bold cyan]", expand=False))
    console.print("  Starting scheduler... (Ctrl+C to stop)")
    console.print()
    start_daemon()


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Stop the background scheduler daemon."""
    from src.scheduler import stop_daemon

    if stop_daemon():
        console.print("[green]Daemon stopped.[/green]")
    else:
        console.print("[yellow]Daemon is not running.[/yellow]")


@daemon_app.command("status")
def daemon_status() -> None:
    """Check if the daemon is running."""
    from src.scheduler import is_daemon_running, LOG_PATH

    if is_daemon_running():
        console.print("[green]Daemon is running.[/green]")
    else:
        console.print("[dim]Daemon is not running.[/dim]")

    # Show last 10 log lines
    if LOG_PATH.exists():
        lines = LOG_PATH.read_text().splitlines()[-10:]
        if lines:
            console.print()
            console.print("[bold]Recent activity:[/bold]")
            for line in lines:
                console.print(f"  [dim]{line}[/dim]")


if __name__ == "__main__":
    app()
