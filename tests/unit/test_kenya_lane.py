"""Filter tests for the Kenya entry-level backend lane.

These pin the precision of the lane filter: real junior backend roles pass,
non-tech pollution and clearly-senior roles are rejected. If a case flips
after a deliberate change, update the case with intent — don't loosen the
filter just to make a role appear.
"""

from src.scrapers.backend_world import _is_backend_role, is_entry_level
from src.scrapers.kenya import (
    _fuzu_passes,
    _looks_like_dev_role,
    _looks_senior,
    _passes_lane,
    _split_title_company,
)


def _fuzu_job(title, company="Acme", category="Information technology, software development, data",
              seniority="basic", description=""):
    return {
        "title": title,
        "company_name": company,
        "description": description,
        "category": {"name": category},
        "seniority_level": {"key": seniority, "name": seniority},
    }


def test_split_title_company():
    assert _split_title_company("Software Engineer Intern at Pezesha") == (
        "Software Engineer Intern",
        "Pezesha",
    )
    # No " at " — company unknown, title preserved.
    assert _split_title_company("Junior Java Developer") == (
        "Junior Java Developer",
        "Unknown",
    )


def test_real_backend_roles_pass():
    assert _passes_lane("Junior Java Developer", "Zeraki")
    assert _passes_lane("Software Engineer Intern", "Pezesha")
    assert _passes_lane("Backend Developer", "Some Startup")
    assert _passes_lane("Spring Boot Developer", "Fintech Co")


def test_pollution_rejected():
    # "Java" the coffee house, not the language.
    assert not _passes_lane("Barista", "Java House")
    assert not _passes_lane("Team Member Manufacturing (Cook)", "Java House")
    assert not _passes_lane("Business Developer", "Insurance Co")
    # Front-end only is out of this backend lane.
    assert not _passes_lane("Frontend Software Developer", "Agency")


def test_seniority_rejected():
    assert _looks_senior("Senior Software Engineer")
    assert _looks_senior("Backend Team Lead")
    assert _looks_senior("Principal Java Developer")
    assert not _looks_senior("Junior Software Engineer")
    assert not _passes_lane("Senior Java Developer", "Bank")


def test_bare_developer_needs_tech_context():
    # A bare "developer" title only survives with tech context in the body.
    assert not _looks_like_dev_role("Developer", "")
    assert _looks_like_dev_role("Developer", "Build REST APIs in Spring Boot with PostgreSQL")


def test_fuzu_it_category_passes_even_non_dev_title():
    # Fuzu tags the category, so trust it for an entry IT role.
    assert _fuzu_passes(_fuzu_job("Graduate Trainee", seniority="basic"))
    assert _fuzu_passes(_fuzu_job("Software Engineer Intern"))


def test_fuzu_rejects_senior_and_wrong_category():
    assert not _fuzu_passes(_fuzu_job("Senior Software Engineer", seniority="senior"))
    # Non-IT category with a non-dev title is out.
    assert not _fuzu_passes(
        _fuzu_job("Finance Assistant", category="Accounting, finance, banking, insurance")
    )
    # Non-IT category but a genuine dev title still passes via the dev filter.
    assert _fuzu_passes(
        _fuzu_job("Java Developer", category="Telecommunications", seniority="basic")
    )


def test_fuzu_data_entry_rejected():
    # "data" is in Fuzu's IT category name; clerical data-entry is not software.
    assert not _fuzu_passes(_fuzu_job("Data Entry Officer", seniority="basic"))


def test_fuzu_mid_level_dropped_unless_title_says_junior():
    # Mid-level tag with a neutral title is above her level -> dropped.
    assert not _fuzu_passes(_fuzu_job("Software Engineer", seniority="middle"))
    # Mid tag but the title explicitly says intern/junior -> kept.
    assert _fuzu_passes(_fuzu_job("Junior Software Engineer", seniority="middle"))
    assert _fuzu_passes(_fuzu_job("Software Engineer Intern", seniority="middle"))


# ---------------------------------------------------------------------------
# Global backend lane
# ---------------------------------------------------------------------------


def test_world_backend_titles_pass():
    assert _is_backend_role("Backend Engineer")
    assert _is_backend_role("Java Software Engineer")
    assert _is_backend_role("Senior Golang Developer")  # all levels kept for learning
    assert _is_backend_role("Node.js Developer")


def test_world_non_backend_rejected():
    assert not _is_backend_role("Frontend Developer")
    assert not _is_backend_role("iOS Developer")
    assert not _is_backend_role("Data Analyst")
    assert not _is_backend_role("Sales Executive")
    # Bare "developer" needs backend context in the body.
    assert not _is_backend_role("Developer", "")
    assert _is_backend_role("Developer", "work on our Django REST API and PostgreSQL backend")


def test_world_entry_flag():
    assert is_entry_level("Junior Backend Engineer")
    assert is_entry_level("Software Engineer Intern")
    assert not is_entry_level("Senior Backend Engineer")
