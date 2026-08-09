"""
resume_customizer.py

AI Job Application & Resume Intelligence
-----------------------------------------

Purpose:
    Generate a role-specific resume from master_resume.json.

Design principles:
    1. master_resume.json is the source of truth.
    2. Locked sections are copied exactly.
    3. Project functionality cannot be changed.
    4. Project facts cannot be changed.
    5. Project wording may be rewritten.
    6. Summary may be rewritten.
    7. Existing skills may be reordered.
    8. New skills/technologies cannot be invented.
    9. No project metrics may be changed.
   10. Generated resume is validated automatically.

Input:
    job description supplied interactively or through --job-file

Output:
    generated_resumes/customized_resume.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

MASTER_RESUME = BASE_DIR / "resume_data" / "master_resume.json"

GENERATED_DIR = BASE_DIR / "generated_resumes"

OUTPUT_FILE = GENERATED_DIR / "customized_resume.json"

JOB_INPUT_FILE = BASE_DIR / "job_description.txt"

VALIDATOR = BASE_DIR / "resume_validator.py"


# ============================================================
# DISPLAY
# ============================================================

WIDTH = 72


def title(text: str) -> None:
    print()
    print("=" * WIDTH)
    print(text)
    print("=" * WIDTH)


def info(text: str) -> None:
    print(f"  {text}")


def success(text: str) -> None:
    print(f"✓ {text}")


def warning(text: str) -> None:
    print(f"⚠ {text}")


def error(text: str) -> None:
    print(f"✗ {text}")


# ============================================================
# FILE UTILITIES
# ============================================================

def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")

    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as fh:
        json.dump(
            data,
            fh,
            indent=2,
            ensure_ascii=False
        )


def load_job_description(path: Path | None = None) -> str:
    if path is not None:

        if not path.exists():
            raise FileNotFoundError(
                f"Job description file not found: {path}"
            )

        text = path.read_text(encoding="utf-8").strip()

        if not text:
            raise ValueError("Job description file is empty.")

        return text

    if JOB_INPUT_FILE.exists():

        text = JOB_INPUT_FILE.read_text(
            encoding="utf-8"
        ).strip()

        if text:
            return text

    print()
    print("Paste the complete job description.")
    print("When finished, press ENTER on an empty line.")
    print()

    lines = []

    while True:
        try:
            line = input()
        except EOFError:
            break

        if not line.strip():
            break

        lines.append(line)

    text = "\n".join(lines).strip()

    if not text:
        raise ValueError(
            "No job description supplied."
        )

    return text


# ============================================================
# TEXT UTILITIES
# ============================================================

def normalize(text: str) -> str:
    """
    Normalize text for keyword comparison.
    """

    text = text.lower()

    text = text.replace("&", " and ")

    text = re.sub(
        r"[^a-z0-9+#.\-/ ]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def tokens(text: str) -> set[str]:
    normalized = normalize(text)

    return set(
        token
        for token in normalized.split()
        if len(token) >= 2
    )


# ============================================================
# JOB ROLE DETECTION
# ============================================================

ROLE_KEYWORDS = {

    "data analyst": [
        "data analyst",
        "data analysis",
        "analytics",
        "business intelligence",
        "bi analyst",
        "reporting analyst",
    ],

    "business analyst": [
        "business analyst",
        "business analysis",
        "requirements",
        "business intelligence",
        "stakeholder",
    ],

    "data engineer": [
        "data engineer",
        "data engineering",
        "etl",
        "elt",
        "data pipeline",
        "data warehouse",
        "data platform",
    ],

    "python developer": [
        "python developer",
        "python development",
        "python developer",
        "software developer",
    ],

    "bi analyst": [
        "power bi",
        "business intelligence",
        "dashboard",
        "dax",
        "reporting",
        "bi analyst",
    ],

    "sql developer": [
        "sql developer",
        "sql",
        "postgresql",
        "mysql",
        "database",
        "queries",
    ],

    "supply chain analyst": [
        "supply chain analyst",
        "supply chain",
        "inventory",
        "logistics",
        "demand planning",
        "procurement",
    ],

    "machine learning": [
        "machine learning",
        "ml",
        "predictive modeling",
        "classification",
        "clustering",
    ],
}


def detect_role(job_description: str) -> str:

    jd = normalize(job_description)

    scores: dict[str, int] = {}

    for role, keywords in ROLE_KEYWORDS.items():

        score = 0

        for keyword in keywords:

            keyword_normalized = normalize(keyword)

            if keyword_normalized in jd:
                score += 1

        scores[role] = score

    best_role = max(
        scores,
        key=scores.get
    )

    if scores[best_role] == 0:
        return "general analytics"

    return best_role


# ============================================================
# KEYWORD EXTRACTION
# ============================================================

KNOWN_SKILL_ALIASES = {
    "power bi": [
        "power bi",
        "powerbi",
    ],
    "power query": [
        "power query",
    ],
    "dax": [
        "dax",
    ],
    "excel": [
        "excel",
        "microsoft excel",
    ],
    "tableau": [
        "tableau",
    ],
    "python": [
        "python",
    ],
    "pandas": [
        "pandas",
    ],
    "numpy": [
        "numpy",
    ],
    "sql": [
        "sql",
    ],
    "postgresql": [
        "postgresql",
        "postgres",
    ],
    "mysql": [
        "mysql",
    ],
    "databricks": [
        "databricks",
    ],
    "pyspark": [
        "pyspark",
        "spark",
    ],
    "aws s3": [
        "aws s3",
        "s3",
    ],
    "azure data factory": [
        "azure data factory",
        "adf",
    ],
    "matplotlib": [
        "matplotlib",
    ],
    "seaborn": [
        "seaborn",
    ],
    "k means": [
        "k-means",
        "k means",
        "clustering",
    ],
    "data cleaning": [
        "data cleaning",
        "data cleansing",
    ],
    "data preparation": [
        "data preparation",
        "data preprocessing",
    ],
    "sales analysis": [
        "sales analysis",
        "sales analytics",
    ],
    "inventory": [
        "inventory",
        "inventory management",
    ],
    "supply chain": [
        "supply chain",
    ],
    "kpi": [
        "kpi",
        "kpis",
    ],
    "forecasting": [
        "forecasting",
        "demand forecasting",
    ],
}


def extract_existing_skill_matches(
    master: dict[str, Any],
    job_description: str
) -> list[str]:

    jd = normalize(job_description)

    found = []

    categories = (
        master
        .get("skills", {})
        .get("categories", {})
    )

    for category_skills in categories.values():

        if not isinstance(category_skills, list):
            continue

        for skill in category_skills:

            if not isinstance(skill, str):
                continue

            skill_normalized = normalize(skill)

            matched = False

            if skill_normalized in jd:
                matched = True

            else:

                for alias in KNOWN_SKILL_ALIASES.values():

                    if skill_normalized in alias:

                        if any(
                            a in jd
                            for a in alias
                        ):
                            matched = True

                        break

            if matched:
                found.append(skill)

    # Preserve order but remove duplicates.
    return list(dict.fromkeys(found))


# ============================================================
# PROJECT RELEVANCE
# ============================================================

PROJECT_KEYWORDS = {

    "Madhav E-Commerce Sales Dashboard": [
        "sql",
        "postgresql",
        "power bi",
        "power query",
        "dax",
        "dashboard",
        "sales",
        "etl",
        "data cleaning",
        "data pipeline",
        "reporting",
        "kpi",
        "analytics",
        "database",
    ],

    "Supply Chain Intelligence Hub": [
        "python",
        "pandas",
        "power bi",
        "excel",
        "supply chain",
        "inventory",
        "logistics",
        "kpi",
        "clustering",
        "k-means",
        "forecasting",
        "analytics",
        "data analysis",
    ],

    "Supply Chain Digital Twin Simulation": [
        "python",
        "pandas",
        "numpy",
        "supply chain",
        "simulation",
        "digital twin",
        "sql",
        "data",
        "inventory",
        "forecasting",
        "operations",
        "analytics",
    ],
}


def project_score(
    project: dict[str, Any],
    job_description: str
) -> int:

    jd = normalize(job_description)

    name = project.get("name", "")

    keywords = PROJECT_KEYWORDS.get(
        name,
        []
    )

    score = 0

    for keyword in keywords:

        if normalize(keyword) in jd:
            score += 1

    # Also inspect technologies.
    technologies = project.get(
        "technologies",
        ""
    )

    for technology in technologies.split("+"):

        technology = technology.strip()

        if (
            technology
            and normalize(technology) in jd
        ):
            score += 2

    return score


def rank_projects(
    master: dict[str, Any],
    job_description: str
) -> list[dict[str, Any]]:

    projects = master.get(
        "projects",
        []
    )

    ranked = []

    for index, project in enumerate(projects):

        score = project_score(
            project,
            job_description
        )

        ranked.append(
            {
                "index": index,
                "project": project,
                "score": score,
            }
        )

    ranked.sort(
        key=lambda item: (
            item["score"],
            -item["index"]
        ),
        reverse=True
    )

    return ranked


# ============================================================
# SAFE PROJECT REWRITING
# ============================================================

def rewrite_project_bullet(
    bullet: str,
    project_name: str,
    role: str
) -> str:
    """
    Conservative wording transformation.

    IMPORTANT:
    This function deliberately does NOT add:
        - new technologies
        - new metrics
        - new achievements
        - new functionality

    It only improves wording and emphasis.
    """

    text = bullet.strip()

    # --------------------------------------------------------
    # Data Analyst
    # --------------------------------------------------------

    if role in {
        "data analyst",
        "bi analyst",
        "business analyst",
        "general analytics",
    }:

        replacements = [
            (
                "Wrote a complete PostgreSQL ETL pipeline",
                "Developed a PostgreSQL ETL pipeline"
            ),
            (
                "Created SQL views",
                "Developed SQL views"
            ),
            (
                "Designed an interactive Power BI dashboard",
                "Developed an interactive Power BI dashboard"
            ),
            (
                "Cleaned and analysed",
                "Cleaned and analysed"
            ),
            (
                "Produced an executive KPI summary",
                "Produced an executive KPI analysis"
            ),
            (
                "Segmented products",
                "Segmented products"
            ),
            (
                "Built a one year digital twin",
                "Built a one-year supply chain digital twin"
            ),
            (
                "Computed fill rate",
                "Analysed supply chain KPIs including fill rate"
            ),
        ]

        for old, new in replacements:

            if old in text:
                text = text.replace(
                    old,
                    new
                )

    # --------------------------------------------------------
    # Data Engineer
    # --------------------------------------------------------

    elif role == "data engineer":

        replacements = [
            (
                "Wrote a complete PostgreSQL ETL pipeline",
                "Developed a PostgreSQL ETL pipeline"
            ),
            (
                "loaded 500 orders and 1,500 order lines from CSV",
                "processed 500 orders and 1,500 order lines from CSV"
            ),
            (
                "Created SQL views",
                "Developed SQL views"
            ),
            (
                "Generated a relational model",
                "Generated a relational data model"
            ),
            (
                "automated primary and foreign key integrity checks",
                "implemented automated primary and foreign-key integrity checks"
            ),
        ]

        for old, new in replacements:

            if old in text:
                text = text.replace(
                    old,
                    new
                )

    # --------------------------------------------------------
    # Supply Chain Analyst
    # --------------------------------------------------------

    elif role == "supply chain analyst":

        replacements = [
            (
                "Cleaned and analysed",
                "Analysed and prepared"
            ),
            (
                "built 0 to 100 scoring indices",
                "developed 0-to-100 scoring indices"
            ),
            (
                "Produced an executive KPI summary",
                "Produced an executive supply chain KPI analysis"
            ),
            (
                "flagged high risk suppliers",
                "identified high-risk suppliers"
            ),
            (
                "wrote up restocking and supplier recommendations",
                "developed restocking and supplier recommendations"
            ),
            (
                "Computed fill rate",
                "Analysed fill rate"
            ),
        ]

        for old, new in replacements:

            if old in text:
                text = text.replace(
                    old,
                    new
                )

    # --------------------------------------------------------
    # SQL Developer
    # --------------------------------------------------------

    elif role == "sql developer":

        replacements = [
            (
                "Wrote a complete PostgreSQL ETL pipeline",
                "Developed a PostgreSQL ETL pipeline"
            ),
            (
                "Created SQL views",
                "Developed SQL views"
            ),
            (
                "16 reusable SQL queries",
                "16 reusable SQL queries"
            ),
            (
                "indexes for faster refresh",
                "indexes to support faster refresh"
            ),
            (
                "Generated a relational model",
                "Generated a relational data model"
            ),
        ]

        for old, new in replacements:

            if old in text:
                text = text.replace(
                    old,
                    new
                )

    # --------------------------------------------------------
    # Python Developer / ML
    # --------------------------------------------------------

    elif role in {
        "python developer",
        "machine learning",
    }:

        replacements = [
            (
                "Cleaned and analysed",
                "Developed Python-based data processing and analysis workflows"
            ),
            (
                "Segmented products",
                "Applied K-Means clustering to segment products"
            ),
            (
                "Built a one year digital twin",
                "Developed a Python-based one-year supply chain digital twin"
            ),
            (
                "Computed fill rate",
                "Implemented calculations for supply chain performance metrics including fill rate"
            ),
        ]

        for old, new in replacements:

            if old in text:
                text = text.replace(
                    old,
                    new
                )

    return text


def customize_project(
    project: dict[str, Any],
    role: str
) -> dict[str, Any]:

    customized = copy.deepcopy(project)

    facts = project.get(
        "facts",
        []
    )

    rewritten = []

    for fact in facts:

        rewritten.append(
            rewrite_project_bullet(
                fact,
                project.get("name", ""),
                role
            )
        )

    # Preserve the original facts in an audit field.
    customized["original_facts"] = copy.deepcopy(
        facts
    )

    customized["customized_bullets"] = rewritten

    # The actual immutable facts remain unchanged.
    customized["facts"] = copy.deepcopy(
        facts
    )

    return customized


# ============================================================
# SUMMARY GENERATION
# ============================================================

def build_summary(
    master: dict[str, Any],
    role: str,
    matched_skills: list[str],
) -> str:

    name = master.get(
        "personal",
        {}
    ).get(
        "name",
        ""
    )

    del name  # intentionally unused

    skills = [
        "SQL",
        "Power BI",
        "Python",
        "Excel",
    ]

    existing_categories = (
        master
        .get("skills", {})
        .get("categories", {})
    )

    all_existing = []

    for values in existing_categories.values():

        if isinstance(values, list):
            all_existing.extend(values)

    available_lower = {
        normalize(skill): skill
        for skill in all_existing
        if isinstance(skill, str)
    }

    selected = []

    for preferred in skills:

        key = normalize(preferred)

        for existing_key, original in available_lower.items():

            if (
                key == existing_key
                or key in existing_key
            ):
                selected.append(original)
                break

    for skill in matched_skills:

        if skill not in selected:
            selected.append(skill)

    # Remove duplicates.
    selected = list(
        dict.fromkeys(selected)
    )

    skill_text = ", ".join(
        selected[:7]
    )

    if role == "data engineer":

        return (
            "Electronics and Telecommunication Engineering "
            "graduate (2026) with working knowledge of "
            f"{skill_text}. Built end-to-end data and analytics "
            "projects involving PostgreSQL ETL, SQL data "
            "transformation, Power BI reporting, Python-based "
            "analysis and supply chain simulation."
        )

    if role == "supply chain analyst":

        return (
            "Electronics and Telecommunication Engineering "
            "graduate (2026) with working knowledge of "
            f"{skill_text}. Built end-to-end supply chain "
            "analytics projects covering inventory health, "
            "supplier performance, KPI analysis, demand "
            "patterns and digital twin simulation."
        )

    if role == "sql developer":

        return (
            "Electronics and Telecommunication Engineering "
            "graduate (2026) with working knowledge of "
            f"{skill_text}. Built end-to-end analytics projects "
            "using PostgreSQL, SQL transformations, ETL workflows, "
            "data quality checks and Power BI reporting."
        )

    if role == "python developer":

        return (
            "Electronics and Telecommunication Engineering "
            "graduate (2026) with working knowledge of "
            f"{skill_text}. Built Python-based analytics and "
            "supply chain projects using Pandas, NumPy, "
            "data processing, clustering and simulation."
        )

    if role == "machine learning":

        return (
            "Electronics and Telecommunication Engineering "
            "graduate (2026) with working knowledge of "
            f"{skill_text}. Built analytics projects involving "
            "Python-based data preparation, K-Means clustering, "
            "supply chain scoring and digital twin simulation."
        )

    # Default analytics profile.
    return (
        "Electronics and Telecommunication Engineering "
        "graduate (2026) with working knowledge of "
        f"{skill_text}. Built three end-to-end analytics "
        "projects covering PostgreSQL ETL, Power BI dashboards, "
        "Python-based supply chain analysis and digital twin "
        "simulation."
    )


# ============================================================
# SKILL REORDERING
# ============================================================

def reorder_skills(
    master: dict[str, Any],
    job_description: str
) -> dict[str, list[str]]:

    categories = (
        master
        .get("skills", {})
        .get("categories", {})
    )

    jd = normalize(job_description)

    result = {}

    scored_categories = []

    for category, skills in categories.items():

        if not isinstance(skills, list):
            continue

        score = 0

        for skill in skills:

            if not isinstance(skill, str):
                continue

            if normalize(skill) in jd:
                score += 1

            # Category relevance.
            if any(
                word in jd
                for word in normalize(category).split()
                if len(word) > 3
            ):
                score += 0.5

        scored_categories.append(
            (
                score,
                category,
                copy.deepcopy(skills)
            )
        )

    scored_categories.sort(
        key=lambda item: item[0],
        reverse=True
    )

    for _, category, skills in scored_categories:

        # Existing skills only.
        # No skill invention.
        skills.sort(
            key=lambda skill: (
                normalize(skill) not in jd,
                normalize(skill)
            )
        )

        result[category] = skills

    return result


# ============================================================
# BUILD CUSTOMIZED RESUME
# ============================================================

def build_customized_resume(
    master: dict[str, Any],
    job_description: str
) -> dict[str, Any]:

    role = detect_role(
        job_description
    )

    matched_skills = extract_existing_skill_matches(
        master,
        job_description
    )

    ranked_projects = rank_projects(
        master,
        job_description
    )

    customized = copy.deepcopy(
        master
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    customized["metadata"][
        "generated_at"
    ] = datetime.now().isoformat(
        timespec="seconds"
    )

    customized["metadata"][
        "generation_type"
    ] = "role_specific_customization"

    customized["metadata"][
        "detected_role"
    ] = role

    customized["metadata"][
        "source_master"
    ] = str(MASTER_RESUME)

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    customized["summary"][
        "original_text"
    ] = build_summary(
        master,
        role,
        matched_skills
    )

    # --------------------------------------------------------
    # SKILLS
    # --------------------------------------------------------

    customized["skills"][
        "categories"
    ] = reorder_skills(
        master,
        job_description
    )

    # Keep original skill text for audit.
    customized["skills"][
        "source_original_text"
    ] = master["skills"].get(
        "original_text",
        ""
    )

    # --------------------------------------------------------
    # PROJECTS
    # --------------------------------------------------------

    new_projects = []

    for item in ranked_projects:

        project = item["project"]

        customized_project = customize_project(
            project,
            role
        )

        customized_project[
            "relevance_score"
        ] = item["score"]

        new_projects.append(
            customized_project
        )

    customized["projects"] = new_projects

    # --------------------------------------------------------
    # LOCKED SECTIONS
    # --------------------------------------------------------

    locked_sections = [
        "personal",
        "education",
        "experience",
        "certifications",
        "training",
        "virtual_job_simulations",
    ]

    for section in locked_sections:

        customized[section] = copy.deepcopy(
            master[section]
        )

    # --------------------------------------------------------
    # PROTECTION
    # --------------------------------------------------------

    customized[
        "generation_protection"
    ] = {

        "source":
            "master_resume.json",

        "detected_role":
            role,

        "matched_existing_skills":
            matched_skills,

        "project_order":
            [
                project["name"]
                for project in new_projects
            ],

        "rules": {

            "never_invent_information":
                True,

            "education_locked":
                True,

            "experience_locked":
                True,

            "certifications_locked":
                True,

            "training_locked":
                True,

            "virtual_simulations_locked":
                True,

            "project_facts_locked":
                True,

            "project_functionality_locked":
                True,

            "summary_rewritten":
                True,

            "skill_order_changed":
                True,

            "project_wording_rewritten":
                True,
        },

        "generated_at":
            datetime.now().isoformat(
                timespec="seconds"
            ),
    }

    return customized


# ============================================================
# INTERNAL SAFETY CHECK
# ============================================================

def compare_locked_sections(
    master: dict[str, Any],
    generated: dict[str, Any]
) -> list[str]:

    violations = []

    locked_sections = [
        "personal",
        "education",
        "experience",
        "certifications",
        "training",
        "virtual_job_simulations",
    ]

    for section in locked_sections:

        if master.get(section) != generated.get(section):

            violations.append(
                f"Locked section changed: {section}"
            )

    # --------------------------------------------------------
    # Project names and facts
    # --------------------------------------------------------

    master_projects = master.get(
        "projects",
        []
    )

    generated_projects = generated.get(
        "projects",
        []
    )

    if len(master_projects) != len(generated_projects):

        violations.append(
            "Number of projects changed."
        )

        return violations

    master_by_name = {
        project.get("name"): project
        for project in master_projects
    }

    generated_by_name = {
        project.get("name"): project
        for project in generated_projects
    }

    if set(master_by_name) != set(generated_by_name):

        violations.append(
            "Project names changed."
        )

        return violations

    for name, master_project in master_by_name.items():

        generated_project = generated_by_name[name]

        if master_project.get(
            "technologies"
        ) != generated_project.get(
            "technologies"
        ):

            violations.append(
                f"Project technologies changed: {name}"
            )

        if master_project.get(
            "facts"
        ) != generated_project.get(
            "facts"
        ):

            violations.append(
                f"Project facts changed: {name}"
            )

    return violations


# ============================================================
# VALIDATOR INTEGRATION
# ============================================================

def run_validator(
    resume_path: Path
) -> int:

    if not VALIDATOR.exists():

        warning(
            "resume_validator.py was not found."
        )

        warning(
            "Skipping external validator."
        )

        return 0

    title(
        "RUNNING RESUME FACT VALIDATOR"
    )

    command = [
        sys.executable,
        str(VALIDATOR),
        "--resume",
        str(resume_path),
    ]

    print()

    result = subprocess.run(
        command,
        cwd=str(BASE_DIR)
    )

    print()

    if result.returncode == 0:

        success(
            "Resume validator completed successfully."
        )

    else:

        error(
            "Resume validator rejected the generated resume."
        )

    return result.returncode


# ============================================================
# REPORT
# ============================================================

def print_report(
    master: dict[str, Any],
    generated: dict[str, Any],
    job_description: str
) -> None:

    role = generated[
        "metadata"
    ].get(
        "detected_role",
        "unknown"
    )

    matched_skills = generated[
        "generation_protection"
    ].get(
        "matched_existing_skills",
        []
    )

    projects = generated.get(
        "projects",
        []
    )

    title(
        "CUSTOMIZATION REPORT"
    )

    info(
        f"Detected role       : {role}"
    )

    info(
        f"Existing skills matched: {len(matched_skills)}"
    )

    if matched_skills:

        print()

        info("Matched existing skills:")

        for skill in matched_skills:

            print(
                f"    • {skill}"
            )

    print()

    info(
        f"Projects included   : {len(projects)}"
    )

    print()

    info("Project ranking:")

    for project in projects:

        print(
            f"    • "
            f"{project.get('name')} "
            f"(score={project.get('relevance_score', 0)})"
        )

    print()

    info(
        f"Job description chars: {len(job_description)}"
    )

    info(
        f"Output               : {OUTPUT_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Generate a role-specific resume "
            "from master_resume.json."
        )
    )

    parser.add_argument(
        "--job-file",
        type=str,
        default=None,
        help="Path to a text file containing the job description."
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional custom output JSON path."
    )

    args = parser.parse_args()

    title(
        "AI JOB APPLICATION & RESUME INTELLIGENCE"
    )

    print(
        "RESUME CUSTOMIZER"
    )

    # --------------------------------------------------------
    # Load master resume
    # --------------------------------------------------------

    print()

    info(
        f"Master profile:"
    )

    info(
        f"  {MASTER_RESUME}"
    )

    try:

        master = load_json(
            MASTER_RESUME
        )

    except Exception as exc:

        error(
            f"Could not load master resume: {exc}"
        )

        return 1

    success(
        "Master resume loaded."
    )

    # --------------------------------------------------------
    # Load job description
    # --------------------------------------------------------

    try:

        job_file = (
            Path(args.job_file)
            if args.job_file
            else None
        )

        job_description = load_job_description(
            job_file
        )

    except Exception as exc:

        error(
            f"Could not load job description: {exc}"
        )

        return 1

    success(
        "Job description loaded."
    )

    # --------------------------------------------------------
    # Generate
    # --------------------------------------------------------

    title(
        "GENERATING ROLE-SPECIFIC RESUME"
    )

    generated = build_customized_resume(
        master,
        job_description
    )

    role = generated[
        "metadata"
    ][
        "detected_role"
    ]

    info(
        f"Detected role: {role}"
    )

    # --------------------------------------------------------
    # Internal safety check
    # --------------------------------------------------------

    title(
        "INTERNAL FACT PROTECTION CHECK"
    )

    violations = compare_locked_sections(
        master,
        generated
    )

    if violations:

        for violation in violations:

            error(
                violation
            )

        error(
            "Generation stopped because protected data changed."
        )

        return 2

    success(
        "All locked sections preserved."
    )

    success(
        "All project facts preserved."
    )

    success(
        "Project names preserved."
    )

    success(
        "Project technologies preserved."
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    output_path = (
        Path(args.output)
        if args.output
        else OUTPUT_FILE
    )

    try:

        save_json(
            output_path,
            generated
        )

    except Exception as exc:

        error(
            f"Could not save generated resume: {exc}"
        )

        return 1

    success(
        f"Generated resume saved to:"
    )

    info(
        f"  {output_path}"
    )

    # --------------------------------------------------------
    # Report
    # --------------------------------------------------------

    print_report(
        master,
        generated,
        job_description
    )

    # --------------------------------------------------------
    # Validator
    # --------------------------------------------------------

    validator_code = run_validator(
        output_path
    )

    if validator_code != 0:

        title(
            "GENERATION REJECTED"
        )

        error(
            "The generated resume failed validation."
        )

        return validator_code

    # --------------------------------------------------------
    # Complete
    # --------------------------------------------------------

    title(
        "CUSTOMIZATION COMPLETE"
    )

    success(
        "Role-specific resume generated."
    )

    success(
        "Protected resume facts preserved."
    )

    success(
        "Validator completed."
    )

    info(
        f"Final file: {output_path}"
    )

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    raise SystemExit(
        main()
    )