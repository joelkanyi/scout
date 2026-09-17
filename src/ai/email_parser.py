"""Email status parsing -- Haiku extracts company, status, interview datetime from emails."""

from rich.console import Console

from src.ai.anthropic_client import AICallError, call_json, wrap_user_input

console = Console()

SYSTEM_PROMPT = "You parse job application emails. Return ONLY valid JSON."

USER_PROMPT_TEMPLATE = """Subject: {subject}
Body (first 600 chars): {body}
Companies I applied to: {companies}

Return exactly this JSON:
{{"is_job_related":true,"company":"","role":"","status":"applied","interview_datetime":null,"notes":""}}

Rules:
- The email may be in ANY language (German, French, Spanish, Italian, Dutch, etc.).
  Interpret is_job_related and status from meaning, not keywords, whatever the language.
  Common rejections: "leider" / "Absage" (DE), "malheureusement" (FR), "lamentamos" (ES),
  "purtroppo" (IT) usually mean rejected. Translate mentally before deciding.
- is_job_related: true if this email is about a job application (a reply from a company or ATS)
- company: the company name from the list above, or extracted from the email
- role: the job title mentioned, or "" if none
- status: one of "applied", "under_review", "interview", "rejected", "offer", "ghosted"
- interview_datetime: ISO format if an interview is scheduled, null otherwise
- notes: brief summary of what the email says, in English"""

VALID_STATUSES = {"applied", "under_review", "interview", "rejected", "offer", "ghosted"}


def parse_email(subject: str, body: str, companies: list[str]) -> dict:
    """Parse an email to extract job application status.

    Returns a dict with validated fields. On AI failure, returns non-job-related result.
    """
    user_prompt = USER_PROMPT_TEMPLATE.format(
        subject=wrap_user_input("email_subject", subject),
        body=wrap_user_input("email_body", body[:600]),
        companies=", ".join(companies[:100]),
    )

    try:
        result = call_json(SYSTEM_PROMPT, user_prompt)
    except AICallError as e:
        console.print(f"  [dim]Email parse failed: {e}[/dim]")
        return {"is_job_related": False, "company": "", "role": "", "status": "", "interview_datetime": None, "notes": ""}

    # Validate is_job_related is actually boolean
    is_related = result.get("is_job_related", False)
    if not isinstance(is_related, bool):
        is_related = str(is_related).lower() == "true"

    # Validate status is a known value
    status = result.get("status", "")
    if status not in VALID_STATUSES:
        status = ""

    return {
        "is_job_related": is_related,
        "company": str(result.get("company", "")),
        "role": str(result.get("role", "")),
        "status": status,
        "interview_datetime": result.get("interview_datetime"),
        "notes": str(result.get("notes", "")),
    }
