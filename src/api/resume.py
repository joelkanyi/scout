"""Resume API routes."""

import json
import re

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.database import Job, Resume, managed_session
from src.paths import RESUME_DIR

router = APIRouter(tags=["resume"])

MASTER_PATH = RESUME_DIR / "master.json"
OUTPUT_DIR = RESUME_DIR / "generated"


def _resume_filename(job: Job | None, ext: str = "pdf") -> str:
    """Build a descriptive download filename from job metadata."""
    if not job:
        return f"Resume.{ext}"
    company = re.sub(r"[^\w\s-]", "", job.company or "").strip().replace(" ", "_")
    title = re.sub(r"[^\w\s-]", "", job.title or "").strip().replace(" ", "_")
    # Read name from master resume if available
    name = "Resume"
    try:
        master = json.loads(MASTER_PATH.read_text())
        full_name = master.get("personal", {}).get("name", "")
        if full_name:
            name = re.sub(r"[^\w\s-]", "", full_name).strip().replace(" ", "_")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return f"{name}_{title}_{company}_Resume.{ext}"


@router.get("/resume/master")
def get_master_resume():
    if not MASTER_PATH.exists():
        raise HTTPException(status_code=404, detail="Master resume not found")
    try:
        return json.loads(MASTER_PATH.read_text())
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Master resume JSON is malformed")


@router.post("/resume/upload")
async def upload_resume_pdf(file: UploadFile):
    """Upload a PDF resume, extract text, and parse with AI. Returns parsed JSON for review."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    # Check API key is configured
    from src.settings import load_settings
    settings = load_settings()
    if not settings.effective_provider:
        raise HTTPException(
            status_code=400,
            detail="Configure your AI provider in Settings before uploading a resume",
        )

    # Extract text
    try:
        from src.resume.pdf_parser import PDFExtractionError, extract_text_from_pdf
        raw_text = extract_text_from_pdf(contents)
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF support is not installed on the server ({e}). Run: pip install pymupdf",
        )
    except PDFExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read the PDF: {e}")

    # AI parse
    from src.ai.resume_parser import parse_resume_text
    result = parse_resume_text(raw_text)

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    return result


@router.post("/resume/master")
def save_master_resume(data: dict):
    """Save reviewed/edited resume data as master.json."""
    if not data.get("personal") or not data.get("experience"):
        raise HTTPException(
            status_code=400,
            detail="Resume must include personal info and at least one experience entry",
        )
    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return {"status": "saved"}


@router.get("/resume/gap-analysis")
def get_gap_analysis():
    """Market-wide gap analysis: which in-demand skills are missing from your resume."""
    if not MASTER_PATH.exists():
        raise HTTPException(status_code=404, detail="Upload your resume first")
    master = json.loads(MASTER_PATH.read_text())

    from src.resume.gap_analysis import market_gap_report
    return market_gap_report(master)


@router.get("/resume/gap-analysis/{job_id}")
def get_job_gap(job_id: str):
    """Per-job ATS gap report: which JD keywords are missing from your resume."""
    if not MASTER_PATH.exists():
        raise HTTPException(status_code=404, detail="Upload your resume first")
    master = json.loads(MASTER_PATH.read_text())

    with managed_session() as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        from src.resume.gap_analysis import job_gap_report
        return job_gap_report(master, job)


@router.post("/resume/enhance")
def enhance_master_resume():
    """AI-powered resume enhancement suggestions."""
    if not MASTER_PATH.exists():
        raise HTTPException(status_code=404, detail="Upload your resume first")

    from src.settings import load_settings
    settings = load_settings()
    if not settings.effective_provider:
        raise HTTPException(status_code=400, detail="Configure your AI provider in Settings first")

    master = json.loads(MASTER_PATH.read_text())

    # Get missing skills from gap analysis to feed into the enhancer
    from src.resume.gap_analysis import market_gap_report
    gap = market_gap_report(master)
    missing_skills = [m["keyword"] for m in gap.get("missing_high_demand", [])[:15]]

    # Get job titles from preferences
    from src.preferences import load_preferences
    prefs = load_preferences()

    from src.ai.resume_enhancer import enhance_resume
    result = enhance_resume(master, missing_skills, prefs.job_titles)

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    return result


@router.post("/resume/apply-suggestions")
def apply_suggestions(data: dict):
    """Apply accepted enhancement suggestions to the master resume.

    Expects:
    {
        "add_skills": ["Docker", "Kubernetes"],
        "bullet_rewrites": [
            {"experience_index": 0, "bullet_index": 1, "text": "new bullet text"}
        ],
        "new_summary": "optional new summary"
    }
    """
    if not MASTER_PATH.exists():
        raise HTTPException(status_code=404, detail="Master resume not found")

    master = json.loads(MASTER_PATH.read_text())

    # Apply skill additions
    add_skills = data.get("add_skills", [])
    if add_skills:
        skills = master.get("skills", [])
        if isinstance(skills, list):
            existing = {s.lower() for s in skills}
            for s in add_skills:
                if s.lower() not in existing:
                    skills.append(s)
            master["skills"] = skills
        elif isinstance(skills, dict):
            # Add to first category or create "Additional" category
            categories = list(skills.keys())
            target_cat = categories[0] if categories else "Additional Skills"
            existing = set()
            for items in skills.values():
                existing.update(s.lower() for s in items)
            for s in add_skills:
                if s.lower() not in existing:
                    skills.setdefault(target_cat, []).append(s)

    # Apply bullet rewrites
    for rewrite in data.get("bullet_rewrites", []):
        exp_idx = rewrite.get("experience_index", -1)
        bul_idx = rewrite.get("bullet_index", -1)
        new_text = rewrite.get("text", "")
        experience = master.get("experience", [])
        if 0 <= exp_idx < len(experience):
            bullets = experience[exp_idx].get("bullets", [])
            if 0 <= bul_idx < len(bullets):
                if isinstance(bullets[bul_idx], dict):
                    bullets[bul_idx]["text"] = new_text
                else:
                    bullets[bul_idx] = new_text

    # Apply summary rewrite
    if data.get("new_summary"):
        master["summary"] = data["new_summary"]

    MASTER_PATH.write_text(json.dumps(master, indent=2, ensure_ascii=False))
    return {"status": "saved", "resume": master}


@router.post("/resume/tailor/{job_id}")
def tailor_resume_for_job(job_id: str):
    with managed_session() as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        try:
            ats_keywords = json.loads(job.ats_keywords) if job.ats_keywords else []
        except (json.JSONDecodeError, TypeError):
            ats_keywords = []
        jd_text = job.jd_text or ""
        title = job.title
        company = job.company
        research_notes = job.research_notes or ""

    from src.ai.tailor import tailor_resume
    tailored = tailor_resume(jd_text, ats_keywords, research_notes=research_notes)

    from src.resume.ats_scorer import score_resume, extract_resume_text
    tailored_text = extract_resume_text(tailored)
    score_breakdown = score_resume(tailored_text, jd_text, keywords=ats_keywords or None)
    score_val = score_breakdown["overall"]

    # Flatten skills for cover letter (handle both dict and list)
    skills_for_cover = tailored.get("skills", [])
    if isinstance(skills_for_cover, dict):
        flat_skills = []
        for items in skills_for_cover.values():
            flat_skills.extend(items)
        skills_for_cover = flat_skills

    from src.ai.cover_letter import generate_cover_letter
    cover_letter = generate_cover_letter(
        title=title, company=company, jd_text=jd_text,
        summary=tailored.get("summary", ""), skills=skills_for_cover,
        research_notes=research_notes,
    )

    from src.resume.builder import build_resume
    resume = build_resume(tailored, job_id, score_val)

    cover_path = OUTPUT_DIR / job_id / "cover_letter.txt"
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_text(cover_letter)

    return {
        "tailored": tailored,
        "ats_score": score_val,
        "score_breakdown": score_breakdown,
        "cover_letter": cover_letter,
        "pdf_path": resume.pdf_path,
        "docx_path": resume.docx_path,
    }


@router.get("/resume/{job_id}/pdf")
def get_resume_pdf(job_id: str, download: bool = False):
    pdf_path = OUTPUT_DIR / job_id / "resume.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found. Build resume first.")
    if download:
        with managed_session() as session:
            job = session.get(Job, job_id)
            filename = _resume_filename(job, "pdf")
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=filename,
        )
    # Inline display for preview (no Content-Disposition: attachment)
    return FileResponse(str(pdf_path), media_type="application/pdf")


@router.get("/resume/{job_id}/tailored")
def get_tailored_resume(job_id: str):
    with managed_session() as session:
        resume = session.query(Resume).filter(Resume.job_id == job_id).first()
        if not resume or not resume.tailored_json:
            raise HTTPException(status_code=404, detail="No tailored resume found")

        try:
            tailored = json.loads(resume.tailored_json)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=500, detail="Tailored resume data is corrupted")

        # Recompute the score breakdown from saved data so the UI gets the
        # full structured view, not just the cached overall float.
        score_breakdown = None
        job = session.get(Job, job_id)
        if job and job.jd_text:
            ai_keywords: list[str] = []
            if job.ats_keywords:
                try:
                    parsed = json.loads(job.ats_keywords)
                    if isinstance(parsed, list):
                        ai_keywords = [k for k in parsed if isinstance(k, str)]
                except (json.JSONDecodeError, TypeError):
                    pass
            from src.resume.ats_scorer import score_resume, extract_resume_text
            score_breakdown = score_resume(
                extract_resume_text(tailored),
                job.jd_text,
                keywords=ai_keywords or None,
            )

        # Load cover letter from disk if available
        cover_path = OUTPUT_DIR / job_id / "cover_letter.txt"
        cover_letter = cover_path.read_text() if cover_path.exists() else None

        return {
            "tailored": tailored,
            "ats_score": (score_breakdown or {}).get("overall", resume.ats_score),
            "score_breakdown": score_breakdown,
            "cover_letter": cover_letter,
            "pdf_path": resume.pdf_path,
            "docx_path": resume.docx_path,
        }
