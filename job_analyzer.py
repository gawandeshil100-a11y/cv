"""
job_analyzer.py
===============

AI Job Application Intelligence Platform - ANALYZER stage.

Reads job_results.csv (produced by job_search.py), removes duplicates,
rejects search/listing/category pages, optionally fetches each individual
job page, extracts structured data (JSON-LD JobPosting where available),
classifies REQUIRED EXPERIENCE with an evidence-based parser, scores
role / location / experience / skills / freshness, and produces a final
decision for a FRESHER profile.

Design rules enforced:
  * Numeric experience evidence beats vague seniority wording.
  * "Senior" in the title, with no numeric evidence, => Senior / Experienced.
  * Missing experience is NEVER treated as "Fresher"  -> "Other / Unknown".
  * Missing date is NEVER treated as fresh            -> "Freshness unknown".
  * Skill score can NEVER make a senior/high-experience job eligible.
  * Rejected jobs are never counted as accepted.
  * Nothing is invented: every decision carries the evidence string used.

Usage:
    python job_analyzer.py
    python job_analyzer.py --no-fetch
    python job_analyzer.py --input job_results.csv --outdir . --limit 50
    python job_analyzer.py --selftest

Dependencies (all optional except the standard library):
    requests, beautifulsoup4, pandas, python-dotenv, lxml
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# --------------------------------------------------------------------------
# OPTIONAL DEPENDENCIES (degrade gracefully, never crash)
# --------------------------------------------------------------------------

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None


# --------------------------------------------------------------------------
# CONFIGURATION  (edit this block only)
# --------------------------------------------------------------------------

TARGET_ROLE = "Data Analyst"
TARGET_CITY = "Pune"
TARGET_COUNTRY = "India"
PROFILE_IS_FRESHER = True

RESUME_SKILLS = [
    "Python", "SQL", "Excel", "Power BI", "Tableau", "Snowflake",
    "Pandas", "NumPy", "Machine Learning", "Statistics", "Data Analysis",
    "Streamlit", "ETL", "Data Engineering", "LangChain",
]

WEIGHTS = {
    "role": 0.25,
    "location": 0.15,
    "experience": 0.30,
    "skills": 0.20,
    "freshness": 0.10,
}

INPUT_FILE = "job_results.csv"
OUTPUT_DIR = "."

FETCH_TIMEOUT = 15
FETCH_DELAY = 1.2          # seconds between requests (be polite)
FETCH_RETRIES = 2
STALE_DOES_NOT_REJECT = True   # old jobs lose priority, they are not rejected

USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
]


# --------------------------------------------------------------------------
# EXPERIENCE CATEGORIES  (exact strings required by the spec)
# --------------------------------------------------------------------------

EXP_0 = "0 years"
EXP_0_1 = "0-1 years"
EXP_0_2 = "0-2 years"
EXP_0_3 = "0-3 years"
EXP_1_2 = "1-2 years"
EXP_1_3 = "1-3 years"
EXP_2_4 = "2-4 years"
EXP_3_5 = "3-5 years"
EXP_3P = "3+ years"
EXP_4P = "4+ years"
EXP_5P = "5+ years"
EXP_SENIOR = "Senior / Experienced"
EXP_UNKNOWN = "Other / Unknown"

EXPERIENCE_CATEGORIES = [
    EXP_0, EXP_0_1, EXP_0_2, EXP_0_3, EXP_1_2, EXP_1_3,
    EXP_2_4, EXP_3_5, EXP_3P, EXP_4P, EXP_5P, EXP_SENIOR, EXP_UNKNOWN,
]

ELIGIBLE_EXP = {EXP_0, EXP_0_1, EXP_0_2, EXP_0_3}
CONSIDER_EXP = {EXP_1_2, EXP_1_3}
TOO_HIGH_EXP = {EXP_2_4, EXP_3_5, EXP_3P, EXP_4P, EXP_5P}

EXPERIENCE_SCORE = {
    EXP_0: 100, EXP_0_1: 100, EXP_0_2: 95, EXP_0_3: 88,
    EXP_1_2: 70, EXP_1_3: 60,
    EXP_2_4: 20, EXP_3_5: 10, EXP_3P: 10, EXP_4P: 5, EXP_5P: 0,
    EXP_SENIOR: 0, EXP_UNKNOWN: 50,
}

# used for sorting "experience fit"
EXPERIENCE_RANK = {
    EXP_0: 10, EXP_0_1: 10, EXP_0_2: 9, EXP_0_3: 8,
    EXP_1_2: 6, EXP_1_3: 5, EXP_UNKNOWN: 4,
    EXP_2_4: 2, EXP_3_5: 1, EXP_3P: 1, EXP_4P: 0, EXP_5P: 0, EXP_SENIOR: 0,
}


# --------------------------------------------------------------------------
# FRESHNESS CATEGORIES
# --------------------------------------------------------------------------

FRESH_24 = "Within 24 hours"
FRESH_48 = "24-48 hours"
FRESH_OLD_48 = "Older than 48 hours"
FRESH_OLD_7 = "Older than 7 days"
FRESH_OLD_30 = "Older than 30 days"
FRESH_UNKNOWN = "Freshness unknown"

FRESHNESS_CATEGORIES = [
    FRESH_24, FRESH_48, FRESH_OLD_48, FRESH_OLD_7, FRESH_OLD_30, FRESH_UNKNOWN,
]

FRESHNESS_SCORE = {
    FRESH_24: 100, FRESH_48: 85, FRESH_OLD_48: 65,
    FRESH_OLD_7: 45, FRESH_OLD_30: 20,
    FRESH_UNKNOWN: 40,          # never treated as fresh
}

FRESHNESS_RANK = {
    FRESH_24: 5, FRESH_48: 4, FRESH_OLD_48: 3,
    FRESH_OLD_7: 2, FRESH_UNKNOWN: 1, FRESH_OLD_30: 0,
}


# --------------------------------------------------------------------------
# RECOMMENDATION LEVELS
# --------------------------------------------------------------------------

REC_HIGH = "🟢 HIGH PRIORITY - APPLY"
REC_APPLY = "🟢 APPLY"
REC_CONSIDER = "🟡 CONSIDER"
REC_LOW = "🟠 LOW PRIORITY"
REC_REJ_EXP = "🔴 REJECT - EXPERIENCE TOO HIGH"
REC_REJ_SENIOR = "🔴 REJECT - SENIOR / EXPERIENCED"
REC_REJ_LOC = "🔴 REJECT - WRONG LOCATION"
REC_REJ_ROLE = "🔴 REJECT - WRONG ROLE"
REC_REJ_LISTING = "🔴 REJECT - INVALID LISTING"
REC_REJ_DATA = "🔴 REJECT - INSUFFICIENT DATA"

REJECTIONS = {
    REC_REJ_EXP, REC_REJ_SENIOR, REC_REJ_LOC,
    REC_REJ_ROLE, REC_REJ_LISTING, REC_REJ_DATA,
}

RECOMMENDATION_RANK = {
    REC_HIGH: 5, REC_APPLY: 4, REC_CONSIDER: 3, REC_LOW: 2,
}


def is_rejected(recommendation: str) -> bool:
    """Single source of truth: a job is accepted only if not rejected."""
    return recommendation in REJECTIONS


# --------------------------------------------------------------------------
# SAFE CONSOLE OUTPUT (Windows / PyCharm friendly)
# --------------------------------------------------------------------------

def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def say(text: str = "") -> None:
    """print() that survives consoles which cannot render emoji."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(re.sub(r"[^\x00-\x7F]+", "", text).strip())


# --------------------------------------------------------------------------
# TEXT HELPERS
# --------------------------------------------------------------------------

WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"nan", "none", "null"}:
        return ""
    text = text.replace("\xa0", " ").replace("\u200b", "")
    return WHITESPACE_RE.sub(" ", text).strip()


def lower(value: Any) -> str:
    return clean_text(value).lower()


def fold(value: Any) -> str:
    """
    Strip accents so that 'Sênior' matches 'senior', 'Bengalūru' matches
    'bengaluru', etc. Used for MATCHING only - the original text is what
    gets written to the CSVs.
    """
    text = clean_text(value)
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return (stripped.replace("\u2013", "-").replace("\u2014", "-")
                    .replace("\u2019", "'").replace("\u00a0", " "))


def truncate(text: str, limit: int = 4000) -> str:
    text = clean_text(text)
    return text if len(text) <= limit else text[:limit] + " ..."


# --------------------------------------------------------------------------
# URL NORMALISATION + DEDUPLICATION
# --------------------------------------------------------------------------

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referer", "referrer", "source", "src", "trk", "trkinfo",
    "originalsubdomain", "position", "pagenum", "refid", "gclid", "fbclid",
    "gh_src", "sid", "cid", "campaign", "medium", "recommended",
    "savedsearchid", "eboa", "eboa_source",
}

KEEP_PARAMS = {"jk", "currentjobid", "vjk", "jobid", "job_id", "id", "jid", "gh_jid"}


def normalize_url(url: str) -> str:
    """Strip tracking params / fragments so the same job collapses to one row."""
    url = clean_text(url)
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    try:
        parts = urlparse(url)
    except Exception:
        return url.lower()

    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.startswith("m."):
        netloc = netloc[2:]

    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        key_l = key.lower()
        if key_l in TRACKING_PARAMS:
            continue
        if key_l in KEEP_PARAMS or len(query_pairs) < 4:
            query_pairs.append((key_l, value))
    query_pairs.sort()

    path = parts.path.rstrip("/")
    return urlunparse(("https", netloc, path, "", urlencode(query_pairs), ""))


JOB_ID_PATTERNS = [
    re.compile(r"linkedin\.com/jobs/view/(\d+)", re.I),
    re.compile(r"[?&]currentJobId=(\d+)", re.I),
    re.compile(r"[?&]jk=([0-9a-zA-Z]+)", re.I),
    re.compile(r"naukri\.com/job-listings-[^/?]*?-(\d{6,})", re.I),
    re.compile(r"/job/[^/?]*?-(\d{6,})", re.I),
    re.compile(r"[?&]gh_jid=(\d+)", re.I),
]


def extract_job_id(url: str) -> str:
    for pattern in JOB_ID_PATTERNS:
        match = pattern.search(url or "")
        if match:
            return match.group(1)
    return ""


def dedupe_key(row: Dict[str, Any]) -> str:
    url = normalize_url(row.get("job_url", ""))
    job_id = extract_job_id(url)
    if job_id:
        host = urlparse(url).netloc if url else ""
        return f"id::{host}::{job_id}"
    if url:
        return f"url::{url}"
    title = re.sub(r"[^a-z0-9]+", " ", lower(row.get("job_title"))).strip()
    company = re.sub(r"[^a-z0-9]+", " ", lower(row.get("company"))).strip()
    location = re.sub(r"[^a-z0-9]+", " ", lower(row.get("location"))).strip()
    return f"tcl::{title}|{company}|{location}"


# --------------------------------------------------------------------------
# LISTING / SEARCH PAGE DETECTION
# --------------------------------------------------------------------------

INDIVIDUAL_URL_PATTERNS = [
    re.compile(r"linkedin\.com/jobs/view/\d+", re.I),
    re.compile(r"naukri\.com/job-listings-", re.I),
    re.compile(r"indeed\.[a-z.]+/viewjob", re.I),
    re.compile(r"indeed\.[a-z.]+/.*[?&]jk=", re.I),
    re.compile(r"indeed\.[a-z.]+/rc/clk", re.I),
    re.compile(r"foundit\.in/job/", re.I),
    re.compile(r"monsterindia\.com/job/", re.I),
    re.compile(r"shine\.com/jobs/[^/]+/\d+", re.I),
    re.compile(r"jobaaj\.com/job/", re.I),
    re.compile(r"glassdoor\.[a-z.]+/job-listing/", re.I),
    re.compile(r"timesjobs\.com/job-detail", re.I),
    re.compile(r"instahyre\.com/job-", re.I),
    re.compile(r"cutshort\.io/job/", re.I),
    re.compile(r"hirist\.tech/j/", re.I),
    re.compile(r"iimjobs\.com/j/", re.I),
    re.compile(r"boards\.greenhouse\.io/[^/]+/jobs/\d+", re.I),
    re.compile(r"jobs\.lever\.co/[^/]+/[0-9a-f\-]{8,}", re.I),
    re.compile(r"myworkdayjobs\.com/.+/job/", re.I),
    re.compile(r"smartrecruiters\.com/[^/]+/\d{6,}", re.I),
    re.compile(r"/job/\d{4,}", re.I),
    re.compile(r"/jobs?/[^/]+-\d{5,}", re.I),
    re.compile(r"/careers?/(?:job|opening|position)s?/[^/]{6,}", re.I),
    re.compile(r"[?&](?:jobId|job_id|requisitionId|reqId)=", re.I),
]

LISTING_URL_PATTERNS = [
    (re.compile(r"linkedin\.com/jobs/search", re.I), "LinkedIn search page"),
    (re.compile(r"linkedin\.com/jobs/[a-z\-]+-jobs", re.I), "LinkedIn category page"),
    (re.compile(r"linkedin\.com/in/", re.I), "LinkedIn profile page"),
    (re.compile(r"linkedin\.com/company/", re.I), "LinkedIn company page"),
    (re.compile(r"linkedin\.com/pub/", re.I), "LinkedIn profile page"),
    (re.compile(r"naukri\.com/[a-z0-9\-]*jobs-in-[a-z\-]+", re.I), "Naukri listing page"),
    (re.compile(r"naukri\.com/(?:jobs|search|browse)", re.I), "Naukri search page"),
    (re.compile(r"naukri\.com/[a-z\-]+-jobs(?:$|[/?])", re.I), "Naukri category page"),
    (re.compile(r"indeed\.[a-z.]+/(?:jobs|q-|m/jobs|browsejobs)", re.I), "Indeed search page"),
    (re.compile(r"indeed\.[a-z.]+/cmp/", re.I), "Indeed company page"),
    (re.compile(r"foundit\.in/(?:search|srp|jobs)", re.I), "Foundit search page"),
    (re.compile(r"shine\.com/job-search", re.I), "Shine search page"),
    (re.compile(r"shine\.com/jobs/[a-z\-]+(?:$|/?\?)", re.I), "Shine category page"),
    (re.compile(r"glassdoor\.[a-z.]+/Job/", re.I), "Glassdoor listing page"),
    (re.compile(r"glassdoor\.[a-z.]+/(?:Overview|Reviews|Salary)", re.I), "Glassdoor company page"),
    (re.compile(r"timesjobs\.com/(?:candidate/job-search|jobskill)", re.I), "TimesJobs search page"),
    (re.compile(r"/job-search", re.I), "Job search page"),
    (re.compile(r"/jobs-in-[a-z\-]+", re.I), "City listing page"),
    (re.compile(r"/(?:category|categories|browse|explore|listing|listings)(?:$|/)", re.I), "Category page"),
    (re.compile(r"/company/[^/]+/?$", re.I), "Company page"),
    (re.compile(r"/(?:jobs|careers|vacancies|openings)/?$", re.I), "Generic jobs index"),
    (re.compile(r"[?&](?:q|k|keyword|keywords|query|searchTerm)=", re.I), "Search-result page"),
    (re.compile(r"/search(?:$|[/?])", re.I), "Search page"),
]

LISTING_TITLE_PATTERNS = [
    re.compile(r"\b\d{2,}\s+(?:jobs?|vacancies|openings)\b", re.I),
    re.compile(r"\bjobs?\s+in\s+[a-z]+\s*[-|]", re.I),
    re.compile(r"\b(?:latest|top|best|urgent)\s+\d+\s+jobs\b", re.I),
    re.compile(r"\bjob\s+(?:search|listings?|openings?)\b", re.I),
    re.compile(r"\bapply\s+to\s+\d+", re.I),
    re.compile(r"\bvacancies\s+in\b", re.I),
    re.compile(r"\bhiring\s+now\s*[-|]\s*\d+", re.I),
]


def validate_job_page(url: str, title: str) -> Tuple[bool, str]:
    """
    Returns (is_individual_job, evidence).
    URL structure first, then page/title content, then a conservative fallback.
    """
    url = clean_text(url)
    title = clean_text(title)

    if not url:
        return True, "no URL in CSV - analysed from CSV fields only"

    for pattern in INDIVIDUAL_URL_PATTERNS:
        if pattern.search(url):
            return True, f"individual job URL pattern: {pattern.pattern}"

    for pattern, reason in LISTING_URL_PATTERNS:
        if pattern.search(url):
            return False, reason

    for pattern in LISTING_TITLE_PATTERNS:
        if pattern.search(title):
            return False, f"listing-style title: {pattern.pattern}"

    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return False, "domain root - not an individual job page"

    last = segments[-1]
    has_id = bool(re.search(r"\d{4,}", last)) or bool(re.search(r"[0-9a-f]{8,}", last, re.I))
    has_slug = last.count("-") >= 2
    looks_like_job = any(seg.lower() in {"job", "jobs", "vacancy", "opening", "position", "careers", "career"}
                         for seg in segments[:-1])

    if has_id and (has_slug or looks_like_job):
        return True, "URL structure looks like an individual posting (slug + id)"
    if looks_like_job and has_slug and len(segments) >= 2:
        return True, "URL structure looks like an individual posting (job path + slug)"
    if has_id and len(segments) >= 2:
        return True, "URL structure contains a posting identifier"

    return False, "URL structure does not look like an individual job posting"


# --------------------------------------------------------------------------
# EXPERIENCE PARSING
# --------------------------------------------------------------------------

RANGE_RE = re.compile(
    r"\b(\d{1,2})\s*(?:\+)?\s*(?:[-–—~]|\s+to\s+|\s+or\s+)\s*(\d{1,2})\s*(?:\+)?\s*"
    r"(?:years?|yrs?|year)\b", re.I)

PLUS_RE = re.compile(
    r"\b(?:(?:minimum|min\.?|at\s+least|over|more\s+than|above)\s+)?"
    r"(\d{1,2})\s*(?:\+\s*(?:years?|yrs?)|(?:years?|yrs?)\s*\+)\b", re.I)

MIN_WORD_RE = re.compile(
    r"\b(?:minimum|min\.?|at\s+least|over|more\s+than|above)\s+(\d{1,2})\s*(?:years?|yrs?)\b", re.I)

SINGLE_RE = re.compile(r"\b(\d{1,2})\s*(?:years?|yrs?)\b", re.I)

CTX_RANGE_RE = re.compile(
    r"\b(?:exp(?:erience)?|exp\.)\s*[:\-]?\s*(\d{1,2})\s*(?:[-–—]|to)\s*(\d{1,2})\b", re.I)

CTX_SINGLE_RE = re.compile(
    r"\b(?:exp(?:erience)?|exp\.)\s*[:\-]?\s*(\d{1,2})\b(?!\s*[-–—])", re.I)

EXP_CONTEXT_WORDS = ("experience", "exp", "yrs", "yoe", "work ex", "background of",
                     "hands-on", "hands on", "relevant")

NEG_CONTEXT_BEFORE = ("last ", "past ", "over the ", "since ", "in the previous",
                      "founded", "established", "for the past")
NEG_CONTEXT_AFTER = ("ago", "old company")

FRESHER_STRONG_RE = re.compile(
    r"\b(freshers?|fresh\s+graduates?|fresh\s+grads?|entry[\s\-]?level|"
    r"trainees?|graduate\s+trainee|management\s+trainee|graduate\s+program(?:me)?|"
    r"apprentice(?:ship)?|campus\s+hiring|off[\s\-]?campus|on[\s\-]?campus|"
    r"recent\s+graduates?|new\s+graduates?|no\s+(?:prior\s+|work\s+)?experience\s+"
    r"(?:is\s+)?(?:required|needed|necessary))\b", re.I)

JUNIOR_WEAK_RE = re.compile(r"\b(junior|jr\.?|associate)\b", re.I)

SENIOR_TITLE_RE = re.compile(
    r"\b(senior|sr\.?|lead|team\s+lead|tech\s+lead|principal|architect|head|"
    r"director|manager|vp|vice\s+president|chief|staff|specialist\s+iv|iii|iv)\b", re.I)

SENIOR_FALSE_POSITIVE_RE = re.compile(
    r"\b(lead\s+gener|leads?\s+manage|lead\s+qualif|reporting\s+to|manager\s+will|"
    r"under\s+the\s+manager|managerial\s+reporting|report\s+to\s+the)\b", re.I)

