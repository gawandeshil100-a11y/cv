"""
AI Job Application & Resume Intelligence - Pipeline Orchestrator

Pipeline:
    Job Selection -> Job Analysis -> Resume Customization
    -> Fact Validation -> DOCX/PDF Rendering

This module orchestrates the existing project modules only.
It does not author resume content.

Expected modules:
    job_analyzer.py
    resume_parser.py
    resume_customizer.py
    resume_validator.py
    resume_renderer.py
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib
import inspect
import json
import re
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from resume_customizer import build_customized_resume
from resume_validator import validate_candidate
from resume_renderer import create_docx, create_pdf


# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
RESUME_DATA_DIR = PROJECT_ROOT / "resume_data"
MASTER_RESUME_PATH = RESUME_DATA_DIR / "master_resume.json"
GENERATED_DIR = PROJECT_ROOT / "generated_resumes"

# The project currently has many CSV files in its root. These directories are
# scanned for job records.
JOB_SEARCH_DIRS: Tuple[Path, ...] = (
    PROJECT_ROOT / "job_data",
    PROJECT_ROOT / "jobs",
    PROJECT_ROOT / "analyzed_jobs",
    PROJECT_ROOT / "job_results",
    PROJECT_ROOT / "output",
    PROJECT_ROOT / "data",
    PROJECT_ROOT,
)

# If auto-discovery cannot identify one of your real functions, put its exact
# function name here. Leave None for automatic discovery.
FUNCTION_OVERRIDES: Dict[str, Optional[str]] = {
    "analyze_job": None,
    "load_master": None,
    "customize": None,
    "validate": None,
    "render_all": None,
    "render_docx": None,
    "render_pdf": None,
}

FUNCTION_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "analyze_job": (
        "analyze_job", "analyse_job", "analyze", "analyse",
        "analyze_job_description", "extract_job_requirements",
        "extract_keywords", "get_job_analysis", "run_analysis",
        "score_job", "parse_job",
    ),
    "load_master": (
        "load_master_resume", "load_master", "parse_master_resume",
        "load_resume", "parse_resume", "read_master_resume",
        "get_master_resume", "load_profile",
    ),
    "customize": (
        "customize_resume", "customise_resume",
        "generate_customized_resume", "generate_customised_resume",
        "build_customized_resume", "tailor_resume", "customize",
        "customise", "run_customization", "create_customized_resume",
        "adapt_resume",
    ),
    "validate": (
        "validate_resume", "validate_customized_resume",
        "run_validation", "validate_customization", "validate",
        "check_resume", "run_fact_validation", "verify_resume",
        "validate_facts", "run_validator",
    ),
    "render_all": (
        "render_resume", "render", "generate_resume", "build_resume",
        "render_all", "generate_documents", "export_resume",
        "render_documents",
    ),
    "render_docx": (
        "render_docx", "generate_docx", "build_docx", "create_docx",
        "export_docx", "to_docx", "write_docx", "render_word",
    ),
    "render_pdf": (
        "render_pdf", "generate_pdf", "build_pdf", "create_pdf",
        "export_pdf", "to_pdf", "write_pdf", "convert_to_pdf",
    ),
}

MODULE_FOR_CAPABILITY = {
    "analyze_job": "job_analyzer",
    "load_master": "resume_parser",
    "customize": "resume_customizer",
    "validate": "resume_validator",
    "render_all": "resume_renderer",
    "render_docx": "resume_renderer",
    "render_pdf": "resume_renderer",
}

ARG_ALIASES: Dict[str, Tuple[str, ...]] = {
    "master": (
        "master", "masterresume", "masterdata", "masterprofile",
        "profile", "baseresume", "sourceresume", "masterjson",
        "resumedata", "base",
    ),
    "resume": (
        "resume", "customizedresume", "customisedresume", "resumejson",
        "tailoredresume", "generatedresume", "candidateresume",
        "data", "resumedict", "content",
    ),
    "job": (
        "job", "jobdata", "jobinfo", "jobdict", "jobrecord",
        "jobposting", "posting", "vacancy", "jd", "jobjson",
    ),
    "job_description": (
        "jobdescription", "description", "jdtext", "jobtext",
        "desc", "text", "rawdescription",
    ),
    "job_title": ("jobtitle", "title", "role", "position", "roletitle"),
    "company": ("company", "companyname", "employer", "organization", "org"),
    "analysis": (
        "analysis", "jobanalysis", "analysisresult", "requirements",
        "keywords", "jobkeywords", "analyzed", "analysisdata",
    ),
    "output_dir": (
        "outputdir", "outdir", "outputdirectory", "outputfolder",
        "destdir", "destination", "dest", "folder", "targetdir",
    ),
    "output_path": (
        "outputpath", "outpath", "path", "filepath", "file",
        "target", "savepath", "destpath",
    ),
    "docx_path": (
        "docxpath", "docx", "docxout", "docxfile", "wordpath",
        "outputdocx",
    ),
    "pdf_path": (
        "pdfpath", "pdf", "pdfout", "pdffile", "outputpdf",
    ),
}

LOCKED_SECTION_HINTS = (
    "personal", "personal_info", "personal_information", "contact",
    "contact_info", "profile_info", "identity",
    "education", "academics", "qualification", "qualifications",
    "experience", "work_experience", "employment",
    "internship", "internships", "training", "trainings",
    "virtual_job_simulations", "job_simulations", "simulations", "forage",
    "certification", "certifications", "certificates",
    "publication", "publications",
)

LOCKED_PROJECT_FIELDS = (
    "name", "title", "project_name", "project_title",
    "tech_stack", "technologies", "tools", "stack", "tech",
    "metrics", "metric", "results", "impact_metrics", "numbers", "stats",
    "rows", "records", "dataset_size", "accuracy", "duration", "dates",
    "start_date", "end_date", "year", "url", "github", "link", "repo",
)

CUSTOMIZABLE_SECTION_HINTS = (
    "summary", "professional_summary", "profile_summary", "objective",
    "about", "headline", "skills", "skill", "technical_skills",
    "core_skills",
)

DOC_EXTENSIONS = {".docx": "DOCX", ".pdf": "PDF"}
VERBOSE = False


# =============================================================================
# ERRORS / CONSOLE
# =============================================================================

class PipelineError(RuntimeError):
    pass


class AdapterError(PipelineError):
    pass


class ValidationFailure(PipelineError):
    def __init__(self, violations: Sequence[str], report: Dict[str, Any]):
        self.violations = list(violations)
        self.report = report
        super().__init__(f"{len(self.violations)} fact violation(s) detected")


def banner(text: str, char: str = "=", width: int = 72) -> None:
    print(char * width)
    print(text)
    print(char * width)


def stage(text: str) -> None:
    print()
    print("-" * 72)
    print(text)
    print("-" * 72)


def info(text: str) -> None:
    print(f"    {text}")


def ok(text: str) -> None:
    print(f"  [OK]   {text}")


def warn(text: str) -> None:
    print(f"  [WARN] {text}")


def fail(text: str) -> None:
    print(f"  [FAIL] {text}")


def debug(text: str) -> None:
    if VERBOSE:
        print(f"  [dbg]  {text}")


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# =============================================================================
# MODULE ADAPTER
# =============================================================================

class ModuleAdapter:
    def __init__(self) -> None:
        self.modules: Dict[str, Any] = {}
        self.resolved: Dict[str, Optional[Callable[..., Any]]] = {}

    def module(self, module_name: str) -> Any:
        if module_name in self.modules:
            return self.modules[module_name]

        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise AdapterError(
                f"Could not import '{module_name}.py'.\n"
                f"Expected location: {PROJECT_ROOT}\n"
                f"Underlying error: {exc}"
            ) from exc
        except Exception as exc:
            raise AdapterError(
                f"'{module_name}.py' failed during import: "
                f"{type(exc).__name__}: {exc}\n"
                "Make sure executable code is protected by "
                "`if __name__ == '__main__':`."
            ) from exc

        self.modules[module_name] = module
        return module

    @staticmethod
    def public_callables(module: Any) -> str:
        if module is None:
            return "<module not loaded>"
        names = [
            name for name in dir(module)
            if not name.startswith("_")
            and callable(getattr(module, name, None))
        ]
        return ", ".join(sorted(names)) or "<no public callables>"

    def resolve(
        self,
        capability: str,
        required: bool = True,
    ) -> Optional[Callable[..., Any]]:
        if capability in self.resolved:
            func = self.resolved[capability]
            if func is None and required:
                raise AdapterError(self.describe_failure(capability))
            return func

        module_name = MODULE_FOR_CAPABILITY[capability]
        module = self.module(module_name)

        override = FUNCTION_OVERRIDES.get(capability)
        if override:
            func = getattr(module, override, None)
            if not callable(func):
                raise AdapterError(
                    f"FUNCTION_OVERRIDES['{capability}'] = '{override}', "
                    f"but '{module_name}.py' has no such callable.\n"
                    f"Available: {self.public_callables(module)}"
                )
            self.resolved[capability] = func
            return func

        available = {
            normalize_name(name): name
            for name in dir(module)
            if not name.startswith("_")
        }

        for candidate in FUNCTION_CANDIDATES[capability]:
            real_name = available.get(normalize_name(candidate))
            if real_name:
                func = getattr(module, real_name, None)
                if callable(func):
                    self.resolved[capability] = func
                    debug(
                        f"{capability} -> "
                        f"{module_name}.{real_name}"
                    )
                    return func

        self.resolved[capability] = None
        if required:
            raise AdapterError(self.describe_failure(capability))
        return None

    def describe_failure(self, capability: str) -> str:
        module_name = MODULE_FOR_CAPABILITY[capability]
        module = self.modules.get(module_name)
        return (
            f"Could not resolve '{capability}' in '{module_name}.py'.\n"
            f"Searched for: {', '.join(FUNCTION_CANDIDATES[capability])}\n"
            f"Module exposes: {self.public_callables(module)}\n"
            f"Set FUNCTION_OVERRIDES['{capability}'] to the exact "
            "function name."
        )

    @staticmethod
    def match_param(
        param_name: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        wanted = normalize_name(param_name)

        for key in context:
            if normalize_name(key) == wanted:
                return key

        for key, aliases in ARG_ALIASES.items():
            if key not in context:
                continue
            if wanted in {normalize_name(x) for x in aliases}:
                return key

        return None

    @staticmethod
    def fallback_args(context: Dict[str, Any]) -> List[Any]:
        order = ("resume", "master", "job", "analysis", "output_dir")
        return [context[k] for k in order if k in context]

    def call(self, func: Callable[..., Any], context: Dict[str, Any]) -> Any:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return func(*self.fallback_args(context))

        args: List[Any] = []
        kwargs: Dict[str, Any] = []
        missing: List[str] = []

        for name, param in signature.parameters.items():
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            key = self.match_param(name, context)

            if key is None:
                if param.default is inspect.Parameter.empty:
                    missing.append(name)
                continue

            if param.kind == inspect.Parameter.POSITIONAL_ONLY:
                args.append(context[key])
            else:
                kwargs[name] = context[key]

        if missing:
            raise AdapterError(
                f"Cannot call {func.__module__}.{func.__name__}{signature}\n"
                f"Missing required parameters: {', '.join(missing)}\n"
                f"Available context keys: {', '.join(sorted(context))}\n"
                "Add an alias to ARG_ALIASES or use a compatible signature."
            )

        try:
            return func(*args, **kwargs)
        except TypeError as exc:
            raise AdapterError(
                f"{func.__name__}{signature} rejected the supplied arguments: "
                f"{exc}"
            ) from exc


ADAPTER = ModuleAdapter()


# =============================================================================
# JOB MODEL
# =============================================================================

JOB_FIELD_ALIASES = {
    "title": (
        "title", "job_title", "jobtitle", "position", "role", "designation"
    ),
    "company": (
        "company", "company_name", "employer", "organization", "companyname"
    ),
    "description": (
        "description", "job_description", "jobdescription", "jd",
        "details", "summary", "snippet", "text", "requirements"
    ),
    "location": (
        "location", "job_location", "city", "place", "area"
    ),
    "url": (
        "url", "link", "job_url", "apply_link", "joburl", "application_link"
    ),
    "skills": (
        "skills", "required_skills", "keywords", "tech_stack", "tags"
    ),
    "source": (
        "source", "portal", "site", "platform", "job_board"
    ),
    "posted": (
        "posted", "date", "posted_date", "date_posted", "published"
    ),
    "match_score": (
        "match_score", "score", "relevance", "match", "fit_score"
    ),
}


@dataclass
class Job:
    title: str = ""
    company: str = ""
    description: str = ""
    location: str = ""
    url: str = ""
    skills: str = ""
    source: str = ""
    posted: str = ""
    match_score: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    origin: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "company": self.company,
            "description": self.description,
            "location": self.location,
            "url": self.url,
            "skills": self.skills,
            "source": self.source,
            "posted": self.posted,
            "match_score": self.match_score,
            "origin": self.origin,
            "raw": self.raw,
        }

    def label(self) -> str:
        result = self.title or "<untitled>"
        if self.company:
            result += f" @ {self.company}"
        if self.location:
            result += f" ({self.location})"
        return result

    def usable(self) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        if not self.title.strip():
            errors.append("missing job title")
        if not self.company.strip():
            errors.append("missing company name")
        if len(self.description.strip()) < 40:
            errors.append("job description is empty/too short (<40 chars)")
        return not errors, errors


def pick_field(row: Dict[str, Any], canonical: str) -> str:
    normalized = {
        normalize_name(k): v for k, v in row.items()
    }

    for alias in JOB_FIELD_ALIASES[canonical]:
        value = normalized.get(normalize_name(alias))
        if value is None:
            continue

        if isinstance(value, (list, tuple)):
            value = ", ".join(map(str, value))
        elif isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)

        text = str(value).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text

    return ""


def job_from_record(row: Dict[str, Any], origin: str) -> Job:
    return Job(
        title=pick_field(row, "title"),
        company=pick_field(row, "company"),
        description=pick_field(row, "description"),
        location=pick_field(row, "location"),
        url=pick_field(row, "url"),
        skills=pick_field(row, "skills"),
        source=pick_field(row, "source"),
        posted=pick_field(row, "posted"),
        match_score=pick_field(row, "match_score"),
        raw=dict(row),
        origin=origin,
    )


def discover_job_files() -> List[Path]:
    found: List[Path] = []
    seen: set[Path] = set()

    excluded = {
        "customized_resume.json",
        "validation_report.json",
        "job.json",
        "job_analysis.json",
    }

    for directory in JOB_SEARCH_DIRS:
        if not directory.is_dir():
            continue

        for pattern in ("*.csv", "*.json"):
            for path in sorted(directory.glob(pattern)):
                resolved = path.resolve()

                if resolved in seen:
                    continue
                if resolved == MASTER_RESUME_PATH.resolve():
                    continue
                if GENERATED_DIR.resolve() in resolved.parents:
                    continue
                if path.name.lower() in excluded:
                    continue

                seen.add(resolved)
                found.append(path)

    return found


def load_jobs_from_file(path: Path) -> List[Job]:
    try:
        if path.suffix.lower() == ".csv":
            with path.open(
                "r", encoding="utf-8-sig", newline=""
            ) as fh:
                return [
                    job_from_record(row, str(path))
                    for row in csv.DictReader(fh)
                    if row
                ]

        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)

            if isinstance(payload, list):
                return [
                    job_from_record(item, str(path))
                    for item in payload
                    if isinstance(item, dict)
                ]

            if isinstance(payload, dict):
                for key in ("jobs", "results", "data", "items", "records"):
                    items = payload.get(key)
                    if isinstance(items, list):
                        return [
                            job_from_record(item, str(path))
                            for item in items
                            if isinstance(item, dict)
                        ]
                return [job_from_record(payload, str(path))]

    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        warn(f"Could not parse {path.name}: {exc}")

    return []


def collect_all_jobs() -> List[Job]:
    jobs: List[Job] = []

    for path in discover_job_files():
        loaded = load_jobs_from_file(path)
        usable = [
            job for job in loaded
            if job.title.strip() or job.company.strip()
        ]
        if usable:
            debug(f"{path.name}: {len(usable)} job(s)")
            jobs.extend(usable)

    return jobs


def manual_job_entry() -> Job:
    print()
    info("Manual job entry")
    title = input("    Job title   : ").strip()
    company = input("    Company     : ").strip()
    location = input("    Location    : ").strip()
    url = input("    Job URL     : ").strip()

    print("    Paste job description. Type END on its own line.")
    lines: List[str] = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)

    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        description="\n".join(lines).strip(),
        source="manual",
        origin="manual entry",
    )


def choose_job(jobs: Sequence[Job]) -> Job:
    if not jobs:
        warn("No job files found. Falling back to manual entry.")
        return manual_job_entry()

    print()
    info(f"{len(jobs)} job(s) available:")
    print()

    for i, job in enumerate(jobs, 1):
        score = f" [score {job.match_score}]" if job.match_score else ""
        print(f"  {i:4}. {job.label()}{score}")
        print(f"         source: {job.origin}")

    print()
    print("     m. Manual job entry")
    print("     q. Quit")
    print()

    while True:
        choice = input("  Select job number: ").strip().lower()

        if choice in {"q", "quit", "exit"}:
            raise PipelineError("Job selection cancelled by user.")

        if choice in {"m", "manual"}:
            return manual_job_entry()

        if choice.isdigit() and 1 <= int(choice) <= len(jobs):
            return jobs[int(choice) - 1]

        print("  Invalid selection.")


def load_job_from_path(
    path: Path,
    title: str = "",
    company: str = "",
) -> Job:
    if not path.exists():
        raise PipelineError(f"Job file not found: {path}")

    if path.suffix.lower() in {".csv", ".json"}:
        jobs = load_jobs_from_file(path)
        if not jobs:
            raise PipelineError(f"No job record could be read from {path}")
        job = jobs[0]
        if len(jobs) > 1:
            warn(f"{path.name} contains {len(jobs)} records; using the first.")
    else:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise PipelineError(f"Could not read {path}: {exc}") from exc
        job = Job(description=text, source="file", origin=str(path))

    if title:
        job.title = title
    if company:
        job.company = company

    return job


# =============================================================================
# MASTER RESUME / FACT INTEGRITY
# =============================================================================

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_master_resume() -> Tuple[Dict[str, Any], str]:
    if not MASTER_RESUME_PATH.exists():
        raise PipelineError(
            f"Master resume not found:\n{MASTER_RESUME_PATH}\n"
            "Create resume_data/master_resume.json first."
        )

    checksum = sha256_file(MASTER_RESUME_PATH)

    loader = ADAPTER.resolve("load_master", required=False)
    master: Optional[Dict[str, Any]] = None

    if loader is not None:
        try:
            result = ADAPTER.call(
                loader,
                {
                    "master": MASTER_RESUME_PATH,
                    "path": MASTER_RESUME_PATH,
                    "output_path": MASTER_RESUME_PATH,
                },
            )
            if isinstance(result, dict):
                master = result
            elif (
                isinstance(result, (list, tuple))
                and result
                and isinstance(result[0], dict)
            ):
                master = result[0]
        except Exception as exc:
            debug(
                f"resume_parser loader not usable: "
                f"{type(exc).__name__}: {exc}"
            )

    if master is None:
        try:
            with MASTER_RESUME_PATH.open("r", encoding="utf-8") as fh:
                master = json.load(fh)
        except json.JSONDecodeError as exc:
            raise PipelineError(
                f"Invalid master_resume.json: line {exc.lineno}, "
                f"column {exc.colno}: {exc.msg}"
            ) from exc

    if not isinstance(master, dict):
        raise PipelineError("master_resume.json must contain a JSON object.")

    return master, checksum


def assert_master_untouched(checksum: str) -> None:
    current = sha256_file(MASTER_RESUME_PATH)
    if current != checksum:
        raise PipelineError(
            "INTEGRITY FAILURE: master_resume.json changed during the run."
        )
    ok("master_resume.json unchanged (SHA-256 verified)")


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): canonical(v)
            for k, v in sorted(value.items(), key=lambda x: str(x[0]))
        }
    if isinstance(value, list):
        return [canonical(x) for x in value]
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


def shorten(value: Any, limit: int = 80) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def locked_key(key: str) -> bool:
    n = normalize_name(key)
    return any(
        normalize_name(x) in n or n in normalize_name(x)
        for x in LOCKED_SECTION_HINTS
    )


def customizable_key(key: str) -> bool:
    n = normalize_name(key)
    return any(
        normalize_name(x) in n or n in normalize_name(x)
        for x in CUSTOMIZABLE_SECTION_HINTS
    )


def diff_nodes(
    before: Any,
    after: Any,
    path: str,
    violations: List[str],
) -> None:
    if type(before) is not type(after):
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            violations.append(
                f"{path}: type changed "
                f"{type(before).__name__} -> {type(after).__name__}"
            )
            return

    if isinstance(before, dict):
        if not isinstance(after, dict):
            violations.append(f"{path}: expected object")
            return

        for key in before:
            if key not in after:
                violations.append(f"{path}.{key}: REMOVED")
            else:
                diff_nodes(before[key], after[key], f"{path}.{key}", violations)

        for key in after:
            if key not in before:
                violations.append(f"{path}.{key}: ADDED")
        return

    if isinstance(before, list):
        if not isinstance(after, list):
            violations.append(f"{path}: expected list")
            return

        if len(before) != len(after):
            violations.append(
                f"{path}: list length changed {len(before)} -> {len(after)}"
            )

        for i in range(min(len(before), len(after))):
            diff_nodes(before[i], after[i], f"{path}[{i}]", violations)
        return

    if canonical(before) != canonical(after):
        violations.append(
            f"{path}: value changed "
            f"{shorten(before)!r} -> {shorten(after)!r}"
        )


def project_identity(project: Any) -> str:
    if not isinstance(project, dict):
        return str(project)

    for key in ("name", "title", "project_name", "project_title"):
        value = project.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value).strip().lower()

    return json.dumps(canonical(project), sort_keys=True)[:120]


def check_project_facts(
    master: Dict[str, Any],
    customized: Dict[str, Any],
) -> List[str]:
    violations: List[str] = []
    locked_fields = {normalize_name(x) for x in LOCKED_PROJECT_FIELDS}

    for key, master_projects in master.items():
        if "project" not in normalize_name(key) or not isinstance(master_projects, list):
            continue

        custom_projects = customized.get(key)
        if not isinstance(custom_projects, list):
            violations.append(f"{key}: project section is not a list")
            continue

        if len(custom_projects) > len(master_projects):
            violations.append(
                f"{key}: customized resume has more projects than master"
            )

        index = {
            project_identity(x): x
            for x in master_projects
            if isinstance(x, dict)
        }

        for i, project in enumerate(custom_projects):
            if not isinstance(project, dict):
                continue

            identity = project_identity(project)
            source = index.get(identity)

            if source is None:
                violations.append(
                    f"{key}[{i}]: project '{identity}' does not exist in master"
                )
                continue

            for field_name, value in project.items():
                if normalize_name(field_name) not in locked_fields:
                    continue

                if field_name not in source:
                    violations.append(
                        f"{key}[{i}].{field_name}: factual field added"
                    )
                else:
                    diff_nodes(
                        source[field_name],
                        value,
                        f"{key}[{i}].{field_name}",
                        violations,
                    )

    return violations


def check_locked_sections(
    master: Dict[str, Any],
    customized: Dict[str, Any],
) -> List[str]:
    violations: List[str] = []

    for key, value in master.items():
        if not locked_key(key) or customizable_key(key):
            continue

        if key not in customized:
            violations.append(f"LOCKED section '{key}' is missing")
            continue

        diff_nodes(value, customized[key], key, violations)

    for key in customized:
        if key not in master and locked_key(key):
            violations.append(
                f"LOCKED section '{key}' was added but is not in master"
            )

    violations.extend(check_project_facts(master, customized))
    return violations


# =============================================================================
# VALIDATOR NORMALIZATION
# =============================================================================

PASS_KEYS = (
    "passed", "valid", "is_valid", "ok", "success", "clean", "approved"
)

VIOLATION_KEYS = (
    "violations", "errors", "issues", "failures", "problems",
    "fact_errors", "conflicts", "warnings_fatal"
)


def string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [
            f"{k}: {shorten(v, 200)}"
            for k, v in value.items()
        ]
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            if isinstance(item, dict):
                result.append(
                    "; ".join(f"{k}={shorten(v, 120)}" for k, v in item.items())
                )
            else:
                result.append(str(item))
        return [x for x in result if x.strip()]
    return [str(value)]


def normalize_validation_result(
    result: Any,
) -> Tuple[Optional[bool], List[str], Any]:
    if isinstance(result, bool):
        return result, ([] if result else ["validator returned False"]), result

    if result is None:
        return None, [], result

    if isinstance(result, tuple) and len(result) == 2:
        a, b = result
        if isinstance(a, bool):
            return a, string_list(b), result
        if isinstance(b, bool):
            return b, string_list(a), result

    if isinstance(result, list):
        errors = string_list(result)
        return len(errors) == 0, errors, result

    if isinstance(result, dict):
        passed: Optional[bool] = None
        for key in PASS_KEYS:
            if isinstance(result.get(key), bool):
                passed = result[key]
                break

        errors: List[str] = []
        for key in VIOLATION_KEYS:
            if key in result:
                errors.extend(string_list(result[key]))

        if passed is None and errors:
            passed = False
        elif passed is None and any(k in result for k in VIOLATION_KEYS):
            passed = True

        return passed, errors, result

    for key in PASS_KEYS:
        value = getattr(result, key, None)
        if isinstance(value, bool):
            errors = []
            for error_key in VIOLATION_KEYS:
                value2 = getattr(result, error_key, None)
                if value2 is not None:
                    errors.extend(string_list(value2))
            return value, errors, result

    return None, [], result


# =============================================================================
# OUTPUT / STAGES
# =============================================================================

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(
                payload, fh, indent=2,
                ensure_ascii=False, default=str
            )
    except OSError as exc:
        raise PipelineError(f"Could not write {path}: {exc}") from exc


def slugify(text: str, limit: int = 60) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:limit] or "Unknown"


def build_output_dir(job: Job, overwrite: bool) -> Path:
    name = f"{slugify(job.title)}_{slugify(job.company)}"
    target = GENERATED_DIR / name

    if target.exists() and not overwrite:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = GENERATED_DIR / f"{name}_{stamp}"

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PipelineError(
            f"Could not create output directory {target}: {exc}"
        ) from exc

    return target


def documents(directory: Path) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    if not directory.exists():
        return result

    for path in directory.iterdir():
        if path.is_file():
            label = DOC_EXTENSIONS.get(path.suffix.lower())
            if label and label not in result:
                result[label] = path

    return result


def document_names(directory: Path) -> set[str]:
    return {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in DOC_EXTENSIONS
    }


def analyze_job(job: Job) -> Any:
    stage("[2/6] JOB ANALYSIS")

    func = ADAPTER.resolve("analyze_job", required=False)
    if func is None:
        warn("No recognized analysis function found; using raw job data.")
        return None

    try:
        result = ADAPTER.call(
            func,
            {
                "job": job.to_dict(),
                "job_description": job.description,
                "job_title": job.title,
                "company": job.company,
            },
        )
        ok(f"Analysis completed using {func.__name__}")
        return result
    except AdapterError:
        raise
    except Exception as exc:
        warn(f"Job analysis failed: {type(exc).__name__}: {exc}")
        if VERBOSE:
            traceback.print_exc()
        return None


def customize_resume(
    master: Dict[str, Any],
    job: Job,
    analysis: Any,
) -> Dict[str, Any]:
    """Call the project's real customizer directly."""
    stage("[3/6] RESUME CUSTOMIZATION")

    try:
        # IMPORTANT: build_customized_resume expects exactly:
        #   master resume dict
        #   job-description string
        result = build_customized_resume(
            master,
            job.description,
        )
    except Exception as exc:
        raise PipelineError(
            "resume_customizer.build_customized_resume() failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(result, dict):
        raise PipelineError(
            "build_customized_resume() must return a dictionary; "
            f"got {type(result).__name__}."
        )

    ok(f"Customized resume built ({len(result)} top-level sections)")
    return result

def validate_resume(
    master: Dict[str, Any],
    customized: Dict[str, Any],
    job: Job,
    output_dir: Path,
) -> Dict[str, Any]:
    stage("[4/6] FACT VALIDATION")

    locked_errors = check_locked_sections(
        master,
        customized,
    )

    if locked_errors:
        fail(
            f"Independent fact guard: {len(locked_errors)} violation(s)"
        )
    else:
        ok("Independent fact guard: PASSED")

    try:
        # IMPORTANT: validate_candidate expects exactly:
        #   master resume dict
        #   customized resume dict
        raw = validate_candidate(
            master,
            customized,
        )
    except Exception as exc:
        raise PipelineError(
            "resume_validator.validate_candidate() failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise PipelineError(
            "validate_candidate() must return a dictionary; "
            f"got {type(raw).__name__}."
        )

    passed = bool(raw.get("passed", False))
    validator_errors = raw.get("errors", [])
    validator_warnings = raw.get("warnings", [])

    if not isinstance(validator_errors, list):
        validator_errors = [str(validator_errors)]
    if not isinstance(validator_warnings, list):
        validator_warnings = [str(validator_warnings)]

    if passed:
        ok("resume_validator: PASSED")
    else:
        fail(
            f"resume_validator: FAILED ({len(validator_errors)} error(s))"
        )

    if validator_warnings:
        warn(
            f"resume_validator warnings: {len(validator_warnings)}"
        )

    all_errors = (
        [f"[fact guard] {x}" for x in locked_errors]
        + [f"[resume_validator] {x}" for x in validator_errors]
    )

    overall = passed and not locked_errors

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job": {
            "title": job.title,
            "company": job.company,
            "origin": job.origin,
        },
        "master_resume": str(MASTER_RESUME_PATH),
        "overall_result": "PASS" if overall else "FAIL",
        "locked_section_guard": {
            "passed": not locked_errors,
            "violations": locked_errors,
        },
        "resume_validator": raw,
        "all_violations": all_errors,
    }

    write_json(
        output_dir / "validation_report.json",
        report,
    )

    if not overall:
        raise ValidationFailure(
            all_errors,
            report,
        )

    ok("FACT VALIDATION PASSED -- rendering authorized")
    return report

def render_resume(
    customized: Dict[str, Any],
    job: Job,
    output_dir: Path,
) -> Dict[str, Path]:
    stage("[5/6] RESUME RENDERING")

    docx_path = output_dir / "resume.docx"
    pdf_path = output_dir / "resume.pdf"

    try:
        # IMPORTANT: the real renderer APIs are:
        #   create_docx(data, output_path)
        #   create_pdf(data, output_path)
        create_docx(
            customized,
            docx_path,
        )
        ok(f"DOCX created: {docx_path.name}")

        create_pdf(
            customized,
            pdf_path,
        )
        ok(f"PDF created: {pdf_path.name}")

    except Exception as exc:
        raise PipelineError(
            "resume_renderer failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not docx_path.exists():
        raise PipelineError(
            "Renderer returned without creating the DOCX file."
        )

    if not pdf_path.exists():
        raise PipelineError(
            "Renderer returned without creating the PDF file."
        )

    return {
        "DOCX": docx_path,
        "PDF": pdf_path,
    }


# =============================================================================
# CLI / MAIN
# =============================================================================

def print_validation_failure(errors: Sequence[str]) -> None:
    print()
    banner("PIPELINE HALTED -- FACT VALIDATION FAILED", "!")
    print()
    print("No validated DOCX/PDF was authorized.")
    print()
    for i, error in enumerate(errors, 1):
        print(f"  {i:3}. {error}")
    print()
    print(
        "Review validation_report.json and resume_customizer.py. "
        "Do not edit master_resume.json just to bypass validation."
    )


def print_final(
    job: Job,
    output_dir: Path,
    produced: Dict[str, Path],
    report: Dict[str, Any],
) -> None:
    stage("[6/6] FINAL OUTPUT")

    print(f"    Job        : {job.title}")
    print(f"    Company    : {job.company}")
    print(f"    Validation : {report['overall_result']}")
    print(f"    Folder     : {output_dir}")
    print()

    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            kb = path.stat().st_size / 1024
            print(f"      - {path.name:<30} {kb:8.1f} KB")

    missing = [
        label for label in DOC_EXTENSIONS.values()
        if label not in produced
    ]
    if missing:
        warn(f"Not produced: {', '.join(missing)}")

    print()
    banner("PIPELINE COMPLETE")


def list_jobs() -> int:
    banner("DISCOVERED JOBS")
    jobs = collect_all_jobs()

    if not jobs:
        warn("No job records found.")
        return 1

    for i, job in enumerate(jobs, 1):
        print(f"{i:4}. {job.label()}")
        print(f"      {job.origin}")

    print()
    print("Run: python pipeline.py --index N")
    return 0


def run_pipeline(args: argparse.Namespace) -> int:
    banner("AI JOB APPLICATION INTELLIGENCE -- PIPELINE")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. JOB
    stage("[1/6] JOB SELECTED")

    if args.job:
        job = load_job_from_path(
            Path(args.job).expanduser(),
            args.title,
            args.company,
        )
    elif args.manual:
        job = manual_job_entry()
    else:
        jobs = collect_all_jobs()
        if args.index is not None:
            if not 1 <= args.index <= len(jobs):
                raise PipelineError(
                    f"--index {args.index} is out of range; "
                    f"{len(jobs)} jobs found."
                )
            job = jobs[args.index - 1]
        else:
            job = choose_job(jobs)

        if args.title:
            job.title = args.title
        if args.company:
            job.company = args.company

    usable, problems = job.usable()
    if not usable:
        raise PipelineError(
            "Selected job is incomplete: " + "; ".join(problems)
        )

    ok(job.label())
    info(f"Source: {job.origin}")
    info(f"Description: {len(job.description)} characters")

    # MASTER
    master, checksum = load_master_resume()
    ok(f"Master profile loaded ({len(master)} top-level sections)")

    # OUTPUT
    output_dir = build_output_dir(job, args.overwrite)
    info(f"Output folder: {output_dir}")

    if args.dry_run:
        write_json(output_dir / "job.json", job.to_dict())
        ok("Dry run complete.")
        return 0

    # 2. ANALYSIS
    analysis = analyze_job(job)
    write_json(output_dir / "job.json", job.to_dict())
    if analysis is not None:
        write_json(output_dir / "job_analysis.json", analysis)

    # 3. CUSTOMIZATION
    customized = customize_resume(master, job, analysis)
    write_json(output_dir / "customized_resume.json", customized)

    # 4. VALIDATION
    report = validate_resume(
        master, customized, job, output_dir
    )

    # 5. RENDERING
    produced = render_resume(
        customized, job, output_dir
    )

    # Master must remain immutable.
    assert_master_untouched(checksum)

    # 6. FINAL
    print_final(job, output_dir, produced, report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Job selection -> analysis -> resume customization -> "
            "fact validation -> DOCX/PDF rendering"
        )
    )

    parser.add_argument("--job", metavar="PATH")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--index", type=int, metavar="N")
    parser.add_argument("--list", action="store_true", dest="list_jobs")
    parser.add_argument("--title", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    global VERBOSE

    parser = build_parser()
    args = parser.parse_args(argv)
    VERBOSE = args.verbose

    if args.list_jobs:
        return list_jobs()

    if args.job and args.manual:
        parser.error("--job and --manual cannot be used together.")

    if args.index is not None and (args.job or args.manual):
        parser.error("--index cannot be combined with --job/--manual.")

    try:
        return run_pipeline(args)
    except ValidationFailure as exc:
        print_validation_failure(exc.violations)
        return 2
    except KeyboardInterrupt:
        print()
        warn("Interrupted by user.")
        return 3
    except AdapterError as exc:
        print()
        banner("MODULE API COULD NOT BE RESOLVED", "!")
        print(exc)
        if VERBOSE:
            traceback.print_exc()
        return 1
    except PipelineError as exc:
        print()
        banner("PIPELINE ERROR", "!")
        print(exc)
        if VERBOSE:
            traceback.print_exc()
        return 1
    except Exception as exc:
        print()
        banner("UNEXPECTED ERROR", "!")
        print(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())