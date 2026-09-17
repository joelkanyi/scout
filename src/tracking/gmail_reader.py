"""Gmail API integration -- OAuth setup, inbox scanning, status updates with timeline events."""

import base64
from datetime import UTC, datetime, timedelta

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
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
]


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
        # Get company names from applications
        apps = session.query(Application).filter(Application.is_dry_run.is_(False)).all()
        applied_job_ids = {a.job_id: a for a in apps}

        companies = []
        job_company_map: dict[str, tuple[str, Application]] = {}

        for job_id, app in applied_job_ids.items():
            job = session.get(Job, job_id)
            if job:
                companies.append(job.company)
                job_company_map[job.company.lower().strip()] = (job_id, app)

        if not companies:
            console.print("  [dim]No applications to track yet.[/dim]")
            return 0, 0

        # Build search query -- ATS domains + company names
        domain_queries = " OR ".join(f"from:{d}" for d in ATS_DOMAINS)
        company_queries = " OR ".join(f'"{c}"' for c in companies[:20])
        query = f"({domain_queries} OR {company_queries}) newer_than:7d"

        results = service.users().messages().list(
            userId="me", q=query, maxResults=50
        ).execute()

        messages = results.get("messages", [])
        console.print(f"  Found {len(messages)} potential emails")

        for msg_meta in messages:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_meta["id"], format="full"
                ).execute()

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

                # Find matching application -- exact then fuzzy
                job_id, app = _match_company(company, job_company_map)
                if not job_id or not app:
                    continue

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
                    )
                    record_event(
                        app.id, job_id, "status_changed",
                        {"from": old_status, "to": status, "trigger": "email"},
                        source="email",
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
            )
            ghosted_count += 1

    return ghosted_count


def _match_company(
    company: str,
    job_company_map: dict[str, tuple[str, Application]],
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