POSITIVE_FRESHER_SIGNALS = [
    "fresher", "freshers", "fresh graduate", "graduate", "entry level", "entry-level",
    "junior", "trainee", "associate", "0 years", "0-1", "0-2", "0-3",
    "campus", "off campus", "graduate program", "graduate trainee", "apprentice",
]

NEGATIVE_FRESHER_SIGNALS = [
    "senior", "lead", "manager", "principal", "architect", "director",
    "5+ years", "4+ years", "3+ years", "3-5 years", "2-4 years",
]


def _mask(text: str, spans: List[Tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for index in range(start, min(end, len(chars))):
            chars[index] = " "
    return "".join(chars)


def _has_exp_context(text: str, start: int, end: int, window: int = 80) -> bool:
    snippet = text[max(0, start - window): min(len(text), end + window)].lower()
    return any(word in snippet for word in EXP_CONTEXT_WORDS)


def _has_negative_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 30): start].lower()
    after = text[end: end + 12].lower()
    if any(word in before for word in NEG_CONTEXT_BEFORE):
        return True
    if any(word in after for word in NEG_CONTEXT_AFTER):
        return True
    return False


def find_experience_mentions(text: str, require_context_for_single: bool) -> List[Dict[str, Any]]:
    """
    Extract numeric experience requirements from a block of text.
    Returns dicts: {kind, min, max, raw}
    Priority within a text: RANGE > PLUS/MIN > SINGLE.
    """
    text = clean_text(text)
    if not text:
        return []

    mentions: List[Dict[str, Any]] = []
    spans: List[Tuple[int, int]] = []

    for match in RANGE_RE.finditer(text):
        if _has_negative_context(text, match.start(), match.end()):
            continue
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        if high > 40:
            continue
        mentions.append({"kind": "range", "min": low, "max": high,
                         "raw": match.group(0).strip()})
        spans.append(match.span())

    masked = _mask(text, spans)

    for match in CTX_RANGE_RE.finditer(masked):
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        if high > 40:
            continue
        mentions.append({"kind": "range", "min": low, "max": high,
                         "raw": match.group(0).strip()})
        spans.append(match.span())

    masked = _mask(text, spans)

    for regex in (PLUS_RE, MIN_WORD_RE):
        for match in regex.finditer(masked):
            if _has_negative_context(text, match.start(), match.end()):
                continue
            value = int(match.group(1))
            if value > 40:
                continue
            mentions.append({"kind": "plus", "min": value, "max": None,
                             "raw": match.group(0).strip()})
            spans.append(match.span())

    masked = _mask(text, spans)

    for match in SINGLE_RE.finditer(masked):
        if _has_negative_context(text, match.start(), match.end()):
            continue
        if require_context_for_single and not _has_exp_context(text, match.start(), match.end()):
            continue
        value = int(match.group(1))
        if value > 40:
            continue
        mentions.append({"kind": "single", "min": value, "max": None,
                         "raw": match.group(0).strip()})
        spans.append(match.span())

    masked = _mask(text, spans)

    for match in CTX_SINGLE_RE.finditer(masked):
        value = int(match.group(1))
        if value > 40:
            continue
        mentions.append({"kind": "single", "min": value, "max": None,
                         "raw": match.group(0).strip()})

    return mentions


def choose_mention(mentions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Explicit ranges are the most reliable statement of a requirement."""
    if not mentions:
        return None
    for kind in ("range", "plus", "single"):
        same_kind = [m for m in mentions if m["kind"] == kind]
        if same_kind:
            return same_kind[0]
    return mentions[0]


def mention_to_category(mention: Dict[str, Any]) -> str:
    kind = mention["kind"]
    low = mention["min"]
    high = mention["max"]

    if kind == "range":
        if low == 0 and high == 0:
            return EXP_0
        if low == 0:
            if high <= 1:
                return EXP_0_1
            if high <= 2:
                return EXP_0_2
            return EXP_0_3
        if low == 1:
            return EXP_1_2 if high <= 2 else EXP_1_3
        if low == 2:
            return EXP_2_4
        if low == 3:
            return EXP_3_5 if high <= 5 else EXP_3P
        if low == 4:
            return EXP_4P
        return EXP_5P

    # "plus" and bare "single" both mean "at least N years"
    if low <= 0:
        return EXP_0
    if low == 1:
        return EXP_1_2 if kind == "single" else EXP_1_3
    if low == 2:
        return EXP_2_4
    if low == 3:
        return EXP_3P
    if low == 4:
        return EXP_4P
    return EXP_5P


def detect_seniority(title: str) -> Optional[str]:
    title = fold(title)
    if not title:
        return None
    if SENIOR_FALSE_POSITIVE_RE.search(title):
        return None
    if FRESHER_STRONG_RE.search(title):
        # "Senior" cannot sensibly coexist with "fresher/trainee" wording
        if not re.search(r"\bsenior\b|\bsr\.?\b", title, re.I):
            return None
    match = SENIOR_TITLE_RE.search(title)
    if not match:
        return None
    token = match.group(1).lower()
    if token in {"iii", "iv"} and not re.search(r"\banalyst\b|\bengineer\b", title, re.I):
        return None
    return match.group(0)


def fresher_signal_balance(text: str) -> Tuple[int, int]:
    text_l = fold(text).lower()
    positive = sum(1 for signal in POSITIVE_FRESHER_SIGNALS if signal in text_l)
    negative = sum(1 for signal in NEGATIVE_FRESHER_SIGNALS if signal in text_l)
    return positive, negative


def classify_experience(title: str, description: str, url: str = "",
                        extra: str = "") -> Tuple[str, str]:
    """
    Returns (category, evidence_string).

    Priority:
      1. numeric evidence in the TITLE
      2. numeric evidence in the DESCRIPTION / metadata / URL
      3. seniority wording in the TITLE  (only when numeric evidence is absent
         or is itself junior-level)
      4. explicit fresher wording anywhere
      5. weak junior wording
      6. Other / Unknown  (NEVER assumed to be fresher)
    """
    title = fold(title)
    description = fold(description)
    extra = fold(extra)
    url_text = fold(url).replace("-", " ").replace("/", " ")

    title_mentions = find_experience_mentions(title, require_context_for_single=False)
    body_mentions = find_experience_mentions(
        " ".join([description, extra]), require_context_for_single=True)
    url_mentions = find_experience_mentions(url_text, require_context_for_single=True)

    title_pick = choose_mention(title_mentions)
    body_pick = choose_mention(body_mentions)
    url_pick = choose_mention(url_mentions)

    numeric_pick = title_pick or body_pick or url_pick
    numeric_source = ("title" if title_pick else
                      "description" if body_pick else
                      "url" if url_pick else "")

    seniority = detect_seniority(title)
    fresher_hit = FRESHER_STRONG_RE.search(title) or FRESHER_STRONG_RE.search(description)
    junior_hit = JUNIOR_WEAK_RE.search(title)

    evidence_parts: List[str] = []
    if title_pick:
        evidence_parts.append(f"title: '{title_pick['raw']}'")
    if body_pick:
        evidence_parts.append(f"description: '{body_pick['raw']}'")
    if url_pick and not (title_pick or body_pick):
        evidence_parts.append(f"url: '{url_pick['raw']}'")
    if seniority:
        evidence_parts.append(f"seniority word in title: '{seniority}'")
    if fresher_hit:
        evidence_parts.append(f"fresher signal: '{fresher_hit.group(0)}'")
    if junior_hit and not fresher_hit:
        evidence_parts.append(f"junior signal: '{junior_hit.group(0)}'")

    if seniority:
        if numeric_pick and numeric_pick["min"] >= 2:
            category = mention_to_category(numeric_pick)
            evidence_parts.append(f"numeric evidence ({numeric_source}) overrides seniority word")
        else:
            category = EXP_SENIOR
            evidence_parts.append("seniority wording is decisive (no higher numeric evidence)")
    elif numeric_pick:
        category = mention_to_category(numeric_pick)
        evidence_parts.append(f"numeric evidence taken from {numeric_source}")
    elif fresher_hit:
        category = EXP_0
        evidence_parts.append("explicit fresher/entry-level wording")
    elif junior_hit:
        category = EXP_0_2
        evidence_parts.append("weak junior/associate wording (assumed 0-2 years)")
    else:
        category = EXP_UNKNOWN
        evidence_parts.append("no experience evidence found in title, description, url or CSV")

    return category, "; ".join(evidence_parts)


# --------------------------------------------------------------------------
# ROLE MATCHING
# --------------------------------------------------------------------------

STRONG_TITLE_RE = re.compile(
    r"\b(?:"
    r"data\s+analyst|junior\s+data\s+analyst|associate\s+data\s+analyst|"
    r"data\s+analytics\s+analyst|graduate\s+data\s+analyst|data\s+analyst\s+trainee|"
    r"business\s+intelligence\s+analyst|bi\s+analyst|reporting\s+analyst|"
    r"mis\s+(?:analyst|executive)|data\s+reporting\s+analyst|data\s+research\s+analyst|"
    r"analytics\s+associate|sql\s+analyst|etl\s+analyst|analytics\s+analyst|"
    r"insight[s]?\s+analyst|data\s+quality\s+analyst"
    r")\b", re.I)

RELATED_TITLE_RE = re.compile(
    r"\b(?:analytics\s+engineer|business\s+analyst|data\s+scientist|data\s+engineer|"
    r"power\s*bi\s+developer|tableau\s+developer|bi\s+developer|"
    r"data\s+associate|data\s+executive|research\s+analyst|product\s+analyst|"
    r"decision\s+scientist|analytics\s+consultant)\b", re.I)

GENERIC_ANALYST_RE = re.compile(r"\banalyst\b", re.I)

ANALYTICS_TERMS = [
    "data analysis", "data analytics", "analytics", "business intelligence",
    "power bi", "tableau", "sql", "dashboard", "reporting", "mis", "insights",
    "etl", "data visualization", "data visualisation", "kpi", "excel",
    "python", "warehouse", "queries", "stakeholder", "metrics", "reports",
]

OFF_TOPIC_TITLE_RE = re.compile(
    r"\b(?:nurse|doctor|chef|driver|teacher|tutor|telecaller|tele\s*caller|"
    r"field\s+sales|sales\s+executive|bpo|customer\s+support|content\s+writer|"
    r"graphic\s+designer|hr\s+recruiter|talent\s+acquisition|security\s+guard|"
    r"civil\s+engineer|mechanical\s+engineer|electrician|accountant|"
    r"digital\s+marketing|seo|social\s+media)\b", re.I)


def score_role(title: str, description: str) -> Tuple[int, str]:
    title = fold(title)
    body = fold(title + " " + description).lower()
    density = sum(1 for term in ANALYTICS_TERMS if term in body)

    if OFF_TOPIC_TITLE_RE.search(title) and not STRONG_TITLE_RE.search(title):
        return 10, "off-topic job title"

    if STRONG_TITLE_RE.search(title):
        score = 100 if density >= 2 else 88
        return score, f"target/related analyst title (analytics terms found: {density})"

    if RELATED_TITLE_RE.search(title):
        score = 78 if density >= 2 else 66
        return score, f"adjacent data/analytics title (analytics terms found: {density})"

    if GENERIC_ANALYST_RE.search(title):
        if density >= 4:
            return 70, f"generic analyst title with strong analytics content ({density} terms)"
        if density >= 2:
            return 55, f"generic analyst title with some analytics content ({density} terms)"
        return 35, "generic analyst title, no analytics evidence"

    if re.search(r"\bdata\b", title, re.I):
        if density >= 4:
            return 55, f"'data' in title with analytics content ({density} terms)"
        return 25, "'data' in title but no analytics evidence"

    if density >= 6:
        return 45, f"non-analyst title but analytics-heavy description ({density} terms)"

    return 12, "title and description do not relate to data/analytics/BI"


# --------------------------------------------------------------------------
# LOCATION MATCHING
# --------------------------------------------------------------------------

PUNE_REGION_TOKENS = [
    "hinjewadi", "hinjawadi", "baner", "kharadi", "hadapsar", "viman nagar",
    "wakad", "pimpri", "chinchwad", "pimpri-chinchwad", "magarpatta",
    "yerwada", "kothrud", "aundh", "balewadi", "bavdhan", "wagholi",
    "shivajinagar", "kalyani nagar", "talawade", "katraj", "pcmc",
]

INDIA_CITY_TOKENS = [
    "mumbai", "navi mumbai", "thane", "bengaluru", "bangalore", "hyderabad",
    "chennai", "delhi", "new delhi", "noida", "gurgaon", "gurugram", "ncr",
    "kolkata", "ahmedabad", "indore", "jaipur", "chandigarh", "coimbatore",
    "kochi", "cochin", "trivandrum", "nagpur", "mysore", "mysuru", "vadodara",
    "surat", "bhubaneswar", "lucknow", "visakhapatnam", "vizag", "madurai",
    "nashik", "goa", "bhopal", "mohali", "trichy", "vellore", "yavatmal",
    "amravati", "aurangabad", "kolhapur", "solapur", "nanded",
]

# Words that positively establish India. "ind" and "in" appear as country
# codes in feeds such as "IND, TELECOMMUTE" and "Pune Division, IN".
INDIA_TOKENS_RE = re.compile(
    r"\b(?:india|indian|bharat|ind|maharashtra|karnataka|telangana|"
    r"tamil nadu|kerala|gujarat|haryana|punjab|rajasthan|west bengal|"
    r"uttar pradesh|madhya pradesh|andhra pradesh|odisha|delhi ncr)\b", re.I)

# Unambiguous non-India places. Deliberately excludes words that double as
# common English (e.g. "turkey", "jordan", "georgia").
FOREIGN_TOKENS = [
    "brazil", "brasil", "sao paulo", "rio de janeiro", "argentina",
    "colombia", "chile", "peru", "mexico", "united states", "u.s.a", "usa",
    "u.s.", "new york", "california", "texas", "chicago", "boston", "seattle",
    "canada", "toronto", "vancouver", "united kingdom", "england", "london",
    "manchester", "ireland", "dublin", "germany", "berlin", "munich",
    "netherlands", "amsterdam", "france", "paris", "spain", "madrid",
    "barcelona", "portugal", "lisbon", "italy", "milan", "poland", "warsaw",
    "krakow", "romania", "bucharest", "hungary", "budapest", "czech",
    "prague", "sweden", "stockholm", "norway", "denmark", "copenhagen",
    "belgium", "brussels", "austria", "vienna", "switzerland", "zurich",
    "greece", "athens", "singapore", "malaysia", "kuala lumpur", "philippines",
    "manila", "indonesia", "jakarta", "vietnam", "hanoi", "thailand",
    "bangkok", "japan", "tokyo", "china", "shanghai", "beijing", "hong kong",
    "taiwan", "south korea", "seoul", "australia", "sydney", "melbourne",
    "new zealand", "dubai", "abu dhabi", "uae", "united arab emirates",
    "qatar", "doha", "saudi", "riyadh", "kuwait", "oman", "muscat", "bahrain",
    "israel", "tel aviv", "egypt", "cairo", "kenya", "nairobi", "nigeria",
    "south africa", "johannesburg", "sri lanka", "colombo", "bangladesh",
    "dhaka", "nepal", "kathmandu", "pakistan", "karachi", "lahore",
    "emea", "latam", "apac region",
]

REMOTE_TOKENS_RE = re.compile(
    r"\b(?:remote|telecommute|work from home|wfh|anywhere in india|hybrid)\b", re.I)


def _scan_location(text: str) -> Dict[str, Any]:
    """Break a piece of text into location evidence."""
    folded = fold(text).lower()
    return {
        "text": folded,
        "pune": bool(re.search(r"\bpune\b", folded)),
        "region": [token for token in PUNE_REGION_TOKENS
                   if re.search(rf"\b{re.escape(token)}\b", folded)],
        "cities": [city for city in INDIA_CITY_TOKENS
                   if re.search(rf"\b{re.escape(city)}\b", folded)],
        "india": bool(INDIA_TOKENS_RE.search(folded)),
        "foreign": [token for token in FOREIGN_TOKENS
                    if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", folded)],
        "remote": bool(REMOTE_TOKENS_RE.search(folded)),
    }


def score_location(location: str, title: str, description: str) -> Tuple[int, str]:
    """
    Evidence priority:
      1. a foreign place named in the TITLE is decisive
      2. the location FIELD (or JSON-LD jobLocation)
      3. only then the title/description as weak fallback

    A stray mention of "India" deep in a description can no longer rescue a
    job whose stated location is another country - that is exactly how the
    Brazil posting leaked into the accepted list.
    """
    title_scan = _scan_location(title)
    if title_scan["foreign"] and not (title_scan["pune"] or title_scan["india"]
                                      or title_scan["cities"]):
        return 0, f"job title names a non-India location: {', '.join(title_scan['foreign'][:3])}"

    field = clean_text(location)
    if field:
        scan = _scan_location(field)
        if scan["foreign"] and not (scan["pune"] or scan["cities"] or scan["india"]):
            return 0, f"location field is outside India: {', '.join(scan['foreign'][:3])}"
        if scan["pune"]:
            return 100, f"Pune in location field ('{truncate(field, 40)}')"
        if scan["region"]:
            return 95, f"Pune-region locality: {', '.join(scan['region'][:3])}"
        if scan["remote"] and scan["india"]:
            return 85, f"India remote/hybrid ('{truncate(field, 40)}')"
        if scan["cities"]:
            return 25, f"India but different city: {', '.join(scan['cities'][:3])}"
        if scan["india"]:
            return 45, f"India, city not specified ('{truncate(field, 40)}')"
        if scan["remote"]:
            body = _scan_location(f"{title} {description[:600]}")
            if body["foreign"] and not body["india"]:
                return 0, "remote role tied to a non-India region"
            if body["pune"]:
                return 90, "remote role with Pune mentioned in the posting"
            return 60, "remote role, country not stated"

    # ---- fallback: title + start of description ------------------------
    body = _scan_location(f"{title} {description[:600]}")
    if body["foreign"] and not (body["india"] or body["pune"] or body["cities"]):
        return 0, f"posting text points outside India: {', '.join(body['foreign'][:3])}"
    if body["pune"]:
        return 100, "Pune found in posting text"
    if body["region"]:
        return 95, f"Pune-region locality in posting text: {', '.join(body['region'][:3])}"
    if body["remote"] and body["india"]:
        return 85, "remote role, India-compatible"
    if body["cities"]:
        return 25, f"India but different city: {', '.join(body['cities'][:3])}"
    if body["india"]:
        return 45, "India, city not specified"
    return 50, "location could not be determined"


# --------------------------------------------------------------------------
# SKILL MATCHING
# --------------------------------------------------------------------------

SKILL_PATTERNS: Dict[str, str] = {
    "Python": r"\bpython\b",
    "SQL": r"\b(?:sql|t-sql|pl/?sql|my\s?sql|postgre\s?sql|postgres|ms\s?sql|sql\s?server|"
           r"oracle\s?sql|queries\s+in\s+sql)\b",
    "Excel": r"\b(?:excel|ms[\s\-]?excel|microsoft\s+excel|advanced\s+excel|vlookup|"
             r"pivot\s+tables?|v-?lookup)\b",
    "Power BI": r"(?:\bpower\s*-?\s*bi\b|\bpowerbi\b|\bpower\s+bi\s+desktop\b|\bdax\b|\bpower\s+query\b)",
    "Tableau": r"\btableau\b",
    "Snowflake": r"\bsnowflake\b",
    "Pandas": r"\bpandas\b",
    "NumPy": r"\b(?:numpy|np\.array)\b",
    "Machine Learning": r"\b(?:machine\s+learning|\bml\b|scikit[\s\-]?learn|sklearn|"
                        r"predictive\s+model(?:l?ing|s)?|classification\s+models?)\b",
    "Statistics": r"\b(?:statistics|statistical|hypothesis\s+testing|regression|"
                  r"probability|a/?b\s+testing)\b",
    "Data Analysis": r"\b(?:data\s+analysis|data\s+analytics|data\s+analyst|"
                     r"exploratory\s+data\s+analysis|\beda\b|data\s+driven)\b",
    "Streamlit": r"\bstreamlit\b",
    "ETL": r"\b(?:etl|elt|data\s+pipelines?|informatica|ssis|talend|data\s+ingestion)\b",
    "Data Engineering": r"\b(?:data\s+engineering|data\s+engineer|databricks|py\s?spark|"
                        r"apache\s+spark|airflow|azure\s+data\s+factory|\badf\b|"
                        r"data\s+warehouse|redshift|bigquery)\b",
    "LangChain": r"\b(?:langchain|llm[s]?|generative\s+ai|gen\s?ai|\brag\b|openai|"
                 r"large\s+language\s+model)\b",
}

COMPILED_SKILLS = {skill: re.compile(pattern, re.I)
                   for skill, pattern in SKILL_PATTERNS.items()
                   if skill in RESUME_SKILLS}

SKILL_COUNT_SCORE = {0: 0, 1: 30, 2: 45, 3: 58, 4: 70, 5: 80, 6: 88, 7: 94}


def normalize_skill_text(text: str) -> str:
    text = fold(text)
    text = re.sub(r"power\s*-\s*bi", "power bi", text, flags=re.I)
    text = re.sub(r"\bpowerbi\b", "power bi", text, flags=re.I)
    text = re.sub(r"\bms[\s\-]?excel\b", "excel", text, flags=re.I)
    text = re.sub(r"\bms[\s\-]?sql\b", "ms sql", text, flags=re.I)
    text = re.sub(r"\bnum\s?py\b", "numpy", text, flags=re.I)
    return text


def match_skills(text: str) -> Tuple[List[str], List[str], int, int]:
    """Returns (matched, missing, skill_score, match_percentage)."""
    text = normalize_skill_text(text)
    matched: List[str] = []
    for skill, pattern in COMPILED_SKILLS.items():
        if pattern.search(text):
            matched.append(skill)
    missing = [skill for skill in RESUME_SKILLS if skill not in matched]
    count = len(matched)
    score = SKILL_COUNT_SCORE.get(count, 100)
    percentage = int(round(100.0 * count / max(1, len(RESUME_SKILLS))))
    return matched, missing, score, percentage


# --------------------------------------------------------------------------
# DATE / FRESHNESS
# --------------------------------------------------------------------------

RELATIVE_DATE_RE = re.compile(
    r"\b(\d{1,3})\+?\s*(minute|min|hour|hr|day|week|month)s?\s+ago\b", re.I)

DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y",
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime_any(value: str, reference: Optional[datetime] = None) -> Optional[datetime]:
    value = clean_text(value)
    if not value:
        return None
    reference = reference or now_utc()

    lowered = value.lower()
    if any(word in lowered for word in ("just posted", "just now", "today", "posted today")):
        return reference - timedelta(hours=2)
    if "yesterday" in lowered:
        return reference - timedelta(days=1)

    relative = RELATIVE_DATE_RE.search(value)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        if unit in ("minute", "min"):
            return reference - timedelta(minutes=amount)
        if unit in ("hour", "hr"):
            return reference - timedelta(hours=amount)
        if unit == "day":
            return reference - timedelta(days=amount)
        if unit == "week":
            return reference - timedelta(weeks=amount)
        if unit == "month":
            return reference - timedelta(days=30 * amount)

    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+0000"
    candidate = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", candidate)

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue

    iso_match = re.search(r"\d{4}-\d{2}-\d{2}", candidate)
    if iso_match:
        try:
            parsed = datetime.strptime(iso_match.group(0), "%Y-%m-%d")
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def classify_freshness(posted: Optional[datetime],
                       reference: Optional[datetime] = None) -> str:
    if posted is None:
        return FRESH_UNKNOWN
    reference = reference or now_utc()
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age = reference - posted
    if age < timedelta(0):
        return FRESH_24
    if age <= timedelta(hours=24):
        return FRESH_24
    if age <= timedelta(hours=48):
        return FRESH_48
    if age <= timedelta(days=7):
        return FRESH_OLD_48
    if age <= timedelta(days=30):
        return FRESH_OLD_7
    return FRESH_OLD_30


# --------------------------------------------------------------------------
# PAGE FETCHING
# --------------------------------------------------------------------------

class PageFetcher:
    """Fetches job pages defensively. Never raises."""

    def __init__(self, enabled: bool = True, delay: float = FETCH_DELAY,
                 timeout: int = FETCH_TIMEOUT):
        self.enabled = enabled and requests is not None
        self.delay = delay
        self.timeout = timeout
        self.cache: Dict[str, Optional[str]] = {}
        self.stats = {"ok": 0, "blocked": 0, "not_found": 0, "error": 0, "skipped": 0}
        self.session = None
        if self.enabled:
            try:
                self.session = requests.Session()
                self.session.headers.update({
                    "User-Agent": USER_AGENTS[0],
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Connection": "close",
                })
            except Exception:
                self.enabled = False

    def fetch(self, url: str) -> Tuple[Optional[str], str]:
        """Returns (html_or_None, note)."""
        url = clean_text(url)
        if not url:
            return None, "no url"
        if not self.enabled:
            self.stats["skipped"] += 1
            return None, "fetching disabled (requests unavailable or --no-fetch)"
        if url in self.cache:
            return self.cache[url], "cached"

        note = "unknown error"
        html: Optional[str] = None

        for attempt in range(FETCH_RETRIES + 1):
            try:
                headers = {"User-Agent": USER_AGENTS[attempt % len(USER_AGENTS)]}
                response = self.session.get(url, timeout=self.timeout,
                                            headers=headers, allow_redirects=True)
                status = response.status_code
                if status == 200:
                    text = response.text or ""
                    if len(text.strip()) < 500:
                        note = "empty or javascript-rendered page"
                        html = None
                    elif re.search(r"(cf-browser-verification|Just a moment|"
                                   r"Attention Required!\s*\|\s*Cloudflare|"
                                   r"enable JavaScript and cookies)", text, re.I):
                        note = "blocked by Cloudflare / bot protection"
                        html = None
                        self.stats["blocked"] += 1
                        break
                    else:
                        html = text
                        note = "fetched"
                        self.stats["ok"] += 1
                    break
                if status in (401, 403):
                    note = f"HTTP {status} - access denied"
                    self.stats["blocked"] += 1
                    break
                if status == 404:
                    note = "HTTP 404 - job removed"
                    self.stats["not_found"] += 1
                    break
                if status == 429:
                    note = "HTTP 429 - rate limited"
                    time.sleep(self.delay * 3)
                    continue
                note = f"HTTP {status}"
            except Exception as error:  # timeouts, DNS, SSL, connection reset...
                note = f"{type(error).__name__}"
            time.sleep(self.delay)

        if html is None and note not in ("fetched",):
            if self.stats["blocked"] == 0 and self.stats["not_found"] == 0:
                self.stats["error"] += 1

        self.cache[url] = html
        time.sleep(self.delay)
        return html, note


# --------------------------------------------------------------------------
# HTML / JSON-LD PARSING
# --------------------------------------------------------------------------

def _iter_jsonld_objects(payload: Any):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _iter_jsonld_objects(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_jsonld_objects(item)


def extract_jsonld_jobposting(html: str) -> Dict[str, Any]:
    """Pull the JobPosting object out of embedded JSON-LD, if present."""
    result: Dict[str, Any] = {}
    if not html:
        return result

    blocks: List[str] = []
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
                if tag.string:
                    blocks.append(tag.string)
                elif tag.text:
                    blocks.append(tag.text)
        except Exception:
            blocks = []
    if not blocks:
        blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.S | re.I)

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        try:
            payload = json.loads(block)
        except Exception:
            try:
                payload = json.loads(re.sub(r",\s*([}\]])", r"\1", block))
            except Exception:
                continue
        for obj in _iter_jsonld_objects(payload):
            obj_type = obj.get("@type") or obj.get("type")
            types = obj_type if isinstance(obj_type, list) else [obj_type]
            if any(str(t).lower() == "jobposting" for t in types if t):
                result = obj
                break
        if result:
            break
    return result


def jsonld_to_fields(jobposting: Dict[str, Any]) -> Dict[str, str]:
    fields = {"title": "", "description": "", "date_posted": "",
              "employment_type": "", "company": "", "location": "",
              "experience": ""}
    if not jobposting:
        return fields

    fields["title"] = clean_text(jobposting.get("title"))
    raw_description = jobposting.get("description") or ""
    fields["description"] = clean_text(strip_html(str(raw_description)))
    fields["date_posted"] = clean_text(jobposting.get("datePosted"))

    employment = jobposting.get("employmentType")
    if isinstance(employment, list):
        employment = ", ".join(str(item) for item in employment)
    fields["employment_type"] = clean_text(employment)

    organisation = jobposting.get("hiringOrganization")
    if isinstance(organisation, dict):
        fields["company"] = clean_text(organisation.get("name"))
    elif organisation:
        fields["company"] = clean_text(organisation)

    location_parts: List[str] = []
    job_location = jobposting.get("jobLocation")
    locations = job_location if isinstance(job_location, list) else [job_location]
    for entry in locations:
        if not isinstance(entry, dict):
            if entry:
                location_parts.append(clean_text(entry))
            continue
        address = entry.get("address")
        if isinstance(address, dict):
            for key in ("addressLocality", "addressRegion", "addressCountry"):
                value = address.get(key)
                if isinstance(value, dict):
                    value = value.get("name")
                if value:
                    location_parts.append(clean_text(value))
        elif address:
            location_parts.append(clean_text(address))
    if jobposting.get("jobLocationType"):
        location_parts.append(clean_text(jobposting.get("jobLocationType")))
    fields["location"] = ", ".join(dict.fromkeys([p for p in location_parts if p]))

    experience_block = jobposting.get("experienceRequirements")
    if isinstance(experience_block, dict):
        months = experience_block.get("monthsOfExperience")
        if months is not None:
            try:
                years = int(months) // 12
                fields["experience"] = f"{years} years experience"
            except Exception:
                fields["experience"] = clean_text(str(months))
        else:
            fields["experience"] = clean_text(experience_block.get("description", ""))
    elif experience_block:
        fields["experience"] = clean_text(str(experience_block))

    return fields


TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def strip_html(html: str) -> str:
    if not html:
        return ""
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            return clean_text(soup.get_text(" "))
        except Exception:
            pass
    text = SCRIPT_RE.sub(" ", html)
    text = TAG_RE.sub(" ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
    return clean_text(text)


META_PATTERNS = [
    ("description", re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.S | re.I)),
    ("og_description", re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', re.S | re.I)),
    ("og_title", re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', re.S | re.I)),
    ("published", re.compile(r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|datePosted|og:updated_time)["\'][^>]+content=["\'](.*?)["\']', re.S | re.I)),
    ("site_name", re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', re.S | re.I)),
]

VISIBLE_DATE_RE = re.compile(
    r"(?:posted|published|updated|active)\s*(?:on|:)?\s*"
    r"([0-9]{1,2}\s+\w+\s+[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2}|\d{1,3}\+?\s*\w+\s+ago)", re.I)


def extract_meta(html: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    if not html:
        return meta
    for key, pattern in META_PATTERNS:
        match = pattern.search(html)
        if match:
            meta[key] = clean_text(match.group(1))
    visible = VISIBLE_DATE_RE.search(strip_html(html)[:4000])
    if visible:
        meta["visible_date"] = clean_text(visible.group(1))
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if title_match:
        meta["page_title"] = clean_text(title_match.group(1))
    return meta


def extract_main_text(html: str) -> str:
    """Best-effort job description text from the page body."""
    if not html:
        return ""
    if BeautifulSoup is None:
        return strip_html(html)[:12000]
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form"]):
            tag.decompose()
        candidates = []
        selectors = [
            {"name": "div", "attrs": {"class": re.compile(r"(job[-_ ]?desc|description|jd[-_ ]?container|"
                                                          r"job[-_ ]?details|show-more-less-html)", re.I)}},
            {"name": "section", "attrs": {"class": re.compile(r"(description|job)", re.I)}},
            {"name": "article", "attrs": {}},
        ]
        for selector in selectors:
            for node in soup.find_all(selector["name"], attrs=selector.get("attrs") or {}):
                text = clean_text(node.get_text(" "))
                if len(text) > 200:
                    candidates.append(text)
        if candidates:
            return max(candidates, key=len)[:12000]
        return clean_text(soup.get_text(" "))[:12000]
    except Exception:
        return strip_html(html)[:12000]


# --------------------------------------------------------------------------
# COMPANY EXTRACTION
# --------------------------------------------------------------------------

BAD_COMPANY_TOKENS = {
    "sql", "python", "excel", "power bi", "powerbi", "tableau", "pune", "mumbai",
    "india", "shine", "naukri", "linkedin", "indeed", "foundit", "glassdoor",
    "monster", "jobs", "job", "apply", "fresher", "freshers", "data analyst",
    "analyst", "hiring", "career", "careers", "remote", "full time", "part time",
    "n/a", "na", "none", "company", "confidential", "years", "maharashtra",
    "timesjobs", "jobaaj", "internshala", "unknown",
}


def looks_like_company(value: str) -> bool:
    value = clean_text(value)
    if not value or len(value) < 2 or len(value) > 80:
        return False
    if value.lower() in BAD_COMPANY_TOKENS:
        return False
    if any(value.lower() == token for token in BAD_COMPANY_TOKENS):
        return False
    if re.fullmatch(r"[\d\W_]+", value):
        return False
    if re.search(r"\b(years?|yrs?)\b", value, re.I) and len(value) < 20:
        return False
    return True


def extract_company(jsonld_company: str, meta: Dict[str, str],
                    csv_company: str, title: str) -> Tuple[str, str]:
    if looks_like_company(jsonld_company):
        return clean_text(jsonld_company), "JSON-LD hiringOrganization"

    for key in ("site_name",):
        value = meta.get(key, "")
        if looks_like_company(value) and not re.search(
                r"(linkedin|naukri|indeed|shine|foundit|glassdoor|monster|jobs)", value, re.I):
            return value, f"page metadata ({key})"

    if looks_like_company(csv_company):
        return clean_text(csv_company), "CSV company column"

    title = clean_text(title)
    patterns = [
        re.compile(r"\bat\s+([A-Z][\w&.,'\- ]{2,50})$"),
        re.compile(r"^\s*([A-Z][\w&.,'\- ]{2,50})\s+is\s+hiring", re.I),
        re.compile(r"\bjob\s+in\s+([A-Z][\w&.,'\- ]{2,50})$"),
    ]
    for pattern in patterns:
        match = pattern.search(title)
        if match:
            candidate = clean_text(match.group(1))
            if looks_like_company(candidate):
                return candidate, "job title pattern"

    return "Unknown", "no reliable company evidence"


# --------------------------------------------------------------------------
# SCORING + DECISION
# --------------------------------------------------------------------------

def compute_overall(role: int, location: int, experience: int,
                    skills: int, freshness: int) -> int:
    total = (role * WEIGHTS["role"] + location * WEIGHTS["location"]
             + experience * WEIGHTS["experience"] + skills * WEIGHTS["skills"]
             + freshness * WEIGHTS["freshness"])
    return int(round(total))


def decide(experience: str, role_score: int, location_score: int,
           overall: int, freshness: str, evidence_length: int,
           positive_signals: int, negative_signals: int,
           is_individual: bool, listing_reason: str) -> Tuple[str, str]:
    """
    Explicit rules run BEFORE the weighted score.
    Returns (recommendation, rejection_reason).
    """
    if not is_individual:
        return REC_REJ_LISTING, listing_reason

    if location_score == 0:
        return REC_REJ_LOC, "job is located outside India and is not remote for India"

    if role_score < 40:
        return REC_REJ_ROLE, "title/description are not a data, analytics or BI role"

    if experience == EXP_SENIOR:
        return REC_REJ_SENIOR, "senior/lead/manager level role"

    if experience in TOO_HIGH_EXP:
        return REC_REJ_EXP, f"requires {experience}, above a fresher profile"

    if experience == EXP_UNKNOWN:
        if evidence_length < 40 and role_score < 60:
            return REC_REJ_DATA, "no description and no reliable role evidence available"
        if negative_signals > positive_signals and negative_signals >= 2:
            return REC_LOW, ("experience not stated; wording leans experienced "
                             f"({negative_signals} negative vs {positive_signals} positive signals)")
        if overall >= 62 and positive_signals >= 1:
            return REC_CONSIDER, ("experience not stated; fresher-friendly signals present "
                                  "- verify on the job page before applying")
        return REC_LOW, "experience not stated; verify eligibility before applying"

    if experience in ELIGIBLE_EXP:
        if location_score <= 30:
            return REC_CONSIDER, ("eligible on experience but the role is in another "
                                  f"Indian city, not {TARGET_CITY}")
        if role_score < 70:
            return REC_CONSIDER, ("adjacent job title - confirm it is really a "
                                  "data/analytics role before applying")
        if overall >= 72 and freshness in (FRESH_24, FRESH_48):
            return REC_HIGH, ""
        if overall >= 62:
            return REC_APPLY, ""
        if overall >= 48:
            return REC_CONSIDER, ""
        return REC_LOW, "eligible on experience but weak role/location/skill fit"

    if experience in CONSIDER_EXP:
        if overall >= 66:
            return REC_CONSIDER, ""
        return REC_LOW, f"requires {experience}; borderline for a fresher"

    return REC_LOW, "unclassified"


# --------------------------------------------------------------------------
# CORE ANALYSIS OF ONE ROW
# --------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "job_title", "company", "location", "source", "job_url",
    "experience", "experience_evidence",
    "freshness", "date_posted",
    "role_score", "location_score", "experience_score", "skill_score",
    "freshness_score", "overall_match",
    "matched_skills", "missing_skills",
    "recommendation", "rejection_reason",
    "description",
]

EXTRA_COLUMNS = [
    "is_individual_job", "listing_evidence", "fetch_status",
    "role_evidence", "location_evidence", "date_source",
    "skill_match_pct", "positive_signals", "negative_signals", "job_id",
]


def analyse_row(row: Dict[str, Any], fetcher: PageFetcher,
                reference_time: Optional[datetime] = None) -> Dict[str, Any]:
    reference_time = reference_time or now_utc()

    csv_title = clean_text(row.get("job_title"))
    csv_company = clean_text(row.get("company"))
    csv_location = clean_text(row.get("location"))
    csv_source = clean_text(row.get("source"))
    csv_description = clean_text(row.get("description"))
    raw_url = clean_text(row.get("job_url"))
    url = normalize_url(raw_url)

    csv_extra = " ".join(clean_text(row.get(key)) for key in
                         ("snippet", "summary", "experience", "date", "date_posted",
                          "posted", "posted_date", "matched_skills", "match_level"))

    is_individual, listing_evidence = validate_job_page(url or raw_url, csv_title)

    html = None
    fetch_status = "not fetched"
    if is_individual:
        html, fetch_status = fetcher.fetch(raw_url or url)

    jsonld = extract_jsonld_jobposting(html or "")
    ld = jsonld_to_fields(jsonld)
    meta = extract_meta(html or "")
    page_text = extract_main_text(html or "") if html else ""

    # ---- re-validate using page content -------------------------------
    if is_individual and html:
        combined_page = f"{meta.get('page_title', '')} {page_text[:1500]}"
        if not jsonld:
            for pattern in LISTING_TITLE_PATTERNS:
                if pattern.search(meta.get("page_title", "")):
                    is_individual = False
                    listing_evidence = f"page title looks like a listing: {pattern.pattern}"
                    break
            if is_individual and re.search(r"\b\d{2,}\s+(?:jobs|vacancies)\s+(?:found|matching)\b",
                                           combined_page, re.I):
                is_individual = False
                listing_evidence = "page content reports multiple job results"

    # ---- assemble the best available text -----------------------------
    title = ld["title"] or csv_title or meta.get("og_title", "") or meta.get("page_title", "")
    title = clean_text(title)

    description_parts = [
        ld["description"],
        page_text,
        meta.get("og_description", ""),
        meta.get("description", ""),
        csv_description,
        ld["experience"],
        ld["employment_type"],
        csv_extra,
    ]
    description = clean_text(" ".join(part for part in description_parts if part))
    evidence_length = len(description)

    location = ld["location"] or csv_location
    company, company_source = extract_company(ld["company"], meta, csv_company, title)

    # ---- experience ---------------------------------------------------
    experience, experience_evidence = classify_experience(
        title=title,
        description=description,
        url=raw_url or url,
        extra=" ".join([ld["experience"], csv_extra]),
    )
    experience_score = EXPERIENCE_SCORE.get(experience, 50)

    # ---- freshness ----------------------------------------------------
    date_candidates = [
        (ld["date_posted"], "JSON-LD datePosted"),
        (meta.get("published", ""), "HTML metadata"),
        (meta.get("visible_date", ""), "visible page date"),
        (clean_text(row.get("date_posted")), "CSV date_posted"),
        (clean_text(row.get("posted")), "CSV posted"),
        (clean_text(row.get("date")), "CSV date"),
        (clean_text(row.get("snippet")), "search snippet"),
    ]

    # relative wording hidden inside the description / snippet ("posted 5 hours ago")
    relative_hit = RELATIVE_DATE_RE.search(csv_description) or RELATIVE_DATE_RE.search(csv_extra)
    if relative_hit:
        date_candidates.append((relative_hit.group(0), "relative date in description"))
    elif re.search(r"\b(?:posted|updated)\s+(?:just now|today)\b", csv_description, re.I):
        date_candidates.append(("today", "relative date in description"))

    posted_dt: Optional[datetime] = None
    date_source = "none"
    date_raw = ""
    for value, source in date_candidates:
        if not value:
            continue
        parsed = parse_datetime_any(value, reference_time)
        if parsed:
            posted_dt = parsed
            date_source = source
            date_raw = value
            break

    freshness = classify_freshness(posted_dt, reference_time)
    freshness_score = FRESHNESS_SCORE[freshness]
    date_posted_out = posted_dt.strftime("%Y-%m-%d %H:%M UTC") if posted_dt else ""

    # ---- role / location / skills -------------------------------------
    role_score, role_evidence = score_role(title, description)
    location_score, location_evidence = score_location(location, title, description)
    matched, missing, skill_score, skill_pct = match_skills(f"{title} {description}")
    positive_signals, negative_signals = fresher_signal_balance(f"{title} {description[:3000]}")

    overall = compute_overall(role_score, location_score, experience_score,
                              skill_score, freshness_score)

    recommendation, rejection_reason = decide(
        experience=experience,
        role_score=role_score,
        location_score=location_score,
        overall=overall,
        freshness=freshness,
        evidence_length=evidence_length,
        positive_signals=positive_signals,
        negative_signals=negative_signals,
        is_individual=is_individual,
        listing_reason=listing_evidence,
    )

    if is_rejected(recommendation):
        overall = min(overall, 45)

    return {
        "job_title": title or "Unknown",
        "company": company,
        "location": location,
        "source": csv_source or (urlparse(url).netloc if url else ""),
        "job_url": raw_url or url,
        "experience": experience,
        "experience_evidence": experience_evidence,
        "freshness": freshness,
        "date_posted": date_posted_out,
        "role_score": role_score,
        "location_score": location_score,
        "experience_score": experience_score,
        "skill_score": skill_score,
        "freshness_score": freshness_score,
        "overall_match": overall,
        "matched_skills": ", ".join(matched),
        "missing_skills": ", ".join(missing),
        "recommendation": recommendation,
        "rejection_reason": rejection_reason,
        "description": truncate(description, 3000),
        # diagnostics
        "is_individual_job": "yes" if is_individual else "no",
        "listing_evidence": listing_evidence,
        "fetch_status": fetch_status,
        "role_evidence": role_evidence,
        "location_evidence": location_evidence,
        "date_source": f"{date_source}: {truncate(date_raw, 60)}" if date_raw else date_source,
        "skill_match_pct": skill_pct,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "job_id": extract_job_id(url),
        "_company_source": company_source,
    }


# --------------------------------------------------------------------------
# CSV INPUT / OUTPUT
# --------------------------------------------------------------------------

def read_input_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Input file '{path}' not found. Run job_search.py first, "
            f"or pass --input <path>.")

    if pd is not None:
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False,
                                encoding="utf-8", on_bad_lines="skip")
            return frame.to_dict(orient="records")
        except Exception:
            pass

    rows: List[Dict[str, Any]] = []
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                rows = [dict(record) for record in reader]
            break
        except Exception:
            continue
    return rows


def write_csv(path: str, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


# --------------------------------------------------------------------------
# SORTING + REPORTING
# --------------------------------------------------------------------------

def sort_key(job: Dict[str, Any]):
    return (
        RECOMMENDATION_RANK.get(job["recommendation"], 0),
        EXPERIENCE_RANK.get(job["experience"], 0),
        FRESHNESS_RANK.get(job["freshness"], 0),
        job["overall_match"],
        job["skill_score"],
    )


def print_report(all_jobs: List[Dict[str, Any]], stats: Dict[str, int],
                 fetcher: PageFetcher, top_n: int = 20) -> None:
    line = "=" * 60
    say(line)
    say("AI JOB ANALYZER")
    say(line)
    say(f"Target Role:              {TARGET_ROLE}")
    say(f"Target City:              {TARGET_CITY}")
    say(f"Country:                  {TARGET_COUNTRY}")
    say(f"Profile:                  {'Fresher' if PROFILE_IS_FRESHER else 'Experienced'}")
    say(f"Analysed at:              {now_utc().strftime('%Y-%m-%d %H:%M UTC')}")
    say("")
    say(f"Input jobs:               {stats['input']}")
    say(f"Unique jobs:              {stats['unique']}")
    say(f"Duplicates removed:       {stats['duplicates']}")
    say(f"Listing pages rejected:   {stats['listing_rejected']}")
    say(f"Individual jobs found:    {stats['individual']}")
    say(f"Accepted jobs:            {stats['accepted']}")
    say(f"Rejected jobs:            {stats['rejected']}")
    say("")
    say(f"Pages fetched OK:         {fetcher.stats['ok']}")
    say(f"Blocked / denied:         {fetcher.stats['blocked']}")
    say(f"Not found (404):          {fetcher.stats['not_found']}")
    say(f"Fetch errors:             {fetcher.stats['error']}")
    say("")

    say(line)
    say("EXPERIENCE DISTRIBUTION")
    say(line)
    for category in EXPERIENCE_CATEGORIES:
        count = sum(1 for job in all_jobs if job["experience"] == category)
        say(f"  {category:<24} {count}")
    say("")

    say(line)
    say("FRESHNESS DISTRIBUTION")
    say(line)
    for category in FRESHNESS_CATEGORIES:
        count = sum(1 for job in all_jobs if job["freshness"] == category)
        say(f"  {category:<24} {count}")
    say("")

    say(line)
    say("DECISION BREAKDOWN")
    say(line)
    for level in (REC_HIGH, REC_APPLY, REC_CONSIDER, REC_LOW, REC_REJ_EXP,
                  REC_REJ_SENIOR, REC_REJ_ROLE, REC_REJ_LOC, REC_REJ_LISTING,
                  REC_REJ_DATA):
        count = sum(1 for job in all_jobs if job["recommendation"] == level)
        say(f"  {level:<38} {count}")
    say("")

    accepted = [job for job in all_jobs if not is_rejected(job["recommendation"])]
    accepted.sort(key=sort_key, reverse=True)

    say(line)
    say(f"TOP {top_n} ELIGIBLE / RECOMMENDED JOBS")
    say(line)
    if not accepted:
        say("  No eligible jobs in this batch.")
    for index, job in enumerate(accepted[:top_n], start=1):
        say(f"\n{index}. {job['job_title']}")
        say(f"   Company     : {job['company']}")
        say(f"   Location    : {job['location'] or 'n/a'}  (score {job['location_score']})")
        say(f"   Experience  : {job['experience']}  (score {job['experience_score']})")
        say(f"   Evidence    : {truncate(job['experience_evidence'], 140)}")
        say(f"   Freshness   : {job['freshness']}"
            + (f"  [{job['date_posted']}]" if job["date_posted"] else ""))
        say(f"   Skills      : {job['matched_skills'] or 'none detected'}")
        say(f"   Overall     : {job['overall_match']}%   Decision: {job['recommendation']}")
        say(f"   URL         : {job['job_url']}")
    say("")


def build_summary_rows(all_jobs: List[Dict[str, Any]], stats: Dict[str, int]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    def add(section: str, metric: str, value: Any) -> None:
        rows.append({"section": section, "metric": metric, "value": str(value)})

    add("profile", "target_role", TARGET_ROLE)
    add("profile", "target_city", TARGET_CITY)
    add("profile", "country", TARGET_COUNTRY)
    add("profile", "profile_type", "Fresher" if PROFILE_IS_FRESHER else "Experienced")
    add("run", "analysed_at_utc", now_utc().strftime("%Y-%m-%d %H:%M:%S"))

    for key in ("input", "unique", "duplicates", "listing_rejected",
                "individual", "accepted", "rejected"):
        add("counts", key, stats[key])

    for category in EXPERIENCE_CATEGORIES:
        add("experience_distribution", category,
            sum(1 for job in all_jobs if job["experience"] == category))
    for category in FRESHNESS_CATEGORIES:
        add("freshness_distribution", category,
            sum(1 for job in all_jobs if job["freshness"] == category))
    for level in (REC_HIGH, REC_APPLY, REC_CONSIDER, REC_LOW, REC_REJ_EXP,
                  REC_REJ_SENIOR, REC_REJ_ROLE, REC_REJ_LOC, REC_REJ_LISTING,
                  REC_REJ_DATA):
        add("decisions", level, sum(1 for job in all_jobs if job["recommendation"] == level))

    return rows


# --------------------------------------------------------------------------
# SELF TEST (the 10 required cases)
# --------------------------------------------------------------------------

def run_self_tests() -> int:
    fetcher = PageFetcher(enabled=False)
    reference = now_utc()

    cases = [
        ("TEST 1", "Data Analyst - Product Analysis - SQL/Power BI - 3 Years - Pune", "",
         EXP_3P, REC_REJ_EXP, "3 years"),
        ("TEST 2", "Senior Data Analyst", "",
         EXP_SENIOR, REC_REJ_SENIOR, "senior"),
        ("TEST 3", "Junior Data Analyst / Fresher", "",
         EXP_0, None, "fresher"),
        ("TEST 4", "Data Analyst - 0-2 years", "",
         EXP_0_2, None, "0-2 years"),
        ("TEST 5", "Data Analyst - 1-3 years", "",
         EXP_1_3, None, "1-3 years"),
        ("TEST 6", "Data Analyst - 2-4 years", "",
         EXP_2_4, REC_REJ_EXP, "2-4 years"),
        ("TEST 7", "Data Analyst - 5+ years", "",
         EXP_5P, REC_REJ_EXP, "5+ years"),
        ("TEST 8", "Data Analyst",
         "We are looking for a graduate/fresher with strong SQL and Power BI skills.",
         EXP_0, None, "fresher"),
        ("TEST 9", "Data Analyst", "Candidates should have 3 years of experience.",
         EXP_3P, REC_REJ_EXP, "3 years"),
        ("TEST 10", "Data Analyst", "Experience not specified.",
         EXP_UNKNOWN, None, ""),
    ]

    # Regression cases taken from real rows that leaked into accepted_jobs.csv
    location_cases = [
        ("REG 1", "[Job-30951] Senior Data Analyst, Brazil", "Brazil",
         "Great analytics role. We hire across India, Brazil and the US.",
         REC_REJ_LOC),
        ("REG 2", "[Job-30951] S\u00eanior Data Analyst, Brazil", "Brazil",
         "Analytics opening. Our India team also grows.", REC_REJ_LOC),
        ("REG 3", "Data Analyst (Remote, India)", "IND, TELECOMMUTE",
         "Remote data analyst role. SQL, Power BI, Excel. Freshers welcome.", None),
        ("REG 4", "Business Intelligence Analyst", "Pune Division, IN",
         "BI analyst. Power BI, SQL, Excel. 0-2 years.", None),
        ("REG 5", "Salesforce Marketing Cloud Analyst", "Pune Division, IN",
         "Manage Salesforce Marketing Cloud journeys and email campaigns. Fresher.",
         REC_REJ_ROLE),
        ("REG 6", "Data Analyst", "Sao Paulo, Brazil",
         "Analytics role. India English required.", REC_REJ_LOC),
    ]

    say("=" * 60)
    say("SELF TEST - required experience classification cases")
    say("=" * 60)

    failures = 0
    for name, title, description, expected_exp, expected_decision, evidence_hint in cases:
        row = {
            "job_title": title,
            "company": "Example Analytics Pvt Ltd",
            "location": "Pune, Maharashtra",
            "source": "selftest",
            "description": description,
            "job_url": "https://www.linkedin.com/jobs/view/1234567890",
        }
        result = analyse_row(row, fetcher, reference_time=reference)
        ok_exp = result["experience"] == expected_exp

        if expected_decision is None:
            ok_dec = not is_rejected(result["recommendation"])
            expected_text = "not rejected"
        else:
            ok_dec = result["recommendation"] == expected_decision
            expected_text = expected_decision

        ok_ev = (evidence_hint.lower() in result["experience_evidence"].lower()
                 if evidence_hint else True)

        passed = ok_exp and ok_dec and ok_ev
        failures += 0 if passed else 1
        status = "PASS" if passed else "FAIL"
        say(f"\n[{status}] {name}: {title}")
        say(f"        experience : {result['experience']}   (expected {expected_exp})")
        say(f"        decision   : {result['recommendation']}   (expected {expected_text})")
        say(f"        evidence   : {truncate(result['experience_evidence'], 160)}")

    say("")
    say("-" * 60)
    say("LOCATION / ROLE REGRESSION CASES")
    say("-" * 60)

    for name, title, location, description, expected in location_cases:
        row = {"job_title": title, "company": "Example Ltd", "location": location,
               "source": "selftest", "description": description,
               "job_url": "https://www.linkedin.com/jobs/view/1234567890"}
        result = analyse_row(row, fetcher, reference_time=reference)
        if expected is None:
            passed = not is_rejected(result["recommendation"])
            expected_text = "not rejected"
        else:
            passed = result["recommendation"] == expected
            expected_text = expected
        failures += 0 if passed else 1
        say(f"\n[{'PASS' if passed else 'FAIL'}] {name}: {title}  |  {location}")
        say(f"        decision   : {result['recommendation']}   (expected {expected_text})")
        say(f"        location   : score {result['location_score']} - {result['location_evidence']}")
        say(f"        role       : score {result['role_score']} - {result['role_evidence']}")

    total = len(cases) + len(location_cases)
    say("")
    say("=" * 60)
    say(f"SELF TEST RESULT: {total - failures}/{total} passed")
    say("=" * 60)
    return failures


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Job Analyzer for a fresher profile")
    parser.add_argument("--input", default=INPUT_FILE, help="input CSV from job_search.py")
    parser.add_argument("--outdir", default=OUTPUT_DIR, help="output directory")
    parser.add_argument("--no-fetch", action="store_true",
                        help="do not fetch job pages; use CSV data only")
    parser.add_argument("--limit", type=int, default=0,
                        help="analyse only the first N unique jobs (0 = all)")
    parser.add_argument("--delay", type=float, default=FETCH_DELAY,
                        help="seconds between HTTP requests")
    parser.add_argument("--top", type=int, default=20, help="how many top jobs to print")
    parser.add_argument("--selftest", action="store_true",
                        help="run the built-in classification test cases and exit")
    return parser.parse_args()


def main() -> int:
    _configure_stdout()

    if load_dotenv is not None:
        try:
            load_dotenv()
        except Exception:
            pass

    args = parse_args()

    if args.selftest:
        return 1 if run_self_tests() else 0

    if requests is None:
        say("NOTE: 'requests' is not installed - running in offline mode (CSV data only).")
    if BeautifulSoup is None:
        say("NOTE: 'beautifulsoup4' is not installed - using regex HTML fallback.")

    try:
        raw_rows = read_input_rows(args.input)
    except FileNotFoundError as error:
        say(f"ERROR: {error}")
        return 1

    stats = {"input": len(raw_rows), "unique": 0, "duplicates": 0,
             "listing_rejected": 0, "individual": 0, "accepted": 0, "rejected": 0}

    if not raw_rows:
        say(f"ERROR: '{args.input}' contains no rows.")
        return 1

    # ---- deduplicate ---------------------------------------------------
    seen: Dict[str, Dict[str, Any]] = {}
    for row in raw_rows:
        key = dedupe_key(row)
        if key in seen:
            existing = seen[key]
            # keep whichever record carries the longer description
            if len(clean_text(row.get("description"))) > len(clean_text(existing.get("description"))):
                seen[key] = row
            stats["duplicates"] += 1
        else:
            seen[key] = row

    unique_rows = list(seen.values())
    stats["unique"] = len(unique_rows)

    if args.limit and args.limit > 0:
        unique_rows = unique_rows[:args.limit]

    fetcher = PageFetcher(enabled=not args.no_fetch, delay=args.delay)

    say("=" * 60)
    say("AI JOB ANALYZER - analysing jobs")
    say("=" * 60)
    say(f"Input file : {args.input}")
    say(f"Unique jobs: {len(unique_rows)}  (from {stats['input']} rows)")
    say(f"Fetching   : {'ON' if fetcher.enabled else 'OFF'}")
    say("")

    reference_time = now_utc()
    analysed: List[Dict[str, Any]] = []

    for index, row in enumerate(unique_rows, start=1):
        try:
            result = analyse_row(row, fetcher, reference_time)
        except Exception as error:  # a single bad row must never kill the run
            result = {column: "" for column in OUTPUT_COLUMNS + EXTRA_COLUMNS}
            result.update({
                "job_title": clean_text(row.get("job_title")) or "Unknown",
                "company": clean_text(row.get("company")) or "Unknown",
                "location": clean_text(row.get("location")),
                "source": clean_text(row.get("source")),
                "job_url": clean_text(row.get("job_url")),
                "experience": EXP_UNKNOWN,
                "experience_evidence": f"analysis error: {type(error).__name__}",
                "freshness": FRESH_UNKNOWN,
                "role_score": 0, "location_score": 0, "experience_score": 0,
                "skill_score": 0, "freshness_score": FRESHNESS_SCORE[FRESH_UNKNOWN],
                "overall_match": 0,
                "recommendation": REC_REJ_DATA,
                "rejection_reason": f"row could not be analysed ({type(error).__name__})",
            })
        analysed.append(result)

        if result["is_individual_job"] == "no":
            stats["listing_rejected"] += 1
        else:
            stats["individual"] += 1

        if index % 10 == 0 or index == len(unique_rows):
            say(f"  processed {index}/{len(unique_rows)} ...")

    stats["accepted"] = sum(1 for job in analysed if not is_rejected(job["recommendation"]))
    stats["rejected"] = sum(1 for job in analysed if is_rejected(job["recommendation"]))

    analysed.sort(key=sort_key, reverse=True)

    accepted_jobs = [job for job in analysed if not is_rejected(job["recommendation"])]
    rejected_jobs = [job for job in analysed if is_rejected(job["recommendation"])]
    recommended_jobs = [job for job in accepted_jobs
                        if job["recommendation"] in (REC_HIGH, REC_APPLY, REC_CONSIDER)]
    high_priority_jobs = [job for job in accepted_jobs if job["recommendation"] == REC_HIGH]
    fresh_jobs = [job for job in accepted_jobs if job["freshness"] in (FRESH_24, FRESH_48)]

    outdir = args.outdir
    if outdir and not os.path.isdir(outdir):
        os.makedirs(outdir, exist_ok=True)

    full_columns = OUTPUT_COLUMNS + EXTRA_COLUMNS
    write_csv(os.path.join(outdir, "analyzed_jobs.csv"), analysed, full_columns)
    write_csv(os.path.join(outdir, "accepted_jobs.csv"), accepted_jobs, full_columns)
    write_csv(os.path.join(outdir, "recommended_jobs.csv"), recommended_jobs, OUTPUT_COLUMNS)
    write_csv(os.path.join(outdir, "high_priority_jobs.csv"), high_priority_jobs, OUTPUT_COLUMNS)
    write_csv(os.path.join(outdir, "fresh_jobs.csv"), fresh_jobs, OUTPUT_COLUMNS)
    write_csv(os.path.join(outdir, "rejected_jobs.csv"), rejected_jobs, full_columns)
    write_csv(os.path.join(outdir, "job_analysis_summary.csv"),
              build_summary_rows(analysed, stats), ["section", "metric", "value"])

    say("")
    print_report(analysed, stats, fetcher, top_n=args.top)

    say("=" * 60)
    say("FILES WRITTEN")
    say("=" * 60)
    for filename, rows in (
        ("analyzed_jobs.csv", analysed),
        ("accepted_jobs.csv", accepted_jobs),
        ("recommended_jobs.csv", recommended_jobs),
        ("high_priority_jobs.csv", high_priority_jobs),
        ("fresh_jobs.csv", fresh_jobs),
        ("rejected_jobs.csv", rejected_jobs),
    ):
        say(f"  {filename:<26} {len(rows)} rows")
    say(f"  {'job_analysis_summary.csv':<26} summary metrics")
    say("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
