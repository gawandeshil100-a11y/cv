#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI JOB APPLICATION & RESUME INTELLIGENCE
========================================

resume_validator.py

Purpose:
--------
Validate an AI-generated/customized resume against the user's
master_resume.json.

The validator protects factual information while allowing
controlled customization.

LOCKED / PROTECTED
------------------
- Personal information
- Education
- Experience
- Certifications
- Training
- Virtual Job Simulations
- Project identity
- Project functionality
- Project factual metrics

CUSTOMIZABLE
------------
- Professional Summary
- Skill ordering
- Project wording
- ATS keyword emphasis

The validator is designed around the ACTUAL master_resume.json
schema discovered using schema_inspect.py.

Important:
----------
This script NEVER modifies master_resume.json.
"""


from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ============================================================================
# PATHS
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent

MASTER_RESUME_PATH = (
    BASE_DIR
    / "resume_data"
    / "master_resume.json"
)


# ============================================================================
# TERMINAL COLORS
# ============================================================================

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BLUE = "\033[94m"


# ============================================================================
# ACTUAL MASTER SCHEMA
# ============================================================================

# These are dictionaries containing original_text.
LOCKED_DICT_SECTIONS = [
    "availability",
    "training",
    "education",
    "experience",
    "certifications",
    "achievements",
]

# These are lists containing objects.
LOCKED_LIST_SECTIONS = [
    "projects",
    "virtual_job_simulations",
]


# ============================================================================
# GENERIC UTILITIES
# ============================================================================

def normalize_text(value: Any) -> str:
    """
    Normalize text for factual comparison.

    This does NOT modify the source data.
    """

    if value is None:
        return ""

    text = str(value)

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(r"\s+", " ", text)

    return text.strip().lower()


def normalize_for_matching(value: Any) -> str:
    """
    More aggressive normalization used for matching facts.

    Removes punctuation while preserving numbers and words.
    """

    text = normalize_text(value)

    text = re.sub(
        r"[^a-z0-9%₹$.,]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def load_json(path: Path) -> Any:
    """
    Read JSON file.
    """

    if not path.exists():

        raise FileNotFoundError(
            f"File not found:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


def print_separator(char: str = "=") -> None:

    print(char * 72)


def print_header(title: str) -> None:

    print()
    print_separator()
    print(title)
    print_separator()


def unique_preserve_order(
    values: List[str]
) -> List[str]:

    result = []

    seen = set()

    for value in values:

        normalized = normalize_text(value)

        if not normalized:
            continue

        if normalized not in seen:

            seen.add(normalized)
            result.append(value)

    return result


# ============================================================================
# RECURSIVE TEXT EXTRACTION
# ============================================================================

def collect_text(
    node: Any,
    path: str = "$",
) -> List[Tuple[str, str]]:
    """
    Recursively collect all textual values from a JSON structure.

    Returns:
        [(path, text), ...]
    """

    results = []

    if isinstance(node, dict):

        for key, value in node.items():

            child_path = (
                f"{path}.{key}"
                if path != "$"
                else key
            )

            results.extend(
                collect_text(
                    value,
                    child_path,
                )
            )

    elif isinstance(node, list):

        for index, value in enumerate(node):

            child_path = (
                f"{path}[{index}]"
            )

            results.extend(
                collect_text(
                    value,
                    child_path,
                )
            )

    elif isinstance(node, str):

        if node.strip():

            results.append(
                (
                    path,
                    node,
                )
            )

    return results


def recursive_original_texts(
    node: Any,
    path: str = "$",
) -> List[Tuple[str, str]]:
    """
    Find every original_text field recursively.
    """

    results = []

    if isinstance(node, dict):

        for key, value in node.items():

            child_path = (
                f"{path}.{key}"
                if path != "$"
                else key
            )

            if key == "original_text":

                if isinstance(value, str):

                    results.append(
                        (
                            child_path,
                            value,
                        )
                    )

            results.extend(
                recursive_original_texts(
                    value,
                    child_path,
                )
            )

    elif isinstance(node, list):

        for index, value in enumerate(node):

            child_path = (
                f"{path}[{index}]"
            )

            results.extend(
                recursive_original_texts(
                    value,
                    child_path,
                )
            )

    return results


# ============================================================================
# STRUCTURE VALIDATION
# ============================================================================

def validate_master_structure(
    master: Any,
) -> List[str]:

    errors = []

    if not isinstance(master, dict):

        return [
            "MASTER ROOT MUST BE A DICTIONARY."
        ]

    required_sections = [
        "metadata",
        "personal",
        "availability",
        "summary",
        "skills",
        "projects",
        "virtual_job_simulations",
        "training",
        "education",
        "experience",
        "certifications",
        "achievements",
        "raw_sections",
        "raw_text",
        "protection",
        "customization_policy",
    ]

    for section in required_sections:

        if section not in master:

            errors.append(
                f"Missing top-level section: {section}"
            )

    # ------------------------------------------------------------------------
    # Required dictionaries
    # ------------------------------------------------------------------------

    required_dicts = [
        "metadata",
        "personal",
        "availability",
        "summary",
        "skills",
        "training",
        "education",
        "experience",
        "certifications",
        "achievements",
        "raw_sections",
        "protection",
        "customization_policy",
    ]

    for section in required_dicts:

        if section in master:

            if not isinstance(
                master[section],
                dict,
            ):

                errors.append(
                    f"{section} must be a dict, "
                    f"found {type(master[section]).__name__}"
                )

    # ------------------------------------------------------------------------
    # Required lists
    # ------------------------------------------------------------------------

    required_lists = [
        "projects",
        "virtual_job_simulations",
    ]

    for section in required_lists:

        if section in master:

            if not isinstance(
                master[section],
                list,
            ):

                errors.append(
                    f"{section} must be a list, "
                    f"found {type(master[section]).__name__}"
                )

    # ------------------------------------------------------------------------
    # original_text validation
    # ------------------------------------------------------------------------

    for section in LOCKED_DICT_SECTIONS:

        section_data = master.get(
            section
        )

        if isinstance(
            section_data,
            dict,
        ):

            if not isinstance(
                section_data.get(
                    "original_text"
                ),
                str,
            ):

                errors.append(
                    f"{section}.original_text "
                    "must be a string."
                )

    # ------------------------------------------------------------------------
    # Project validation
    # ------------------------------------------------------------------------

    projects = master.get(
        "projects",
        [],
    )

    if isinstance(projects, list):

        if not projects:

            errors.append(
                "projects list is empty."
            )

        for index, project in enumerate(projects):

            if not isinstance(
                project,
                dict,
            ):

                errors.append(
                    f"projects[{index}] must be a dict."
                )
                continue

            if not project.get("name"):

                errors.append(
                    f"projects[{index}] has no name."
                )

            if not isinstance(
                project.get("original_text"),
                str,
            ):

                errors.append(
                    f"projects[{index}].original_text "
                    "must be a string."
                )

    # ------------------------------------------------------------------------
    # Virtual simulation validation
    # ------------------------------------------------------------------------

    simulations = master.get(
        "virtual_job_simulations",
        [],
    )

    if isinstance(simulations, list):

        for index, simulation in enumerate(
            simulations
        ):

            if not isinstance(
                simulation,
                dict,
            ):

                errors.append(
                    "virtual_job_simulations"
                    f"[{index}] must be a dict."
                )
                continue

            if not simulation.get("name"):

                errors.append(
                    "virtual_job_simulations"
                    f"[{index}] has no name."
                )

            if not isinstance(
                simulation.get("original_text"),
                str,
            ):

                errors.append(
                    "virtual_job_simulations"
                    f"[{index}].original_text "
                    "must be a string."
                )

    return errors


# ============================================================================
# PROTECTION CONFIGURATION
# ============================================================================

def get_protection_rules(
    master: Dict[str, Any]
) -> Dict[str, Any]:

    protection = master.get(
        "protection",
        {},
    )

    if not isinstance(
        protection,
        dict,
    ):

        return {}

    rules = protection.get(
        "rules",
        {},
    )

    if isinstance(
        rules,
        dict,
    ):

        return rules

    return {}


def get_locked_sections(
    master: Dict[str, Any]
) -> List[str]:

    protection = master.get(
        "protection",
        {},
    )

    if not isinstance(
        protection,
        dict,
    ):

        return []

    locked = protection.get(
        "locked_sections",
        [],
    )

    if isinstance(
        locked,
        list,
    ):

        return [
            str(item)
            for item in locked
        ]

    return []


# ============================================================================
# EXTRACT MASTER LOCKED FACTS
# ============================================================================

def extract_locked_master_facts(
    master: Dict[str, Any]
) -> Dict[str, List[str]]:
    """
    Extract factual text from all protected sections.

    Handles dictionaries AND lists correctly.
    """

    facts = {}

    # ------------------------------------------------------------------------
    # Dictionary sections
    # ------------------------------------------------------------------------

    for section in LOCKED_DICT_SECTIONS:

        data = master.get(
            section
        )

        section_facts = []

        if isinstance(
            data,
            dict,
        ):

            original_text = data.get(
                "original_text",
                "",
            )

            if isinstance(
                original_text,
                str,
            ) and original_text.strip():

                section_facts.append(
                    original_text
                )

        facts[section] = section_facts

    # ------------------------------------------------------------------------
    # List sections
    # ------------------------------------------------------------------------

    for section in LOCKED_LIST_SECTIONS:

        data = master.get(
            section
        )

        section_facts = []

        if isinstance(
            data,
            list,
        ):

            for index, item in enumerate(
                data
            ):

                if not isinstance(
                    item,
                    dict,
                ):

                    continue

                original_text = item.get(
                    "original_text",
                    "",
                )

                if isinstance(
                    original_text,
                    str,
                ) and original_text.strip():

                    section_facts.append(
                        original_text
                    )

        facts[section] = section_facts

    return facts


# ============================================================================
# PROJECT FACTS
# ============================================================================

def extract_project_facts(
    master: Dict[str, Any]
) -> List[str]:
    """
    Extract project facts from protection.project_facts.

    Also falls back to project-level facts when available.
    """

    results = []

    protection = master.get(
        "protection",
        {},
    )

    if isinstance(
        protection,
        dict,
    ):

        protected_project_facts = protection.get(
            "project_facts",
            [],
        )

        if isinstance(
            protected_project_facts,
            list,
        ):

            for fact in protected_project_facts:

                if isinstance(
                    fact,
                    str,
                ):

                    results.append(
                        fact
                    )

                elif isinstance(
                    fact,
                    dict,
                ):

                    for value in fact.values():

                        if isinstance(
                            value,
                            str,
                        ):

                            results.append(
                                value
                            )

                        elif isinstance(
                            value,
                            list,
                        ):

                            for item in value:

                                if isinstance(
                                    item,
                                    str,
                                ):

                                    results.append(
                                        item
                                    )

    # ------------------------------------------------------------------------
    # Project-level facts
    # ------------------------------------------------------------------------

    projects = master.get(
        "projects",
        [],
    )

    if isinstance(
        projects,
        list,
    ):

        for project in projects:

            if not isinstance(
                project,
                dict,
            ):

                continue

            project_facts = project.get(
                "facts",
                [],
            )

            if isinstance(
                project_facts,
                list,
            ):

                for fact in project_facts:

                    if isinstance(
                        fact,
                        str,
                    ):

                        results.append(
                            fact
                        )

    return unique_preserve_order(
        results
    )


# ============================================================================
# MASTER TECHNOLOGIES
# ============================================================================

def extract_master_technologies(
    master: Dict[str, Any]
) -> List[str]:
    """
    Extract known technologies from skills and projects.
    """

    technologies = []

    # ------------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------------

    skills = master.get(
        "skills",
        {},
    )

    if isinstance(
        skills,
        dict,
    ):

        categories = skills.get(
            "categories",
            {},
        )

        if isinstance(
            categories,
            dict,
        ):

            for values in categories.values():

                if isinstance(
                    values,
                    list,
                ):

                    for value in values:

                        if isinstance(
                            value,
                            str,
                        ):

                            technologies.append(
                                value
                            )

    # ------------------------------------------------------------------------
    # Project technologies
    # ------------------------------------------------------------------------

    projects = master.get(
        "projects",
        [],
    )

    if isinstance(
        projects,
        list,
    ):

        for project in projects:

            if not isinstance(
                project,
                dict,
            ):

                continue

            tech = project.get(
                "technologies",
                "",
            )

            if isinstance(
                tech,
                str,
            ):

                parts = re.split(
                    r"[,|+/;]+",
                    tech,
                )

                technologies.extend(
                    parts
                )

    return unique_preserve_order(
        technologies
    )


# ============================================================================
# CANDIDATE TEXT
# ============================================================================

def candidate_full_text(
    candidate: Dict[str, Any]
) -> str:

    pieces = []

    for path, text in collect_text(
        candidate
    ):

        pieces.append(
            text
        )

    return normalize_for_matching(
        " ".join(pieces)
    )


# ============================================================================
# LOCKED FACT VALIDATION
# ============================================================================

def fact_present(
    fact: str,
    candidate_text: str,
) -> bool:

    normalized_fact = normalize_for_matching(
        fact
    )

    if not normalized_fact:
        return True

    # Exact normalized fact
    if normalized_fact in candidate_text:

        return True

    # ------------------------------------------------------------------------
    # For longer facts, check important factual tokens.
    # ------------------------------------------------------------------------

    tokens = normalized_fact.split()

    important_tokens = []

    for token in tokens:

        # Numbers, percentages, currencies and technical names
        # are important.
        if (
            any(char.isdigit() for char in token)
            or "%" in token
            or "₹" in token
            or "$" in token
            or len(token) >= 6
        ):

            important_tokens.append(
                token
            )

    if not important_tokens:

        return False

    matched = sum(
        1
        for token in important_tokens
        if token in candidate_text
    )

    # Require all important factual tokens.
    return matched == len(
        important_tokens
    )


def validate_locked_facts(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    errors = []

    candidate_text = candidate_full_text(
        candidate
    )

    locked_facts = extract_locked_master_facts(
        master
    )

    for section, facts in locked_facts.items():

        for fact in facts:

            if not fact_present(
                fact,
                candidate_text,
            ):

                errors.append(
                    "LOCKED FACT MISSING: "
                    f"{section} -> "
                    f"{fact[:160]}"
                )

    return errors


# ============================================================================
# PROJECT VALIDATION
# ============================================================================

def extract_project_names(
    data: Dict[str, Any]
) -> List[str]:

    result = []

    projects = data.get(
        "projects",
        [],
    )

    if not isinstance(
        projects,
        list,
    ):

        return result

    for project in projects:

        if not isinstance(
            project,
            dict,
        ):

            continue

        name = project.get(
            "name",
            "",
        )

        if isinstance(
            name,
            str,
        ) and name.strip():

            result.append(
                name
            )

    return result


def validate_project_identity(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    errors = []

    master_projects = extract_project_names(
        master
    )

    candidate_projects = extract_project_names(
        candidate
    )

    candidate_names_normalized = {
        normalize_text(name)
        for name in candidate_projects
    }

    for project_name in master_projects:

        if normalize_text(
            project_name
        ) not in candidate_names_normalized:

            errors.append(
                "PROJECT REMOVED OR RENAMED: "
                f"{project_name}"
            )

    return errors


# ============================================================================
# PROJECT METRIC VALIDATION
# ============================================================================

def extract_factual_numbers(
    text: str
) -> List[str]:

    if not isinstance(
        text,
        str,
    ):

        return []

    # Preserve common numbers and percentages.
    matches = re.findall(
        r"(?<![A-Za-z])"
        r"\d+(?:,\d{3})*"
        r"(?:\.\d+)?"
        r"%?",
        text,
    )

    return unique_preserve_order(
        matches
    )


def validate_project_metrics(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    errors = []

    master_projects = master.get(
        "projects",
        [],
    )

    candidate_projects = candidate.get(
        "projects",
        [],
    )

    if not isinstance(
        master_projects,
        list,
    ):

        return [
            "Master projects is not a list."
        ]

    if not isinstance(
        candidate_projects,
        list,
    ):

        return [
            "Candidate projects is not a list."
        ]

    candidate_text = candidate_full_text(
        candidate
    )

    # ------------------------------------------------------------------------
    # Use project facts from protection
    # ------------------------------------------------------------------------

    protected_facts = extract_project_facts(
        master
    )

    for fact in protected_facts:

        numbers = extract_factual_numbers(
            fact
        )

        for number in numbers:

            # Ignore trivial numbers.
            if number in {
                "0",
                "1",
                "2",
                "3",
            }:

                continue

            if number not in candidate_text:

                errors.append(
                    "PROJECT METRIC/NUMBER MISSING: "
                    f"{number}"
                )

    # ------------------------------------------------------------------------
    # Project-level facts
    # ------------------------------------------------------------------------

    for project in master_projects:

        if not isinstance(
            project,
            dict,
        ):

            continue

        project_name = project.get(
            "name",
            "Unknown Project",
        )

        facts = project.get(
            "facts",
            [],
        )

        if not isinstance(
            facts,
            list,
        ):

            continue

        for fact in facts:

            if not isinstance(
                fact,
                str,
            ):

                continue

            numbers = extract_factual_numbers(
                fact
            )

            for number in numbers:

                if number in {
                    "0",
                    "1",
                    "2",
                    "3",
                }:

                    continue

                if number not in candidate_text:

                    errors.append(
                        f"PROJECT FACT MAY BE "
                        f"MISSING: {project_name} "
                        f"-> {number}"
                    )

    return unique_preserve_order(
        errors
    )


# ============================================================================
# EDUCATION VALIDATION
# ============================================================================

def validate_education(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    errors = []

    master_education = master.get(
        "education",
        {},
    )

    candidate_education = candidate.get(
        "education",
        {},
    )

    if not isinstance(
        master_education,
        dict,
    ):

        return [
            "Master education is not a dict."
        ]

    if not isinstance(
        candidate_education,
        dict,
    ):

        return [
            "Candidate education is not a dict."
        ]

    master_text = master_education.get(
        "original_text",
        "",
    )

    candidate_text = candidate_education.get(
        "original_text",
        "",
    )

    if not candidate_text:

        errors.append(
            "EDUCATION SECTION MISSING."
        )

        return errors

    # Important factual education tokens.
    master_numbers = extract_factual_numbers(
        master_text
    )

    normalized_candidate = normalize_for_matching(
        candidate_text
    )

    for number in master_numbers:

        if number not in normalized_candidate:

            errors.append(
                "EDUCATION FACT MISSING: "
                f"{number}"
            )

    # Degree-related tokens.
    degree_keywords = [
        "b.e",
        "be",
        "bachelor",
        "engineering",
        "electronics",
        "telecommunication",
        "university",
        "cgpa",
        "percentage",
    ]

    normalized_master = normalize_for_matching(
        master_text
    )

    for keyword in degree_keywords:

        if keyword in normalized_master:

            if keyword not in normalized_candidate:

                errors.append(
                    "EDUCATION KEYWORD MISSING: "
                    f"{keyword}"
                )

    return unique_preserve_order(
        errors
    )


# ============================================================================
# TRAINING VALIDATION
# ============================================================================

def validate_training(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    errors = []

    master_training = master.get(
        "training",
        {},
    )

    candidate_training = candidate.get(
        "training",
        {},
    )

    if not isinstance(
        master_training,
        dict,
    ):

        return [
            "Master training is not a dict."
        ]

    if not isinstance(
        candidate_training,
        dict,
    ):

        return [
            "Candidate training is not a dict."
        ]

    master_text = normalize_for_matching(
        master_training.get(
            "original_text",
            "",
        )
    )

    candidate_text = normalize_for_matching(
        candidate_training.get(
            "original_text",
            "",
        )
    )

    if master_text and not candidate_text:

        errors.append(
            "TRAINING SECTION REMOVED."
        )

        return errors

    # Require company/course/provider names
    # to remain present where possible.
    important_tokens = [
        token
        for token in master_text.split()
        if len(token) >= 6
    ]

    for token in important_tokens:

        if token not in candidate_text:

            errors.append(
                "TRAINING FACT MAY BE "
                f"MISSING: {token}"
            )

    return unique_preserve_order(
        errors
    )


# ============================================================================
# VIRTUAL JOB SIMULATION VALIDATION
# ============================================================================

def validate_virtual_job_simulations(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    errors = []

    master_simulations = master.get(
        "virtual_job_simulations",
        [],
    )

    candidate_simulations = candidate.get(
        "virtual_job_simulations",
        [],
    )

    if not isinstance(
        master_simulations,
        list,
    ):

        return [
            "Master virtual_job_simulations "
            "is not a list."
        ]

    if not isinstance(
        candidate_simulations,
        list,
    ):

        return [
            "Candidate virtual_job_simulations "
            "is not a list."
        ]

    candidate_names = []

    for item in candidate_simulations:

        if isinstance(
            item,
            dict,
        ):

            name = item.get(
                "name",
                "",
            )

            if isinstance(
                name,
                str,
            ):

                candidate_names.append(
                    normalize_text(name)
                )

    for master_item in master_simulations:

        if not isinstance(
            master_item,
            dict,
        ):

            continue

        name = master_item.get(
            "name",
            "",
        )

        if not isinstance(
            name,
            str,
        ):

            continue

        if normalize_text(
            name
        ) not in candidate_names:

            errors.append(
                "VIRTUAL JOB SIMULATION "
                f"REMOVED: {name}"
            )

    return errors


# ============================================================================
# EXPERIENCE VALIDATION
# ============================================================================

def validate_dict_locked_section(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
    section: str,
) -> List[str]:

    errors = []

    master_section = master.get(
        section,
        {},
    )

    candidate_section = candidate.get(
        section,
        {},
    )

    if not isinstance(
        master_section,
        dict,
    ):

        return [
            f"Master {section} is not a dict."
        ]

    if not isinstance(
        candidate_section,
        dict,
    ):

        return [
            f"Candidate {section} is not a dict."
        ]

    master_text = master_section.get(
        "original_text",
        "",
    )

    candidate_text = candidate_section.get(
        "original_text",
        "",
    )

    if master_text and not candidate_text:

        errors.append(
            f"{section.upper()} SECTION REMOVED."
        )

        return errors

    # ------------------------------------------------------------------------
    # Extract numbers and important factual tokens.
    # ------------------------------------------------------------------------

    master_numbers = extract_factual_numbers(
        master_text
    )

    normalized_candidate = normalize_for_matching(
        candidate_text
    )

    for number in master_numbers:

        if number in {
            "0",
            "1",
            "2",
            "3",
        }:

            continue

        if number not in normalized_candidate:

            errors.append(
                f"{section.upper()} FACT MISSING: "
                f"{number}"
            )

    return errors


# ============================================================================
# CERTIFICATION VALIDATION
# ============================================================================

def validate_certifications(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    return validate_dict_locked_section(
        master,
        candidate,
        "certifications",
    )


# ============================================================================
# EXPERIENCE VALIDATION
# ============================================================================

def validate_experience(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    return validate_dict_locked_section(
        master,
        candidate,
        "experience",
    )


# ============================================================================
# ACHIEVEMENT VALIDATION
# ============================================================================

def validate_achievements(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    return validate_dict_locked_section(
        master,
        candidate,
        "achievements",
    )


# ============================================================================
# TECHNOLOGY INVENTION DETECTION
# ============================================================================

MONITORED_TECHNOLOGIES = [
    "python",
    "sql",
    "postgresql",
    "mysql",
    "oracle",
    "power bi",
    "tableau",
    "excel",
    "pandas",
    "numpy",
    "matplotlib",
    "seaborn",
    "pyspark",
    "spark",
    "databricks",
    "aws",
    "aws s3",
    "azure",
    "azure data factory",
    "jupyter",
    "dax",
    "power query",
    "k-means",
    "machine learning",
    "tensorflow",
    "pytorch",
    "snowflake",
    "airflow",
    "docker",
    "kubernetes",
    "etl",
    "elt",
    "nlp",
    "computer vision",
]


def validate_new_technologies(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    warnings = []

    known = {
        normalize_text(value)
        for value in extract_master_technologies(
            master
        )
    }

    candidate_text = candidate_full_text(
        candidate
    )

    for technology in MONITORED_TECHNOLOGIES:

        normalized = normalize_text(
            technology
        )

        if normalized in candidate_text:

            if normalized not in known:

                warnings.append(
                    "NEW TECHNOLOGY DETECTED: "
                    f"{technology}"
                )

    return warnings


# ============================================================================
# INVENTION DETECTION USING MASTER VOCABULARY
# ============================================================================

def validate_suspicious_claims(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:

    warnings = []

    candidate_text = candidate_full_text(
        candidate
    )

    # ------------------------------------------------------------------------
    # Suspicious experience phrases
    # ------------------------------------------------------------------------

    suspicious_patterns = [
        r"\b\d+\+?\s+years?\s+of\s+experience\b",
        r"\bled\s+a\s+team\b",
        r"\bmanaged\s+a\s+team\b",
        r"\bproduction\s+environment\b",
        r"\bdeployed\s+to\s+production\b",
        r"\benterprise[- ]scale\b",
    ]

    master_text = candidate_full_text(
        master
    )

    for pattern in suspicious_patterns:

        matches = re.findall(
            pattern,
            candidate_text,
            flags=re.IGNORECASE,
        )

        for match in matches:

            if normalize_text(match) not in master_text:

                warnings.append(
                    "SUSPICIOUS CLAIM: "
                    f"{match}"
                )

    return unique_preserve_order(
        warnings
    )


# ============================================================================
# MASTER SELF CHECK
# ============================================================================

def master_self_check(
    master: Dict[str, Any]
) -> Dict[str, Any]:

    errors = []

    errors.extend(
        validate_master_structure(
            master
        )
    )

    protection = master.get(
        "protection",
        {},
    )

    if not isinstance(
        protection,
        dict,
    ):

        errors.append(
            "protection must be a dict."
        )

    else:

        if not isinstance(
            protection.get(
                "locked_sections",
                [],
            ),
            list,
        ):

            errors.append(
                "protection.locked_sections "
                "must be a list."
            )

        if not isinstance(
            protection.get(
                "locked_hashes",
                {},
            ),
            dict,
        ):

            errors.append(
                "protection.locked_hashes "
                "must be a dict."
            )

        if not isinstance(
            protection.get(
                "project_facts",
                [],
            ),
            list,
        ):

            errors.append(
                "protection.project_facts "
                "must be a list."
            )

    # Check original_text locations.
    original_texts = recursive_original_texts(
        master
    )

    if not original_texts:

        errors.append(
            "No original_text fields found."
        )

    return {
        "status": (
            "PASS"
            if not errors
            else "FAIL"
        ),
        "passed": not errors,
        "errors": unique_preserve_order(
            errors
        ),
    }


# ============================================================================
# COMPLETE CANDIDATE VALIDATION
# ============================================================================

def validate_candidate(
    master: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:

    errors = []
    warnings = []

    # ------------------------------------------------------------------------
    # Candidate structure
    # ------------------------------------------------------------------------

    if not isinstance(
        candidate,
        dict,
    ):

        return {
            "status": "FAIL",
            "passed": False,
            "errors": [
                "Candidate resume root must be a dict."
            ],
            "warnings": [],
        }

    # ------------------------------------------------------------------------
    # Protected sections
    # ------------------------------------------------------------------------

    errors.extend(
        validate_dict_locked_section(
            master,
            candidate,
            "experience",
        )
    )

    errors.extend(
        validate_certifications(
            master,
            candidate,
        )
    )

    errors.extend(
        validate_training(
            master,
            candidate,
        )
    )

    errors.extend(
        validate_education(
            master,
            candidate,
        )
    )

    errors.extend(
        validate_achievements(
            master,
            candidate,
        )
    )

    # ------------------------------------------------------------------------
    # Virtual job simulations
    # ------------------------------------------------------------------------

    errors.extend(
        validate_virtual_job_simulations(
            master,
            candidate,
        )
    )

    # ------------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------------

    errors.extend(
        validate_project_identity(
            master,
            candidate,
        )
    )

    errors.extend(
        validate_project_metrics(
            master,
            candidate,
        )
    )

    # ------------------------------------------------------------------------
    # Generic locked facts
    # ------------------------------------------------------------------------

    errors.extend(
        validate_locked_facts(
            master,
            candidate,
        )
    )

    # ------------------------------------------------------------------------
    # Technology invention warnings
    # ------------------------------------------------------------------------

    warnings.extend(
        validate_new_technologies(
            master,
            candidate,
        )
    )

    # ------------------------------------------------------------------------
    # Suspicious claims
    # ------------------------------------------------------------------------

    warnings.extend(
        validate_suspicious_claims(
            master,
            candidate,
        )
    )

    errors = unique_preserve_order(
        errors
    )

    warnings = unique_preserve_order(
        warnings
    )

    return {
        "status": (
            "PASS"
            if not errors
            else "FAIL"
        ),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


# ============================================================================
# PRINT RESULT
# ============================================================================

def print_validation_result(
    result: Dict[str, Any]
) -> None:

    if result.get(
        "passed",
        False,
    ):

        print(
            f"\n{GREEN}✓ VALIDATION PASSED{RESET}"
        )

    else:

        print(
            f"\n{RED}✗ VALIDATION FAILED{RESET}"
        )

    print(
        f"Errors   : "
        f"{result.get('error_count', len(result.get('errors', [])))}"
    )

    print(
        f"Warnings : "
        f"{result.get('warning_count', len(result.get('warnings', [])))}"
    )

    errors = result.get(
        "errors",
        [],
    )

    if errors:

        print()
        print(
            f"{RED}ERRORS{RESET}"
        )

        for index, error in enumerate(
            errors,
            start=1,
        ):

            print(
                f"  {index}. {error}"
            )

    warnings = result.get(
        "warnings",
        [],
    )

    if warnings:

        print()
        print(
            f"{YELLOW}WARNINGS{RESET}"
        )

        for index, warning in enumerate(
            warnings,
            start=1,
        ):

            print(
                f"  {index}. {warning}"
            )


# ============================================================================
# MASTER PROFILE SUMMARY
# ============================================================================

def print_master_summary(
    master: Dict[str, Any]
) -> None:

    print_header(
        "MASTER PROFILE SUMMARY"
    )

    projects = master.get(
        "projects",
        [],
    )

    simulations = master.get(
        "virtual_job_simulations",
        [],
    )

    skills = master.get(
        "skills",
        {},
    )

    print(
        f"Projects                : "
        f"{len(projects) if isinstance(projects, list) else 0}"
    )

    print(
        f"Virtual simulations     : "
        f"{len(simulations) if isinstance(simulations, list) else 0}"
    )

    if isinstance(
        skills,
        dict,
    ):

        categories = skills.get(
            "categories",
            {},
        )

        if isinstance(
            categories,
            dict,
        ):

            skill_count = sum(
                len(values)
                for values in categories.values()
                if isinstance(
                    values,
                    list,
                )
            )

            print(
                f"Known skills            : "
                f"{skill_count}"
            )

    print(
        f"Protected project facts : "
        f"{len(extract_project_facts(master))}"
    )

    print(
        f"Locked sections         : "
        f"{len(get_locked_sections(master))}"
    )


# ============================================================================
# ARGUMENTS
# ============================================================================

def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Validate an AI-generated resume "
            "against master_resume.json."
        )
    )

    parser.add_argument(
        "--master",
        default=str(
            MASTER_RESUME_PATH
        ),
        help=(
            "Path to master_resume.json"
        ),
    )

    parser.add_argument(
        "--resume",
        default=None,
        help=(
            "Path to generated resume JSON"
        ),
    )

    parser.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print master profile summary."
        ),
    )

    return parser.parse_args()


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:

    print_header(
        "AI JOB APPLICATION & RESUME INTELLIGENCE"
    )

    print(
        f"{CYAN}RESUME FACT VALIDATOR{RESET}"
    )

    args = parse_arguments()

    master_path = Path(
        args.master
    )

    print()
    print(
        "Master profile:"
    )

    print(
        f"  {master_path.resolve()}"
    )

    # ------------------------------------------------------------------------
    # Load master
    # ------------------------------------------------------------------------

    try:

        master = load_json(
            master_path
        )

    except Exception as error:

        print(
            f"\n{RED}ERROR LOADING MASTER RESUME{RESET}"
        )

        print(
            error
        )

        return 1

    # ------------------------------------------------------------------------
    # Master self-check
    # ------------------------------------------------------------------------

    print_header(
        "MASTER PROFILE SELF-CHECK"
    )

    master_result = master_self_check(
        master
    )

    if master_result["passed"]:

        print(
            f"{GREEN}✓ MASTER SCHEMA VALID{RESET}"
        )

    else:

        print_validation_result(
            master_result
        )

        print(
            f"\n{RED}"
            "Master profile is not safe to use."
            f"{RESET}"
        )

        return 1

    print_master_summary(
        master
    )

    # ------------------------------------------------------------------------
    # No candidate supplied
    # ------------------------------------------------------------------------

    if not args.resume:

        print_header(
            "VALIDATOR READY"
        )

        print(
            "No generated resume supplied."
        )

        print(
            "\nMaster resume has passed the schema check."
        )

        print(
            "\nThe validator is now ready to validate "
            "AI-generated resumes."
        )

        print(
            "\nExample:"
        )

        print(
            "python resume_validator.py "
            "--resume generated_resumes/generated_resume.json"
        )

        print(
            f"\n{GREEN}STATUS: READY{RESET}"
        )

        return 0

    # ------------------------------------------------------------------------
    # Candidate
    # ------------------------------------------------------------------------

    candidate_path = Path(
        args.resume
    )

    print_header(
        "GENERATED RESUME VALIDATION"
    )

    print(
        "Candidate:"
    )

    print(
        f"  {candidate_path.resolve()}"
    )

    try:

        candidate = load_json(
            candidate_path
        )

    except Exception as error:

        print(
            f"\n{RED}ERROR LOADING CANDIDATE RESUME{RESET}"
        )

        print(
            error
        )

        return 1

    result = validate_candidate(
        master,
        candidate,
    )

    print_validation_result(
        result
    )

    # ------------------------------------------------------------------------
    # Final decision
    # ------------------------------------------------------------------------

    if result["passed"]:

        print()
        print_separator()

        print(
            f"{GREEN}"
            "✓ SAFE TO GENERATE FINAL RESUME"
            f"{RESET}"
        )

        print_separator()

        if result["warnings"]:

            print(
                f"\n{YELLOW}"
                "Review the warnings before submitting."
                f"{RESET}"
            )

        return 0

    print()
    print_separator()

    print(
        f"{RED}"
        "✗ DO NOT GENERATE FINAL RESUME"
        f"{RESET}"
    )

    print_separator()

    print(
        "\nFactual violations must be fixed "
        "before generating the final CV."
    )

    return 2


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )