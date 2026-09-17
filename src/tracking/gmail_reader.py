"""Gmail API integration -- OAuth setup, inbox scanning, status updates with timeline events."""

import base64
import uuid
from datetime import UTC, datetime, timedelta

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from rich.console import Console

from src.ai.email_parser import parse_email
from src.database import Application, Job, managed_session, record_event
from src.paths import CREDENTIALS_DIR

console = Console()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH = CREDENTIALS_DIR / "gmail_token.json"
CLIENT_SECRET_PATH = CREDENTIALS_DIR / "client_secret.json"

# ATS domains to search for
ATS_DOMAINS = [
    "greenhouse.io",
    "lever.co",
    "workday.com",
    "myworkdayjobs.com",
    "bamboohr.com",
    "icims.com",
    "jobvite.com",
    "smartrecruiters.com",
    "ashbyhq.com",
    "workable.com",
    "breezy.hr",
    "jazz.co",
    "recruitee.com",
    "applytojob.com",
    "personio.de",
    "teamtailor-mail.com",
    "onlyfy.jobs",
    "workablemail.com",
    "deliveryherogroup.com",
    "swissmarketplace.group",
    "pinpoint.email",
    "wise.jobs",
]

# Generic status language so rejections from custom company domains
# (not in ATS_DOMAINS) are caught and matched against scraped jobs.
STATUS_TERMS = [
    "your application",
    "thank you for applying",
    "application received",
    "regret to inform",
    "move forward with other candidates",
    "not moving forward",
    "not be progressing",
    "decided not to proceed",
    "unable to move forward",
    "interview",
    "we would like to invite",
    "offer",
]

# Forward-only status precedence. A later email must not drag an application
# back to an earlier stage, and terminal outcomes must not be overwritten by a
# stray "thank you for applying" auto-reply that arrives (or is processed) late.
STATUS_RANK = {
    "ghosted": 0,
    "applied": 1,
    "under_review": 2,
    "interview": 3,
    "offer": 4,
    "rejected": 4,
}
TERMINAL_STATUSES = {"offer", "rejected"}


def authenticate_gmail() -> Credentials:
    """Run OAuth flow or refresh existing token. Returns credentials."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                console.print("  [yellow]Saved Gmail token is no longer valid; re-authorizing.[/yellow]")
                creds = None

        if not refreshed:
            if not CLIENT_SECRET_PATH.exists():
                console.print("[red]client_secret.json not found![/red]")
                console.print(
                    "  1. Go to console.cloud.google.com -> APIs & Services -> Credentials\n"
                    "  2. Create OAuth 2.0 Client ID (Desktop app)\n"
                    "  3. Download JSON and save to:\n"
                    f"     {CLIENT_SECRET_PATH}"
                )
                raise FileNotFoundError(str(CLIENT_SECRET_PATH))

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())
        TOKEN_PATH.chmod(0o600)  # Owner read/write only
        console.print(f"  [green]Token saved to {TOKEN_PATH}[/green]")

    return creds


def get_gmail_service():
    """Get authenticated Gmail API service."""
    creds = authenticate_gmail()
    return build("gmail", "v1", credentials=creds)


def sync_emails() -> tuple[int, int]:
    """Scan inbox for application-related emails. Returns (processed, updated)."""
    service = get_gmail_service()

    processed = 0
    updated = 0

    with managed_session() as session:
        jobs = session.query(Job).all()
        if not jobs:
            console.print("  [dim]No jobs in the database yet.[/dim]")
            return 0, 0

        real_apps = (
            session.query(Application).filter(Application.is_dry_run.is_(False)).all()
        )
        app_by_job = {a.job_id: a for a in real_apps}

        # Map each company to one job, preferring a job we applied to, then the
        # most recently scraped. Company-level matching lets us update status for
        # jobs applied to OUTSIDE Scout (LinkedIn, Personio, direct email) too.
        def _rank(job: Job) -> tuple[int, float]:
            applied = 0 if job.id in app_by_job else 1
            ts = job.scraped_at.timestamp() if job.scraped_at else 0.0
            return (applied, -ts)

        job_company_map: dict[str, tuple[str, Application | None]] = {}
        for job in sorted(jobs, key=_rank):
            key = job.company.lower().strip()
            if key and key not in job_company_map:
                job_company_map[key] = (job.id, app_by_job.get(job.id))

        applied_companies = [
            job.company for job_id in app_by_job if (job := session.get(Job, job_id))
        ]
        companies = applied_companies or [job.company for job in jobs]

        # ATS senders OR generic status language, so rejections from custom
        # company domains are caught and matched against the jobs table.
        domain_queries = " OR ".join(f"from:{d}" for d in ATS_DOMAINS)
        term_queries = " OR ".join(f'"{t}"' for t in STATUS_TERMS)
        query = f"(({domain_queries}) OR ({term_queries})) newer_than:14d"

        try:
            results = service.users().messages().list(
                userId="me", q=query, maxResults=100
            ).execute()
        except HttpError as e:
            if "accessNotConfigured" in str(e) or e.resp.status == 403:
                console.print(
                    "  [red]Gmail API is not enabled for this Google Cloud project.[/red]\n"
                    "  Enable it, wait ~2 min, then retry:\n"
                    "  https://console.cloud.google.com/apis/library/gmail.googleapis.com"
                )
            else:
                console.print(f"  [red]Gmail API error: {e}[/red]")
            return 0, 0

        message_ids = results.get("messages", [])
        console.print(f"  Found {len(message_ids)} potential emails")

        # Fetch first, then process oldest-first so the newest email wins.
        fetched = []
        for msg_meta in message_ids:
            try:
                fetched.append(
                    service.users().messages().get(
                        userId="me", id=msg_meta["id"], format="full"
                    ).execute()
                )
            except HttpError as e:
                console.print(f"  [dim]Error fetching {msg_meta.get('id', '?')}: {e}[/dim]")
        fetched.sort(key=lambda m: int(m.get("internalDate", 0)))

        for msg in fetched:
            try:
                headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
                subject = headers.get("Subject", "")
                sender = headers.get("From", "")
                body = _extract_body(msg)

                parsed = parse_email(subject, body, companies)
                processed += 1

                if not parsed.get("is_job_related"):
                    continue

                company = parsed.get("company", "")
                status = parsed.get("status", "")
                interview_dt = parsed.get("interview_datetime")

                if not company or not status:
                    continue

                # Find matching job -- exact then fuzzy. A job applied to
                # outside Scout has no Application row yet, so create one.
                job_id, app = _match_company(company, job_company_map)
                if not job_id:
                    continue
                if app is None:
                    app = _ensure_application(session, job_id)

                now = datetime.now(UTC)

                # Always update email tracking fields regardless of status change
                app.last_email_at = now
                app.updated_at = now
                app.email_count = (app.email_count or 0) + 1

                # Track first response
                if not app.first_response_at:
                    app.first_response_at = now

                # Track specific milestones (always, even if status unchanged)
                if interview_dt:
                    try:
                        app.interview_at = datetime.fromisoformat(interview_dt)
                    except (ValueError, TypeError):
                        pass

                if parsed.get("notes"):
                    app.notes = parsed["notes"]

                # Forward-only: never regress out of a terminal outcome, and
                # never drag an application back to an earlier stage.
                regresses = STATUS_RANK.get(status, 0) < STATUS_RANK.get(app.status, 0)
                if app.status in TERMINAL_STATUSES or regresses:
                    continue

                # Only update status and record event if status actually changed
                if app.status != status:
                    old_status = app.status
                    app.status = status

                    if status == "offer":
                        app.offer_at = now
                    elif status == "rejected":
                        app.rejected_at = now

                    # Update job status too
                    job = session.get(Job, job_id)
                    if job:
                        job.status = status

                    # Record timeline events
                    record_event(
                        app.id, job_id, "email_received",
                        {
                            "old_status": old_status,
                            "new_status": status,
                            "subject": subject[:200],
                            "sender": sender[:100],
                            "notes": parsed.get("notes", "")[:300],
                        },
                        source="email",
                        session=session,
                    )
                    record_event(
                        app.id, job_id, "status_changed",
                        {"from": old_status, "to": status, "trigger": "email"},
                        source="email",
                        session=session,
                    )

                    updated += 1
                    console.print(
                        f"    [cyan]{company}[/cyan]: {old_status} -> [bold]{status}[/bold]"
                    )

                    # Notify for important updates
                    if status in ("interview", "offer"):
                        _notify(company, status, parsed.get("notes", ""))

            except Exception as e:
                console.print(f"  [dim]Error processing email {msg_meta.get('id', '?')}: {e}[/dim]")
                continue

    return processed, updated


def detect_ghosted() -> int:
    """Flag applications with no email reply in 21 days."""
    ghosted_count = 0

    with managed_session() as session:
        cutoff = datetime.now(UTC) - timedelta(days=21)
        now = datetime.now(UTC)

        # Find applied apps that are older than 21 days AND have never received a response
        apps = session.query(Application).filter(
            Application.status == "applied",
            Application.is_dry_run.is_(False),
        ).all()

        for app in apps:
            app_date = app.created_at
            if not app_date or app_date >= cutoff:
                continue

            # No response received at all
            if app.first_response_at is not None:
                continue

            app.status = "ghosted"
            app.updated_at = now

            job = session.get(Job, app.job_id)
            if job:
                job.status = "ghosted"
                console.print(f"  [dim]Ghosted: {job.company} -- {job.title}[/dim]")

            record_event(
                app.id, app.job_id, "ghosted",
                {"days_since_applied": (now - app_date).days},
                source="scheduler",
                session=session,
            )
            ghosted_count += 1

    return ghosted_count


def _ensure_application(session, job_id: str) -> Application:
    """Create a real Application row for a job applied to outside Scout.

    Flushed so its id is available for events written in the same session.
    """
    now = datetime.now(UTC)
    app = Application(
        id=uuid.uuid4().hex,
        job_id=job_id,
        status="applied",
        created_at=now,
        updated_at=now,
        is_dry_run=False,
        email_count=0,
        applied_via="email-detected",
    )
    session.add(app)
    session.flush()
    return app


def _match_company(
    company: str,
    job_company_map: dict[str, tuple[str, Application | None]],
) -> tuple[str | None, Application | None]:
    """Match a company name from email to our applications."""
    company_lower = company.lower().strip()

    # Exact match
    if company_lower in job_company_map:
        return job_company_map[company_lower]

    # Fuzzy match -- require significant overlap
    best_match = None
    best_score = 0
    for key, value in job_company_map.items():
        if company_lower in key or key in company_lower:
            score = min(len(company_lower), len(key)) / max(len(company_lower), len(key))
            # Require at least 70% overlap AND minimum 3 chars to avoid false positives
            if score > best_score and score >= 0.7 and min(len(company_lower), len(key)) >= 3:
                best_score = score
                best_match = value

    if best_match:
        return best_match
    return None, None


def _extract_body(msg: dict) -> str:
    """Extract plain text body from a Gmail message (up to 2000 chars)."""
    payload = msg.get("payload", {})

    # Try to get full body from parts first (more complete)
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            decoded = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            return decoded[:2000]

    # Fallback to direct body
    if "body" in payload and payload["body"].get("data"):
        decoded = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        return decoded[:2000]

    # Last resort: snippet
    return msg.get("snippet", "")[:500]


def _notify(company: str, status: str, notes: str) -> None:
    """Send macOS notification for important status changes."""
    try:
        from plyer import notification
        titles = {
            "interview": f"Interview scheduled -- {company}!",
            "offer": f"Offer received -- {company}!",
        }
        notification.notify(
            title=titles.get(status, f"Status update -- {company}"),
            message=notes[:200] if notes else f"Status changed to {status}",
            timeout=15,
        )
    except Exception:
        pass  # Notification is best-effort
