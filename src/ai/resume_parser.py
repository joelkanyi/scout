"""AI-powered resume text to structured JSON parsing."""

from src.ai.anthropic_client import AICallError, call_json

MAX_INPUT_CHARS = 8000

SYSTEM_PROMPT = """\
You are a resume parser. Given raw text extracted from a resume PDF, produce a structured JSON object.

OUTPUT FORMAT (return ONLY this JSON, no markdown):
{
  "personal": {
    "name": "Full Name",
    "email": "email@example.com",
    "phone": "+1 234 567 8900",
    "location": "City, Country",
    "linkedin": "https://linkedin.com/in/username",
    "github": "https://github.com/username",
    "website": ""
  },
  "summary": "2-3 sentence professional summary.",
  "experience": [
    {
      "role": "Job Title",
      "company": "Company Name",
      "location": "City, Country",
      "start_date": "YYYY-MM",
      "end_date": "YYYY-MM or present",
      "bullets": [
        {"text": "Achievement or responsibility", "tags": ["relevant", "tech"]}
      ]
    }
  ],
  "skills": ["Skill1", "Skill2", "Skill3"],
  "education": [
    {"degree": "B.S. Computer Science", "institution": "University Name", "year": "2020"}
  ],
  "projects": [
    {"name": "Project Name", "description": "One sentence description.", "tags": ["tech1"]}
  ],
  "certifications": ["Cert Name (Year)"],
  "languages": ["English", "Spanish"]
}

RULES:
1. Extract ONLY information present in the resume text. Never fabricate.
2. If a field is missing from the text, use an empty string or empty array.
3. For experience bullets, each should start with a past-tense action verb.
4. Tags should be relevant technologies or skills mentioned in that bullet.
5. Skills should be a flat list of individual technologies/tools.
6. Dates should be YYYY-MM format where possible. Use "present" for current roles.
7. Return valid JSON only. No markdown fences, no explanation."""


def parse_resume_text(raw_text: str) -> dict:
    """Parse raw resume text into structured JSON.

    Returns a dict with the parsed resume and optional warnings.
    """
    truncated = raw_text[:MAX_INPUT_CHARS]

    try:
        parsed = call_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"Parse this resume:\n\n{truncated}",
            max_tokens=4096,
        )
    except AICallError as e:
        return {"error": str(e), "raw_text": truncated}
    except Exception as e:  # network, rate limit, provider-specific errors, JSON issues
        return {"error": f"Could not parse the resume with AI: {e}", "raw_text": truncated}

    if not isinstance(parsed, dict):
        return {"error": "The AI returned an unexpected format. Try again or enter your resume manually.", "raw_text": truncated}

    # Structural validation
    warnings = []
    if not parsed.get("personal", {}).get("name"):
        warnings.append("Could not extract name")
    if not parsed.get("experience"):
        warnings.append("No work experience found")
    if not parsed.get("skills"):
        warnings.append("No skills found")

    result = {"parsed": parsed}
    if warnings:
        result["warnings"] = warnings
    return result
