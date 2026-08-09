#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI JOB APPLICATION INTELLIGENCE
================================
MASTER RESUME PARSER

Purpose:
    Read the master CV from resume_data/
    and create a structured master_resume.json.

Important design rules:
    1. Never invent CV information.
    2. Preserve the original extracted text.
    3. Education is LOCKED.
    4. Experience is LOCKED.
    5. Certifications/training are LOCKED.
    6. Project functionality is LOCKED.
    7. Project wording may later be customized.
    8. Virtual job simulations are LOCKED.
    9. The generated JSON becomes the source of truth.

This script DOES NOT customize the resume yet.

Pipeline:

    Master CV
        ↓
    resume_parser.py
        ↓
    master_resume.json
        ↓
    Future resume_builder.py
        ↓
    Job-specific resume
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF


# ============================================================================
# PROJECT PATHS
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent

RESUME_DATA_DIR = BASE_DIR / "resume_data"

OUTPUT_FILE = RESUME_DATA_DIR / "master_resume.json"

RAW_TEXT_FILE = RESUME_DATA_DIR / "master_resume_raw.txt"


# ============================================================================
# CV SECTION DEFINITIONS
# ============================================================================

SECTION_ALIASES = {
    "summary": {
        "professional summary",
        "summary",
        "profile",
        "professional profile",
        "career objective",
        "objective",
    },

    "skills": {
        "skills",
        "technical skills",
        "technical skills and tools",
        "technical skills & tools",
        "core skills",
        "key skills",
    },

    "projects": {
        "projects",
        "key projects",
        "project experience",
        "academic projects",
        "personal projects",
    },

    "virtual_job_simulations": {
        "virtual job simulations",
        "virtual job simulation",
        "job simulations",
    },

    "training": {
        "training",
        "professional training",
        "technical training",
    },

    "education": {
        "education",
        "academic background",
        "educational qualification",
        "qualifications",
    },

    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment",
    },

    "certifications": {
        "certifications",
        "certificates",
        "certification",
        "licenses & certifications",
        "licenses and certifications",
    },

    "achievements": {
        "achievements",
        "accomplishments",
        "awards",
        "honors",
    },
}


# ============================================================================
# LOCKING RULES
# ============================================================================

LOCKED_SECTIONS = [
    "personal",
    "education",
    "experience",
    "certifications",
    "training",
    "virtual_job_simulations",
    "project_facts",
]

EDITABLE_SECTIONS = [
    "summary",
    "skills_order",
    "project_wording",
]


# ============================================================================
# TEXT UTILITIES
# ============================================================================

def clean_text(text: str) -> str:
    """
    Clean PDF text without changing its actual meaning.
    """

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Normalize spaces/tabs
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def normalize_heading(text: str) -> str:
    """
    Normalize a possible section heading.
    """

    value = text.strip().lower()

    value = value.replace(":", "")
    value = value.replace("–", "-")
    value = value.replace("—", "-")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def detect_section(line: str) -> Optional[str]:
    """
    Return the internal section name if the line is a known heading.
    """

    normalized = normalize_heading(line)

    for section_name, aliases in SECTION_ALIASES.items():

        if normalized in aliases:
            return section_name

    return None


def clean_bullet(line: str) -> str:
    """
    Remove bullet symbols only.
    Do not rewrite the actual content.
    """

    line = line.strip()

    line = re.sub(
        r"^[•●▪◦■◆★➢➤*]+\s*",
        "",
        line,
    )

    return line.strip()


def lines_to_list(text: str) -> List[str]:
    """
    Convert section text into a list while preserving wording.
    """

    if not text:
        return []

    result = []

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        line = clean_bullet(line)

        if line:
            result.append(line)

    return result


# ============================================================================
# PDF READING
# ============================================================================

def find_master_resume() -> Path:
    """
    Automatically find the user's master PDF inside resume_data/.

    This avoids hard-coding:
        Analyst_Shil 2.0.pdf
    or
        Analyst_Shil 2.o.pdf

    The first PDF found is used.
    """

    if not RESUME_DATA_DIR.exists():

        raise FileNotFoundError(
            f"Resume folder does not exist:\n{RESUME_DATA_DIR}"
        )

    pdf_files = sorted(
        RESUME_DATA_DIR.glob("*.pdf"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not pdf_files:

        raise FileNotFoundError(
            "\nNo PDF resume found in:\n"
            f"{RESUME_DATA_DIR}\n\n"
            "Put your latest CV PDF inside the resume_data folder."
        )

    # Most recently modified PDF = current master CV
    return pdf_files[0]


def extract_pdf_text(pdf_path: Path) -> str:
    """
    Extract text from every page of the PDF.
    """

    print(f"\nReading CV:")
    print(f"  {pdf_path.name}")

    document = fitz.open(pdf_path)

    pages = []

    try:

        for page_number, page in enumerate(document, start=1):

            text = page.get_text("text")

            if text.strip():

                pages.append(
                    f"--- PAGE {page_number} ---\n{text.strip()}"
                )

    finally:

        document.close()

    full_text = "\n\n".join(pages)

    return clean_text(full_text)


# ============================================================================
# SECTION PARSER
# ============================================================================

def split_into_sections(text: str) -> Dict[str, str]:
    """
    Split the CV into known sections.

    Unknown content is preserved under 'other'.
    """

    section_names = [
        "header",
        "summary",
        "skills",
        "projects",
        "virtual_job_simulations",
        "training",
        "education",
        "experience",
        "certifications",
        "achievements",
        "other",
    ]

    sections: Dict[str, List[str]] = {
        name: []
        for name in section_names
    }

    current_section = "header"

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        # Ignore our page marker
        if line.startswith("--- PAGE "):
            continue

        detected = detect_section(line)

        if detected:

            current_section = detected

            continue

        sections[current_section].append(line)

    return {
        key: "\n".join(value).strip()
        for key, value in sections.items()
    }


# ============================================================================
# PERSONAL INFORMATION
# ============================================================================

def extract_email(text: str) -> str:

    match = re.search(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        text,
    )

    return match.group(0) if match else ""


def extract_phone(text: str) -> str:

    patterns = [
        r"\+91[\s-]?\d{5}[\s-]?\d{5}",
        r"\+91[\s-]?\d{10}",
        r"\b\d{10}\b",
    ]

    for pattern in patterns:

        match = re.search(pattern, text)

        if match:
            return match.group(0)

    return ""


def extract_linkedin(text: str) -> str:

    match = re.search(
        r"(?:https?://)?(?:www\.)?linkedin\.com/[^\s|]+",
        text,
        re.IGNORECASE,
    )

    if not match:
        return ""

    return match.group(0).rstrip(".,)")


def extract_github(text: str) -> str:

    match = re.search(
        r"(?:https?://)?(?:www\.)?github\.com/[^\s|]+",
        text,
        re.IGNORECASE,
    )

    if not match:
        return ""

    return match.group(0).rstrip(".,)")


def extract_name(header: str) -> str:
    """
    Usually the first meaningful line in the header is the name.
    """

    for line in header.splitlines():

        value = line.strip()

        if not value:
            continue

        # Skip page markers
        if value.startswith("--- PAGE"):
            continue

        # Skip obvious contact-only lines
        if "@" in value:
            continue

        if re.search(r"\d{7,}", value):
            continue

        if "linkedin.com" in value.lower():
            continue

        if "github.com" in value.lower():
            continue

        return value

    return ""


def extract_location(header: str) -> str:

    for line in header.splitlines():

        line = line.strip()

        if not line:
            continue

        if "Pune" in line:

            match = re.search(
                r"(Pune[^|]*)",
                line,
                re.IGNORECASE,
            )

            if match:
                return match.group(1).strip()

    return ""


# ============================================================================
# SKILLS PARSER
# ============================================================================

def parse_skills(text: str) -> Dict[str, List[str]]:
    """
    Preserve the skill categories from the CV.

    Example:

    Data Analysis and Visualisation:
        Power BI...
        Excel...
    """

    categories: Dict[str, List[str]] = {}

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        if ":" in line:

            category, values = line.split(":", 1)

            category = category.strip()
            values = values.strip()

            if category and values:

                categories[category] = [
                    item.strip()
                    for item in re.split(
                        r",|;",
                        values
                    )
                    if item.strip()
                ]

        else:

            # Preserve uncategorized skill lines
            categories.setdefault(
                "Other",
                []
            ).append(line)

    return categories


# ============================================================================
# PROJECT PARSER
# ============================================================================

def parse_projects(text: str) -> List[Dict[str, object]]:
    """
    Parse the user's current three projects.

    The PDF extraction may place the project title and first bullet
    on the same line, so this parser recognizes the actual project
    titles found in the CV.

    The content is preserved rather than rewritten.
    """

    known_projects = [
        "Madhav E-Commerce Sales Dashboard",
        "Supply Chain Intelligence Hub",
        "Supply Chain Digital Twin Simulation",
    ]

    projects = []

    for index, project_name in enumerate(known_projects):

        start = text.find(project_name)

        if start == -1:
            continue

        if index + 1 < len(known_projects):

            next_project = known_projects[index + 1]

            end = text.find(next_project, start + len(project_name))

        else:

            # Projects section ends at Virtual Job Simulations
            end = text.find(
                "VIRTUAL JOB SIMULATIONS",
                start + len(project_name),
            )

        if end == -1:
            block = text[start:]
        else:
            block = text[start:end]

        block = block.strip()

        # Remove project name from beginning
        remainder = block[len(project_name):].strip()

        technologies = ""

        # Your CV uses:
        # Project Name Power BI + PostgreSQL
        # Project Name Python (Pandas) + Power BI
        # etc.
        first_bullet = remainder.find("•")

        if first_bullet != -1:

            tech_part = remainder[:first_bullet].strip()

            if tech_part:
                technologies = tech_part

            bullet_text = remainder[first_bullet:]

        else:

            bullet_text = remainder

        bullets = []

        # Split PDF bullet points
        for bullet in re.split(r"•", bullet_text):

            bullet = bullet.strip()

            if bullet:
                bullets.append(bullet)

        projects.append(
            {
                "name": project_name,
                "technologies": technologies,
                "original_text": block,
                "facts": bullets,
                "customization_allowed": True,
                "functionality_locked": True,
            }
        )

    return projects


# ============================================================================
# VIRTUAL JOB SIMULATION PARSER
# ============================================================================

def parse_virtual_job_simulations(
    text: str,
) -> List[Dict[str, object]]:

    simulations = []

    known_simulations = [
        "Data Analytics Job Simulation, Deloitte (Forage)",
        "Data Visualisation Job Simulation, Tata (Forage)",
    ]

    for index, name in enumerate(known_simulations):

        start = text.find(name)

        if start == -1:
            continue

        if index + 1 < len(known_simulations):

            next_name = known_simulations[index + 1]

            end = text.find(
                next_name,
                start + len(name),
            )

        else:

            end = text.find(
                "TRAINING",
                start + len(name),
            )

        if end == -1:
            block = text[start:]
        else:
            block = text[start:end]

        block = block.strip()

        simulations.append(
            {
                "name": name,
                "original_text": block,
                "facts": lines_to_list(block),
                "locked": True,
            }
        )

    return simulations


# ============================================================================
# EDUCATION PARSER
# ============================================================================

def parse_education(text: str) -> List[str]:

    return lines_to_list(text)


# ============================================================================
# TRAINING PARSER
# ============================================================================

def parse_training(text: str) -> List[str]:

    return lines_to_list(text)


# ============================================================================
# CERTIFICATION PARSER
# ============================================================================

def parse_certifications(text: str) -> List[str]:

    if not text:
        return []

    return lines_to_list(text)


# ============================================================================
# EXPERIENCE PARSER
# ============================================================================

def parse_experience(text: str) -> List[str]:

    if not text:
        return []

    return lines_to_list(text)


# ============================================================================
# HASHING / FACT PROTECTION
# ============================================================================

def make_hash(text: str) -> str:
    """
    Create SHA-256 hash of original content.

    Later resume_builder.py can use this to verify that
    protected information has not been changed.
    """

    normalized = clean_text(text)

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def create_protection_record(
    sections: Dict[str, str],
    projects: List[Dict[str, object]],
) -> Dict[str, object]:

    project_facts = []

    for project in projects:

        project_facts.append(
            {
                "name": project["name"],
                "facts": project["facts"],
                "facts_hash": make_hash(
                    "\n".join(
                        project["facts"]
                    )
                ),
            }
        )

    return {
        "locked_sections": LOCKED_SECTIONS,

        "locked_hashes": {
            "education": make_hash(
                sections["education"]
            ),

            "experience": make_hash(
                sections["experience"]
            ),

            "certifications": make_hash(
                sections["certifications"]
            ),

            "training": make_hash(
                sections["training"]
            ),

            "virtual_job_simulations": make_hash(
                sections["virtual_job_simulations"]
            ),
        },

        "project_facts": project_facts,

        "rules": {
            "never_invent_information": True,
            "never_change_education": True,
            "never_change_experience": True,
            "never_change_certifications": True,
            "never_change_training": True,
            "never_change_simulation_facts": True,
            "never_change_project_functionality": True,
            "project_wording_can_change": True,
            "summary_can_change": True,
            "skill_order_can_change": True,
        },
    }


# ============================================================================
# MASTER PROFILE CREATION
# ============================================================================

def build_master_profile(
    pdf_path: Path,
    raw_text: str,
    sections: Dict[str, str],
) -> Dict[str, object]:

    projects = parse_projects(
        sections["projects"]
    )

    simulations = parse_virtual_job_simulations(
        sections["virtual_job_simulations"]
    )

    profile = {
        "metadata": {
            "profile_version": "1.0",
            "source_file": pdf_path.name,
            "source_path": str(pdf_path),
            "parser": "resume_parser.py",
            "purpose": (
                "Master source of truth for "
                "job-specific resume generation."
            ),
        },

        "personal": {
            "name": extract_name(
                sections["header"]
            ),

            "location": extract_location(
                sections["header"]
            ),

            "phone": extract_phone(
                sections["header"]
            ),

            "email": extract_email(
                sections["header"]
            ),

            "linkedin": extract_linkedin(
                sections["header"]
            ),

            "github": extract_github(
                sections["header"]
            ),
        },

        "availability": {
            "original_text": (
                "Available to join immediately | "
                "Open to full-time and contract roles"
            )
        },

        "summary": {
            "original_text": sections["summary"],
            "customization_allowed": True,
        },

        "skills": {
            "categories": parse_skills(
                sections["skills"]
            ),

            "original_text": sections["skills"],

            "reordering_allowed": True,

            "skill_invention_allowed": False,
        },

        "projects": projects,

        "virtual_job_simulations": simulations,

        "training": {
            "original_text": sections["training"],
            "items": parse_training(
                sections["training"]
            ),
            "locked": True,
        },

        "education": {
            "original_text": sections["education"],
            "items": parse_education(
                sections["education"]
            ),
            "locked": True,
        },

        "experience": {
            "original_text": sections["experience"],
            "items": parse_experience(
                sections["experience"]
            ),
            "locked": True,
        },

        "certifications": {
            "original_text": sections["certifications"],
            "items": parse_certifications(
                sections["certifications"]
            ),
            "locked": True,
        },

        "achievements": {
            "original_text": sections["achievements"],
            "items": lines_to_list(
                sections["achievements"]
            ),
            "locked": True,
        },

        "raw_sections": sections,

        "raw_text": raw_text,

        "protection": create_protection_record(
            sections,
            projects,
        ),

        "customization_policy": {
            "allowed": [
                "Rewrite professional summary.",
                "Reorder existing skills according to job relevance.",
                "Rewrite project bullet wording.",
                "Emphasize existing project capabilities relevant to the job.",
                "Change keyword placement.",
                "Improve ATS terminology when supported by the master CV.",
            ],

            "forbidden": [
                "Invent work experience.",
                "Invent internships.",
                "Invent certifications.",
                "Invent education.",
                "Invent project functionality.",
                "Invent technologies.",
                "Invent metrics.",
                "Change project results.",
                "Change project names.",
                "Change dates.",
                "Change degree.",
                "Change university.",
                "Change training facts.",
                "Change virtual job simulation facts.",
            ],
        },
    }

    return profile


# ============================================================================
# SAVE FUNCTIONS
# ============================================================================

def save_json(
    profile: Dict[str, object],
    output_path: Path,
) -> None:

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            profile,
            file,
            indent=2,
            ensure_ascii=False,
        )


def save_raw_text(
    text: str,
    output_path: Path,
) -> None:

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(text)


# ============================================================================
# VALIDATION
# ============================================================================

def validate_profile(
    profile: Dict[str, object]
) -> List[str]:

    errors = []

    personal = profile.get(
        "personal",
        {}
    )

    if not personal.get("name"):
        errors.append(
            "Could not detect candidate name."
        )

    if not personal.get("email"):
        errors.append(
            "Could not detect email address."
        )

    if not personal.get("phone"):
        errors.append(
            "Could not detect phone number."
        )

    if not profile.get("projects"):
        errors.append(
            "No projects were detected."
        )

    education = profile.get(
        "education",
        {}
    )

    if not education.get("items"):
        errors.append(
            "No education information detected."
        )

    skills = profile.get(
        "skills",
        {}
    )

    if not skills.get("categories"):
        errors.append(
            "No skills detected."
        )

    return errors


# ============================================================================
# PRINT PROFILE SUMMARY
# ============================================================================

def print_profile_summary(
    profile: Dict[str, object]
) -> None:

    print("\n")
    print("=" * 70)
    print("MASTER RESUME PROFILE")
    print("=" * 70)

    personal = profile["personal"]

    print(
        f"\nName       : {personal['name']}"
    )

    print(
        f"Location   : {personal['location']}"
    )

    print(
        f"Email      : {personal['email']}"
    )

    print(
        f"Phone      : {personal['phone']}"
    )

    print(
        f"LinkedIn   : {personal['linkedin']}"
    )

    print(
        f"GitHub     : {personal['github']}"
    )

    print("\nSkills categories:")

    for category, skills in profile[
        "skills"
    ]["categories"].items():

        print(
            f"  • {category}: "
            f"{len(skills)} items"
        )

    print(
        f"\nProjects detected: "
        f"{len(profile['projects'])}"
    )

    for project in profile["projects"]:

        print(
            f"  • {project['name']}"
        )

    print(
        "\nVirtual job simulations: "
        f"{len(profile['virtual_job_simulations'])}"
    )

    for simulation in profile[
        "virtual_job_simulations"
    ]:

        print(
            f"  • {simulation['name']}"
        )

    education = profile["education"]["items"]

    print(
        f"\nEducation lines: "
        f"{len(education)}"
    )

    training = profile["training"]["items"]

    print(
        f"Training lines: "
        f"{len(training)}"
    )

    print(
        "\nLocked sections:"
    )

    for section in LOCKED_SECTIONS:

        print(
            f"  🔒 {section}"
        )

    print(
        "\nEditable later:"
    )

    for section in EDITABLE_SECTIONS:

        print(
            f"  ✏ {section}"
        )

    print("=" * 70)


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:

    print("=" * 70)
    print("AI JOB APPLICATION INTELLIGENCE")
    print("MASTER RESUME PARSER")
    print("=" * 70)

    try:

        # ------------------------------------------------------------------
        # 1. Find CV
        # ------------------------------------------------------------------

        print("\n[1/6] Finding master CV...")

        pdf_path = find_master_resume()

        print(
            f"       Found: {pdf_path.name}"
        )

        # ------------------------------------------------------------------
        # 2. Read PDF
        # ------------------------------------------------------------------

        print("\n[2/6] Extracting PDF text...")

        raw_text = extract_pdf_text(
            pdf_path
        )

        if not raw_text:

            print(
                "\nERROR: No text could be extracted."
            )

            print(
                "Your PDF may be image/scanned based."
            )

            return 1

        print(
            f"       Characters extracted: "
            f"{len(raw_text):,}"
        )

        # ------------------------------------------------------------------
        # 3. Split sections
        # ------------------------------------------------------------------

        print(
            "\n[3/6] Detecting CV sections..."
        )

        sections = split_into_sections(
            raw_text
        )

        for name, content in sections.items():

            if content:

                print(
                    f"       ✓ {name}"
                )

        # ------------------------------------------------------------------
        # 4. Build structured profile
        # ------------------------------------------------------------------

        print(
            "\n[4/6] Building master profile..."
        )

        profile = build_master_profile(
            pdf_path,
            raw_text,
            sections,
        )

        # ------------------------------------------------------------------
        # 5. Validate
        # ------------------------------------------------------------------

        print(
            "\n[5/6] Validating extracted profile..."
        )

        errors = validate_profile(
            profile
        )

        if errors:

            print(
                "\nWARNING:"
            )

            for error in errors:

                print(
                    f"  ⚠ {error}"
                )

        else:

            print(
                "       ✓ Basic validation passed."
            )

        # ------------------------------------------------------------------
        # 6. Save
        # ------------------------------------------------------------------

        print(
            "\n[6/6] Saving master profile..."
        )

        RESUME_DATA_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        save_json(
            profile,
            OUTPUT_FILE,
        )

        save_raw_text(
            raw_text,
            RAW_TEXT_FILE,
        )

        # ------------------------------------------------------------------
        # Print result
        # ------------------------------------------------------------------

        print_profile_summary(
            profile
        )

        print(
            "\nFILES CREATED"
        )

        print(
            f"  ✓ {OUTPUT_FILE}"
        )

        print(
            f"  ✓ {RAW_TEXT_FILE}"
        )

        print(
            "\nSTATUS: SUCCESS"
        )

        print(
            "\nIMPORTANT:"
        )

        print(
            "The original CV has NOT been modified."
        )

        print(
            "The JSON is now the master source of truth."
        )

        return 0

    except FileNotFoundError as error:

        print(
            f"\nERROR: {error}"
        )

        return 1

    except Exception as error:

        print(
            "\nUNEXPECTED ERROR:"
        )

        print(
            f"{type(error).__name__}: {error}"
        )

        return 1


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )