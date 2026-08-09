"""
job_search.py
=============

AI Job Application Intelligence Platform - DISCOVERY stage.

Design principle:  SEARCH = HIGH RECALL,  ANALYZER = HIGH PRECISION.

This module discovers as many plausibly relevant job pages as possible and
writes them to job_results.csv for job_analyzer.py to filter strictly.
It deliberately does NOT reject senior jobs, jobs with unknown freshness,
or jobs with missing companies - that is the analyzer's job.

What it does:
  1. Plans ~40 simple, Serper-free-tier-safe queries across role / skill /
     fresher / job-board / remote families (no Cartesian explosion).
  2. Calls the Serper API with retries, backoff and per-error handling.
  3. Normalizes and deduplicates URLs across queries and job boards.
  4. Classifies each URL as an individual job page or a listing page.
  5. Mines listing pages for individual job URLs (LinkedIn / Naukri /
     Indeed / Foundit / Shine / Glassdoor / Internshala / Wellfound ...).
  6. Optionally fetches individual pages and reads JSON-LD JobPosting.
  7. Scores each result for discovery relevance and writes seven CSVs.

Nothing is invented: unknown experience is "Not specified", unknown
freshness is "Unknown", unknown company is "Unknown".

Usage:
    python job_search.py
    python job_search.py --dry-run           # show the query plan, no API calls
    python job_search.py --no-fetch          # search only, never fetch pages
    python job_search.py --max-queries 25
    python job_search.py --selftest          # offline pipeline test, no API calls
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, urljoin, unquote

# --------------------------------------------------------------------------
# OPTIONAL DEPENDENCIES - the script degrades instead of crashing
# --------------------------------------------------------------------------

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

try:
    from dateutil import parser as dateutil_parser
except Exception:  # pragma: no cover
    dateutil_parser = None  # type: ignore

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore


# ==========================================================================
# CONFIGURATION
# ==========================================================================

TARGET_ROLE = "Data Analyst"
TARGET_CITY = "Pune"
TARGET_COUNTRY = "India"

RESUME_SKILLS: List[str] = [
    "Python", "SQL", "Excel", "Power BI", "Tableau", "Snowflake",
    "Pandas", "NumPy", "Machine Learning", "Statistics", "Data Analysis",
    "Streamlit", "ETL", "Data Engineering", "LangChain",
]

# Roles searched explicitly. The analyzer decides real suitability.
ROLE_FAMILY: List[str] = [
    "Data Analyst",
    "Junior Data Analyst",
    "Associate Data Analyst",
    "Data Analytics Analyst",
    "Analytics Associate",
    "BI Analyst",
    "Business Intelligence Analyst",
    "Reporting Analyst",
    "Data Reporting Analyst",
    "MIS Analyst",
    "Data Research Analyst",
    "SQL Analyst",
    "ETL Analyst",
    "Analytics Engineer",
    "BI Developer",
    "Business Analyst",
    "Junior Business Analyst",
]

# Skills that are actually used as search discriminators (high signal only).
SEARCH_SKILLS: List[str] = [
    "Python", "SQL", "Power BI", "Excel", "Tableau",
    "Snowflake", "Machine Learning", "ETL",
]

FRESHER_TERMS: List[str] = [
    "fresher", "freshers", "graduate", "trainee",
    "entry level", "0 to 1 years", "0 to 2 years",
]

JOB_BOARD_HINTS: List[str] = [
    "LinkedIn", "Naukri", "Indeed", "Foundit", "Shine", "Internshala",
]

PUNE_LOCALITIES: List[str] = [
    "pune", "pimpri", "chinchwad", "pimpri-chinchwad", "hinjewadi",
    "hinjawadi", "kharadi", "viman nagar", "baner", "wakad", "magarpatta",
    "hadapsar", "aundh", "kothrud", "balewadi", "yerwada", "bavdhan",
    "shivajinagar", "wagholi", "kalyani nagar", "pcmc",
]

# Query budget: one Serper API call == one query page.
DEFAULT_MAX_QUERIES = 40
RESULTS_PER_QUERY = 20          # Serper 'num'
PAGINATE_TOP_N_QUERIES = 8      # these queries also fetch page 2

SERPER_ENDPOINT = "https://google.serper.dev/search"
SERPER_TIMEOUT = 20
SERPER_MAX_RETRIES = 3
SERPER_BACKOFF_BASE = 2.0
SERPER_DELAY = 1.0              # polite gap between API calls

FETCH_TIMEOUT = 15
FETCH_DELAY = 1.2
FETCH_RETRIES = 2
DEFAULT_MAX_FETCHES = 60        # cap page fetches so a daily run stays quick
MAX_LINKS_PER_LISTING = 15      # individual URLs mined from one listing page

OUTPUT_FILES = [
    "all_raw_jobs.csv",
    "all_unique_jobs.csv",
    "individual_jobs.csv",
    "fresh_jobs_24h.csv",
    "job_results.csv",
    "top_10_jobs.csv",
    "top_20_jobs.csv",
]

USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
]

# Discovery-time country gate. Search is high-recall, but a job explicitly
# advertised for another country is noise, not recall.
FOREIGN_PLACE_RE = re.compile(
    r"(?<![a-z])(?:brazil|brasil|sao paulo|argentina|colombia|chile|peru|mexico|"
    r"united states|u\.s\.a|usa|new york|california|texas|chicago|seattle|"
    r"canada|toronto|vancouver|united kingdom|england|london|ireland|dublin|"
    r"germany|berlin|munich|netherlands|amsterdam|france|paris|spain|madrid|"
    r"barcelona|portugal|lisbon|italy|milan|poland|warsaw|krakow|romania|"
    r"bucharest|hungary|budapest|czech|prague|sweden|stockholm|norway|denmark|"
    r"copenhagen|belgium|brussels|austria|vienna|switzerland|zurich|greece|"
    r"athens|singapore|malaysia|kuala lumpur|philippines|manila|indonesia|"
    r"jakarta|vietnam|thailand|bangkok|japan|tokyo|china|shanghai|beijing|"
    r"hong kong|taiwan|south korea|seoul|australia|sydney|melbourne|"
    r"new zealand|dubai|abu dhabi|uae|qatar|doha|saudi|riyadh|kuwait|oman|"
    r"bahrain|israel|tel aviv|egypt|cairo|kenya|nairobi|nigeria|south africa|"
    r"sri lanka|colombo|bangladesh|dhaka|nepal|kathmandu|pakistan|karachi|"
    r"lahore|emea|latam)(?![a-z])", re.I)

INDIA_PLACE_RE = re.compile(
    r"(?<![a-z])(?:india|indian|bharat|ind|maharashtra|karnataka|telangana|"
    r"tamil nadu|kerala|gujarat|haryana|punjab|rajasthan|west bengal|"
    r"uttar pradesh|madhya pradesh|andhra pradesh|odisha|pune|mumbai|"
    r"bengaluru|bangalore|hyderabad|chennai|delhi|noida|gurgaon|gurugram|"
    r"kolkata|ahmedabad|indore|jaipur|chandigarh|coimbatore|kochi|nagpur|"
    r"nashik|thane|telecommute)(?![a-z])", re.I)

STRICT_INDIA_ONLY = True

FRESH_24 = "within_24_hours"
FRESH_48 = "24_to_48_hours"
FRESH_OLD = "older"
FRESH_UNKNOWN = "unknown"

NOT_SPECIFIED = "Not specified"
UNKNOWN = "Unknown"

logger = logging.getLogger("job_search")


# ==========================================================================
# SMALL UTILITIES
# ==========================================================================

def configure_logging(verbose: bool = False) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def say(text: str = "") -> None:
    """print() that survives consoles which cannot render every glyph."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(re.sub(r"[^\x00-\x7F]+", "", text))


def fold(value: Any) -> str:
    """Strip accents for matching ('Senior' == 'Senior'). Output keeps originals."""
    text = clean(value)
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def truncate(text: str, limit: int = 2000) -> str:
    text = clean(text)
    return text if len(text) <= limit else text[:limit] + " ..."


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ==========================================================================
# URL HANDLING
# ==========================================================================

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referer", "referrer", "source", "src", "trk", "trkinfo",
    "originalsubdomain", "position", "pagenum", "refid", "gclid", "fbclid",
    "sid", "cid", "campaign", "medium", "recommended", "savedsearchid",
    "eboa", "spa", "from", "utm_id", "vjs", "tk", "advn", "adid",
}

KEEP_PARAMS = {"jk", "currentjobid", "vjk", "jobid", "job_id", "id", "jid", "gh_jid"}


def normalize_url(url: str) -> str:
    """Canonical form: https, no www/m prefix, no fragment, no tracking params."""
    url = clean(url)
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    try:
        parts = urlparse(url)
    except Exception:
        return url

    netloc = parts.netloc.lower()
    for prefix in ("www.", "m.", "in."):
        if netloc.startswith(prefix) and netloc != prefix.strip("."):
            netloc = netloc[len(prefix):]
            break

    kept: List[Tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        key_l = key.lower()
        if key_l in TRACKING_PARAMS:
            continue
        if key_l in KEEP_PARAMS or len(kept) < 4:
            kept.append((key_l, value))
    kept.sort()

    return urlunparse(("https", netloc, parts.path.rstrip("/"), "",
                       urlencode(kept), ""))


def domain_of(url: str) -> str:
    try:
        netloc = urlparse(normalize_url(url)).netloc
    except Exception:
        return ""
    return netloc


SOURCE_NAMES = {
    "linkedin.com": "LinkedIn", "naukri.com": "Naukri", "indeed.com": "Indeed",
    "foundit.in": "Foundit", "monsterindia.com": "Foundit", "shine.com": "Shine",
    "glassdoor.co.in": "Glassdoor", "glassdoor.com": "Glassdoor",
    "jobaaj.com": "Jobaaj", "internshala.com": "Internshala",
    "wellfound.com": "Wellfound", "angel.co": "Wellfound",
    "timesjobs.com": "TimesJobs", "instahyre.com": "Instahyre",
    "cutshort.io": "Cutshort", "hirist.tech": "Hirist", "iimjobs.com": "IIMJobs",
    "freshersworld.com": "FreshersWorld", "apna.co": "Apna",
    "greenhouse.io": "Greenhouse", "lever.co": "Lever",
    "myworkdayjobs.com": "Workday", "smartrecruiters.com": "SmartRecruiters",
}


def source_of(url: str) -> str:
    host = domain_of(url)
    for key, name in SOURCE_NAMES.items():
        if host.endswith(key):
            return name
    return host or "Web"


# --- individual job page patterns (deliberately broad, multi-site) ---------

INDIVIDUAL_PATTERNS: List[re.Pattern] = [
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
    re.compile(r"internshala\.com/(?:job|internship)/detail/", re.I),
    re.compile(r"wellfound\.com/(?:jobs|company/[^/]+/jobs)/\d+", re.I),
    re.compile(r"angel\.co/company/[^/]+/jobs/\d+", re.I),
    re.compile(r"timesjobs\.com/job-detail", re.I),
    re.compile(r"instahyre\.com/job-", re.I),
    re.compile(r"cutshort\.io/job/", re.I),
    re.compile(r"hirist\.tech/j/", re.I),
    re.compile(r"iimjobs\.com/j/", re.I),
    re.compile(r"freshersworld\.com/jobs/jobdetail/", re.I),
    re.compile(r"apna\.co/jobs/[^/]+-\d+", re.I),
    re.compile(r"boards\.greenhouse\.io/[^/]+/jobs/\d+", re.I),
    re.compile(r"jobs\.lever\.co/[^/]+/[0-9a-f\-]{8,}", re.I),
    re.compile(r"myworkdayjobs\.com/.+/job/", re.I),
    re.compile(r"smartrecruiters\.com/[^/]+/\d{6,}", re.I),
    # generic company career pages
    re.compile(r"/job/\d{4,}", re.I),
    re.compile(r"/jobs?/[^/]+-\d{5,}", re.I),
    re.compile(r"/careers?/(?:job|opening|position|vacanc(?:y|ies))s?/[^/]{6,}", re.I),
    re.compile(r"[?&](?:jobId|job_id|requisitionId|reqId|gh_jid)=", re.I),
]

LISTING_PATTERNS: List[re.Pattern] = [
    re.compile(r"linkedin\.com/jobs/search", re.I),
    re.compile(r"linkedin\.com/jobs/[a-z\-]+-jobs", re.I),
    re.compile(r"naukri\.com/[a-z0-9\-]*jobs-in-[a-z\-]+", re.I),
    re.compile(r"naukri\.com/(?:jobs|search|browse)", re.I),
    re.compile(r"naukri\.com/[a-z\-]+-jobs(?:$|[/?])", re.I),
    re.compile(r"indeed\.[a-z.]+/(?:jobs|q-|browsejobs)", re.I),
    re.compile(r"foundit\.in/(?:search|srp|jobs)", re.I),
    re.compile(r"shine\.com/job-search", re.I),
    re.compile(r"glassdoor\.[a-z.]+/Job/", re.I),
    re.compile(r"internshala\.com/(?:jobs|internships)/", re.I),
    re.compile(r"wellfound\.com/(?:role|jobs)(?:$|/[a-z\-]+$)", re.I),
    re.compile(r"/job-search", re.I),
    re.compile(r"/jobs-in-[a-z\-]+", re.I),
    re.compile(r"/(?:category|categories|browse|explore|listings?)(?:$|/)", re.I),
    re.compile(r"/(?:jobs|careers|vacancies|openings)/?$", re.I),
    re.compile(r"[?&](?:q|k|keyword|keywords|query|searchTerm)=", re.I),
    re.compile(r"/search(?:$|[/?])", re.I),
]

JUNK_PATTERNS: List[re.Pattern] = [
    re.compile(r"linkedin\.com/(?:in|pub)/", re.I),
    re.compile(r"(?:facebook|twitter|x|instagram|youtube|reddit|quora|pinterest)\.com", re.I),
    re.compile(r"\.(?:pdf|doc|docx|xls|xlsx|zip|jpg|png)$", re.I),
    re.compile(r"(?:coursera|udemy|edx|simplilearn|wikipedia|glassdoor\.[a-z.]+/Salaries)", re.I),
]

JOB_ID_PATTERNS = [
    re.compile(r"linkedin\.com/jobs/view/(\d+)", re.I),
    re.compile(r"[?&]currentJobId=(\d+)", re.I),
    re.compile(r"[?&]jk=([0-9a-zA-Z]+)", re.I),
    re.compile(r"naukri\.com/job-listings-[^/?]*?-(\d{6,})", re.I),
    re.compile(r"/job/[^/?]*?-(\d{6,})", re.I),
    re.compile(r"[?&]gh_jid=(\d+)", re.I),
]


def is_junk_url(url: str) -> bool:
    return any(pattern.search(url) for pattern in JUNK_PATTERNS)


def is_individual_job_url(url: str) -> bool:
    """Broad, multi-site detection. Individual patterns win over listing ones."""
    url = clean(url)
    if not url or is_junk_url(url):
        return False
    if any(pattern.search(url) for pattern in INDIVIDUAL_PATTERNS):
        return True
    if any(pattern.search(url) for pattern in LISTING_PATTERNS):
        return False

    parts = urlparse(normalize_url(url))
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        return False
    last = segments[-1]
    has_id = bool(re.search(r"\d{4,}", last)) or bool(re.search(r"[0-9a-f]{8,}", last, re.I))
    has_slug = last.count("-") >= 2
    job_path = any(segment.lower() in {"job", "jobs", "vacancy", "opening",
                                       "position", "career", "careers"}
                   for segment in segments[:-1])
    if has_id and (has_slug or job_path):
        return True
    if job_path and has_slug:
        return True
    return False


def is_listing_url(url: str) -> bool:
    if is_individual_job_url(url):
        return False
    return any(pattern.search(url) for pattern in LISTING_PATTERNS)


def extract_job_id(url: str) -> str:
    for pattern in JOB_ID_PATTERNS:
        match = pattern.search(url or "")
        if match:
            return match.group(1)
    return ""


# ==========================================================================
# DATA MODEL
# ==========================================================================

@dataclass
class JobRecord:
    """One discovered job candidate. Discovery data only - never a verdict."""
    job_title: str = ""
    company: str = UNKNOWN
    location: str = ""
    country: str = TARGET_COUNTRY
    experience: str = NOT_SPECIFIED
    freshness: str = FRESH_UNKNOWN
    date_posted: str = ""
    source: str = ""
    job_url: str = ""
    normalized_url: str = ""
    job_id: str = ""
    description: str = ""
    snippet: str = ""
    skills: str = ""
    search_query: str = ""
    search_keyword: str = ""
    page_type: str = "unknown"        # individual | listing | unknown
    origin: str = "serp"              # serp | listing_extraction
    fetch_status: str = "not_fetched"  # fetched | blocked | not_found | error | skipped
    discovery_score: int = 0
    score_breakdown: str = ""
    found_at: str = field(default_factory=lambda: now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"))

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SearchQuery:
    query: str
    category: str
    keyword: str
    priority: int = 5
    page: int = 1


@dataclass
class RunStats:
    queries_planned: int = 0
    queries_executed: int = 0
    queries_failed: int = 0
    api_errors: int = 0
    raw_results: int = 0
    unique_jobs: int = 0
    individual_jobs: int = 0
    listing_pages: int = 0
    mined_from_listings: int = 0
    fresh_jobs: int = 0
    unknown_freshness: int = 0
    pages_fetched: int = 0
    pages_blocked: int = 0


# ==========================================================================
# QUERY PLANNER
# ==========================================================================

def plan_queries(max_queries: int = DEFAULT_MAX_QUERIES) -> List[SearchQuery]:
    """
    Build ~40 simple, natural-language queries. No nested OR, no negative
    operators, no site: syntax - those trigger Serper's free-tier
    "Query pattern not allowed" 400 error.

    Categories are interleaved so that lowering --max-queries keeps the mix
    balanced instead of dropping an entire category.
    """
    city, country = TARGET_CITY, TARGET_COUNTRY
    buckets: Dict[str, List[SearchQuery]] = {}

    # --- ROLE queries -------------------------------------------------
    role_queries = [
        SearchQuery(f"{role} jobs {city} {country}", "role", role,
                    priority=9 if index < 6 else 6)
        for index, role in enumerate(ROLE_FAMILY)
    ]
    buckets["role"] = role_queries

    # --- SKILL queries ------------------------------------------------
    buckets["skill"] = [
        SearchQuery(f"{skill} {TARGET_ROLE} jobs {city} {country}", "skill", skill,
                    priority=8 if index < 4 else 5)
        for index, skill in enumerate(SEARCH_SKILLS)
    ]

    # --- FRESHER queries ----------------------------------------------
    fresher_targets = [TARGET_ROLE, TARGET_ROLE, "Data Analytics", "BI Analyst",
                       "Business Analyst", TARGET_ROLE, "MIS Analyst"]
    buckets["fresher"] = [
        SearchQuery(f"{term} {fresher_targets[index % len(fresher_targets)]} jobs {city} {country}",
                    "fresher", term, priority=9 if index < 4 else 6)
        for index, term in enumerate(FRESHER_TERMS)
    ]

    # --- JOB BOARD queries (simple hint words, not site: operators) ----
    buckets["board"] = [
        SearchQuery(f"{TARGET_ROLE} jobs {city} {board}", "board", board,
                    priority=8 if index < 3 else 5)
        for index, board in enumerate(JOB_BOARD_HINTS)
    ]

    # --- REMOTE / HYBRID / CAREER-PAGE queries -------------------------
    buckets["other"] = [
        SearchQuery(f"{TARGET_ROLE} remote jobs {country}", "remote", "remote", 7),
        SearchQuery(f"{TARGET_ROLE} hybrid jobs {city}", "remote", "hybrid", 6),
        SearchQuery(f"{TARGET_ROLE} jobs Hinjewadi {city}", "locality", "Hinjewadi", 6),
        SearchQuery(f"{TARGET_ROLE} careers {city} {country} apply", "career", "career page", 5),
        SearchQuery(f"entry level analytics jobs {city} {country}", "fresher", "entry level", 7),
    ]

    # --- interleave so truncation stays balanced -----------------------
    order = ["role", "fresher", "skill", "board", "other"]
    interleaved: List[SearchQuery] = []
    index = 0
    while len(interleaved) < sum(len(bucket) for bucket in buckets.values()):
        added = False
        for name in order:
            bucket = buckets[name]
            if index < len(bucket):
                interleaved.append(bucket[index])
                added = True
        if not added:
            break
        index += 1

    planned = interleaved[:max_queries]

    # --- pagination for the highest-priority queries, inside budget ----
    remaining = max_queries - len(planned)
    if remaining > 0:
        top = sorted(planned, key=lambda item: -item.priority)[:PAGINATE_TOP_N_QUERIES]
        for query in top[:remaining]:
            planned.append(SearchQuery(query.query, query.category,
                                       query.keyword, query.priority, page=2))

    return planned[:max_queries]


# ==========================================================================
# SERPER CLIENT
# ==========================================================================

class SerperClient:
    """Serper API wrapper with retries, backoff and per-status handling."""

    def __init__(self, api_key: str, stats: RunStats, delay: float = SERPER_DELAY):
        self.api_key = api_key
        self.stats = stats
        self.delay = delay
        self.session = requests.Session() if requests is not None else None
        if self.session is not None:
            self.session.headers.update({
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            })

    def search(self, query: SearchQuery) -> List[Dict[str, Any]]:
        """Returns a list of organic results; never raises."""
        if self.session is None:
            logger.error("requests is not installed - cannot call Serper")
            self.stats.queries_failed += 1
            return []

        payload = {
            "q": query.query,
            "gl": "in",          # India only
            "hl": "en",
            "location": f"{TARGET_CITY}, {TARGET_COUNTRY}",
            "num": RESULTS_PER_QUERY,
        }
        if query.page > 1:
            payload["page"] = query.page

        for attempt in range(1, SERPER_MAX_RETRIES + 1):
            try:
                response = self.session.post(SERPER_ENDPOINT, json=payload,
                                             timeout=SERPER_TIMEOUT)
                status = response.status_code

                if status == 200:
                    self.stats.queries_executed += 1
                    time.sleep(self.delay)
                    return self._organic(response)

                if status == 400:
                    # e.g. "Query pattern not allowed for free accounts."
                    detail = truncate(response.text, 160)
                    logger.warning("400 from Serper for %r - skipping. %s",
                                   query.query, detail)
                    self.stats.queries_failed += 1
                    self.stats.api_errors += 1
                    return []

                if status in (401, 403):
                    logger.error("Serper rejected the API key (HTTP %s). "
                                 "Check SERPER_API_KEY in .env", status)
                    self.stats.queries_failed += 1
                    self.stats.api_errors += 1
                    return []

                if status == 429:
                    wait = SERPER_BACKOFF_BASE ** attempt + random.uniform(0, 1)
                    logger.warning("429 rate limited - backing off %.1fs", wait)
                    self.stats.api_errors += 1
                    time.sleep(wait)
                    continue

                logger.warning("HTTP %s from Serper for %r", status, query.query)
                self.stats.api_errors += 1

            except Exception as error:
                logger.warning("Serper request failed (%s) for %r",
                               type(error).__name__, query.query)
                self.stats.api_errors += 1

            if attempt < SERPER_MAX_RETRIES:
                time.sleep(SERPER_BACKOFF_BASE ** attempt + random.uniform(0, 0.5))

        self.stats.queries_failed += 1
        return []

    @staticmethod
    def _organic(response: Any) -> List[Dict[str, Any]]:
        try:
            payload = response.json()
        except Exception:
            return []
        results: List[Dict[str, Any]] = []
        for key in ("organic", "jobs", "topStories"):
            block = payload.get(key)
            if isinstance(block, list):
                results.extend(item for item in block if isinstance(item, dict))
        return results


class MockSerperClient(SerperClient):
    """Offline client used by --selftest. Makes no network calls."""

    def __init__(self, stats: RunStats, fixtures: List[Dict[str, Any]]):
        self.stats = stats
        self.delay = 0.0
        self.session = None
        self.api_key = "mock"
        self._fixtures = fixtures
        self._cursor = 0

    def search(self, query: SearchQuery) -> List[Dict[str, Any]]:
        self.stats.queries_executed += 1
        chunk = self._fixtures[self._cursor:self._cursor + 12]
        self._cursor = (self._cursor + 9) % max(1, len(self._fixtures))
        return chunk


# ==========================================================================
# FRESHNESS
# ==========================================================================

RELATIVE_RE = re.compile(r"\b(\d{1,3})\+?\s*(minute|min|hour|hr|day|week|month)s?\s+ago\b", re.I)

DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
]


def parse_any_date(value: str, reference: Optional[datetime] = None) -> Optional[datetime]:
    """Parse absolute or relative date wording. Returns None when unsure."""
    value = clean(value)
    if not value:
        return None
    reference = reference or now_utc()
    lowered = value.lower()

    if any(token in lowered for token in ("just posted", "just now", "posted today", "today")):
        return reference - timedelta(hours=2)
    if "yesterday" in lowered:
        return reference - timedelta(days=1)

    match = RELATIVE_RE.search(lowered)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        deltas = {
            "minute": timedelta(minutes=amount), "min": timedelta(minutes=amount),
            "hour": timedelta(hours=amount), "hr": timedelta(hours=amount),
            "day": timedelta(days=amount), "week": timedelta(weeks=amount),
            "month": timedelta(days=30 * amount),
        }
        return reference - deltas[unit]

    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+0000"
    candidate = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", candidate)
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt)
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
        except ValueError:
            continue

    if dateutil_parser is not None:
        try:
            parsed = dateutil_parser.parse(candidate, fuzzy=False)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def classify_freshness(posted: Optional[datetime],
                       reference: Optional[datetime] = None) -> str:
    """Unknown stays unknown - it is never upgraded to fresh."""
    if posted is None:
        return FRESH_UNKNOWN
    reference = reference or now_utc()
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age = reference - posted
    if age <= timedelta(hours=24):
        return FRESH_24
    if age <= timedelta(hours=48):
        return FRESH_48
    return FRESH_OLD


# ==========================================================================
# PAGE FETCHING + ENRICHMENT
# ==========================================================================

class PageFetcher:
    """Defensive HTTP fetcher. Blocked pages are marked, never discarded."""

    def __init__(self, enabled: bool, stats: RunStats, delay: float = FETCH_DELAY):
        self.enabled = enabled and requests is not None
        self.stats = stats
        self.delay = delay
        self.cache: Dict[str, Tuple[Optional[str], str]] = {}
        self.session = requests.Session() if self.enabled else None
        if self.session is not None:
            self.session.headers.update({
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
                "Connection": "close",
            })

    def get(self, url: str) -> Tuple[Optional[str], str]:
        """Returns (html_or_None, fetch_status)."""
        url = clean(url)
        if not url:
            return None, "skipped"
        if not self.enabled:
            return None, "skipped"
        if url in self.cache:
            return self.cache[url]

        result: Tuple[Optional[str], str] = (None, "error")
        for attempt in range(FETCH_RETRIES + 1):
            try:
                response = self.session.get(  # type: ignore[union-attr]
                    url, timeout=FETCH_TIMEOUT, allow_redirects=True,
                    headers={"User-Agent": USER_AGENTS[attempt % len(USER_AGENTS)]},
                )
                status = response.status_code
                text = response.text or ""

                if status == 200:
                    if len(text.strip()) < 500:
                        result = (None, "blocked")      # JS-rendered or empty
                    elif re.search(r"(cf-browser-verification|Just a moment|"
                                   r"Attention Required!|enable JavaScript and cookies)",
                                   text, re.I):
                        result = (None, "blocked")
                    else:
                        result = (text, "fetched")
                        self.stats.pages_fetched += 1
                    break
                if status in (401, 403):
                    result = (None, "blocked")
                    break
                if status == 404:
                    result = (None, "not_found")
                    break
                if status == 429:
                    time.sleep(self.delay * (attempt + 2))
                    continue
                result = (None, "error")
            except Exception as error:
                logger.debug("fetch failed %s: %s", url, type(error).__name__)
                result = (None, "error")
            time.sleep(self.delay)

        if result[1] == "blocked":
            self.stats.pages_blocked += 1
        self.cache[url] = result
        time.sleep(self.delay)
        return result


TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                tag.decompose()
            return clean(soup.get_text(" "))
        except Exception:
            pass
    text = SCRIPT_RE.sub(" ", html)
    text = TAG_RE.sub(" ", text)
    return clean(text.replace("&nbsp;", " ").replace("&amp;", "&"))


def _walk_json(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _walk_json(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _walk_json(item)


def extract_jsonld_job(html: str) -> Dict[str, Any]:
    """Return the JSON-LD JobPosting object if the page publishes one."""
    if not html:
        return {}
    blocks: List[str] = []
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
                blocks.append(tag.string or tag.text or "")
        except Exception:
            blocks = []
    if not blocks:
        blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.S | re.I)

    for block in blocks:
        block = (block or "").strip()
        if not block:
            continue
        try:
            payload = json.loads(block)
        except Exception:
            try:
                payload = json.loads(re.sub(r",\s*([}\]])", r"\1", block))
            except Exception:
                continue
        for obj in _walk_json(payload):
            types = obj.get("@type") or obj.get("type")
            types = types if isinstance(types, list) else [types]
            if any(str(item).lower() == "jobposting" for item in types if item):
                return obj
    return {}


def enrich_from_jsonld(record: JobRecord, jobposting: Dict[str, Any],
                       reference: datetime) -> None:
    """Fill blanks from structured data. Never overwrites with empty values."""
    if not jobposting:
        return

    title = clean(jobposting.get("title"))
    if title:
        record.job_title = title

    organisation = jobposting.get("hiringOrganization")
    name = clean(organisation.get("name")) if isinstance(organisation, dict) else clean(organisation)
    if name:
        record.company = name

    parts: List[str] = []
    locations = jobposting.get("jobLocation")
    locations = locations if isinstance(locations, list) else [locations]
    for entry in locations:
        if isinstance(entry, dict):
            address = entry.get("address")
            if isinstance(address, dict):
                for key in ("addressLocality", "addressRegion", "addressCountry"):
                    value = address.get(key)
                    value = value.get("name") if isinstance(value, dict) else value
                    if value:
                        parts.append(clean(value))
            elif address:
                parts.append(clean(address))
        elif entry:
            parts.append(clean(entry))
    if jobposting.get("jobLocationType"):
        parts.append(clean(jobposting.get("jobLocationType")))
    if parts:
        record.location = ", ".join(dict.fromkeys(part for part in parts if part))

    description = clean(html_to_text(str(jobposting.get("description") or "")))
    if description:
        record.description = truncate(description, 3000)

    experience = jobposting.get("experienceRequirements")
    if isinstance(experience, dict):
        months = experience.get("monthsOfExperience")
        if months is not None:
            try:
                record.experience = f"{int(months) // 12} years"
            except Exception:
                record.experience = clean(str(months)) or NOT_SPECIFIED
        else:
            record.experience = clean(experience.get("description")) or record.experience
    elif experience:
        record.experience = clean(str(experience)) or record.experience

    posted = parse_any_date(clean(jobposting.get("datePosted")), reference)
    if posted:
        record.date_posted = posted.strftime("%Y-%m-%d %H:%M UTC")
        record.freshness = classify_freshness(posted, reference)


META_DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']',
    re.S | re.I)
META_DATE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|datePosted|og:updated_time)["\'][^>]+content=["\'](.*?)["\']',
    re.S | re.I)


def enrich_record(record: JobRecord, fetcher: PageFetcher, reference: datetime) -> None:
    """Fetch the individual job page and fill in whatever it publishes."""
    html, status = fetcher.get(record.job_url)
    record.fetch_status = status
    if not html:
        return                                    # URL is preserved regardless

    enrich_from_jsonld(record, extract_jsonld_job(html), reference)

    if not record.description:
        meta = META_DESC_RE.search(html)
        body = clean(meta.group(1)) if meta else html_to_text(html)[:3000]
        if body:
            record.description = truncate(body, 3000)

    if record.freshness == FRESH_UNKNOWN:
        meta_date = META_DATE_RE.search(html)
        if meta_date:
            posted = parse_any_date(clean(meta_date.group(1)), reference)
            if posted:
                record.date_posted = posted.strftime("%Y-%m-%d %H:%M UTC")
                record.freshness = classify_freshness(posted, reference)


# ==========================================================================
# LISTING PAGE MINING
# ==========================================================================

def mine_listing_page(record: JobRecord, fetcher: PageFetcher) -> List[str]:
    """
    Pull individual job URLs out of a listing/search page.
    This is what stops the run from collapsing to "0 jobs" when search
    engines mostly return listing pages.
    """
    html, status = fetcher.get(record.job_url)
    record.fetch_status = status
    if not html:
        return []

    hrefs: List[str] = []
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            hrefs = [anchor.get("href") for anchor in soup.find_all("a", href=True)]
        except Exception:
            hrefs = []
    if not hrefs:
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)

    base = record.job_url
    found: List[str] = []
    seen: set = set()
    for href in hrefs:
        if not href:
            continue
        href = unquote(clean(href))
        if href.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = href if href.startswith("http") else urljoin(base, href)
        if not is_individual_job_url(absolute):
            continue
        key = normalize_url(absolute)
        if key in seen:
            continue
        seen.add(key)
        found.append(absolute)
        if len(found) >= MAX_LINKS_PER_LISTING:
            break
    return found


# ==========================================================================
# RECORD BUILDING
# ==========================================================================

COMPANY_JUNK = {
    "sql", "python", "excel", "power bi", "tableau", "pune", "mumbai", "india",
    "jobs", "job", "apply", "fresher", "freshers", "data analyst", "analyst",
    "hiring", "careers", "career", "remote", "n/a", "na", "none", "unknown",
    "linkedin", "naukri", "indeed", "foundit", "shine", "glassdoor", "monster",
}

TITLE_SPLIT_RE = re.compile(r"\s+[-|–—]\s+")


def parse_serp_result(item: Dict[str, Any], query: SearchQuery,
                      reference: datetime) -> Optional[JobRecord]:
    """Turn one Serper organic result into a JobRecord. Discovery data only."""
    url = clean(item.get("link") or item.get("url"))
    if not url or is_junk_url(url):
        return None

    raw_title = clean(item.get("title"))
    snippet = clean(item.get("snippet") or item.get("description"))
    normalized = normalize_url(url)

    # Country gate: a foreign place named in the title (or in the snippet with
    # no Indian place anywhere) means this posting is not for the Indian market.
    folded_title = fold(raw_title)
    folded_all = fold(f"{raw_title} {snippet} {item.get('location') or ''}")
    if STRICT_INDIA_ONLY:
        if FOREIGN_PLACE_RE.search(folded_title) and not INDIA_PLACE_RE.search(folded_title):
            logger.debug("dropped non-India result: %s", raw_title)
            return None
        if FOREIGN_PLACE_RE.search(folded_all) and not INDIA_PLACE_RE.search(folded_all):
            logger.debug("dropped non-India result: %s", raw_title)
            return None

    record = JobRecord(
        job_title=raw_title or TARGET_ROLE,
        location=clean(item.get("location")) or "",
        source=source_of(url),
        job_url=url,
        normalized_url=normalized,
        job_id=extract_job_id(normalized),
        snippet=snippet,
        description=snippet,
        search_query=query.query,
        search_keyword=query.keyword,
        page_type="individual" if is_individual_job_url(url)
                  else "listing" if is_listing_url(url) else "unknown",
    )

    # company: Serper sometimes supplies it; otherwise use a safe title pattern
    company = clean(item.get("company") or item.get("companyName"))
    if not company:
        segments = TITLE_SPLIT_RE.split(raw_title)
        for segment in reversed(segments[1:]):
            candidate = clean(re.sub(r"\b(jobs?|hiring|careers?|apply now)\b", "",
                                     segment, flags=re.I))
            if (2 < len(candidate) <= 60 and candidate.lower() not in COMPANY_JUNK
                    and not re.search(r"\b(years?|yrs?)\b", candidate, re.I)
                    and not any(city in candidate.lower() for city in PUNE_LOCALITIES)):
                company = candidate
                break
    record.company = company or UNKNOWN

    # location straight from the visible text, stored exactly as found
    if not record.location:
        haystack = f"{raw_title} {snippet}"
        for locality in PUNE_LOCALITIES:
            match = re.search(rf"\b{re.escape(locality)}\b", haystack, re.I)
            if match:
                record.location = match.group(0)
                break

    # freshness from the SERP date field / snippet wording only
    posted = parse_any_date(clean(item.get("date")), reference) or \
        parse_any_date(snippet, reference)
    if posted:
        record.date_posted = posted.strftime("%Y-%m-%d %H:%M UTC")
        record.freshness = classify_freshness(posted, reference)

    record.skills = ", ".join(detect_skills(f"{raw_title} {snippet}"))
    return record


SKILL_PATTERNS: Dict[str, re.Pattern] = {
    "Python": re.compile(r"\bpython\b", re.I),
    "SQL": re.compile(r"\b(?:sql|mysql|postgresql|pl/?sql|sql server)\b", re.I),
    "Excel": re.compile(r"\b(?:excel|vlookup|pivot tables?)\b", re.I),
    "Power BI": re.compile(r"(?:\bpower\s*-?\s*bi\b|\bpowerbi\b|\bdax\b)", re.I),
    "Tableau": re.compile(r"\btableau\b", re.I),
    "Snowflake": re.compile(r"\bsnowflake\b", re.I),
    "Pandas": re.compile(r"\bpandas\b", re.I),
    "NumPy": re.compile(r"\bnumpy\b", re.I),
    "Machine Learning": re.compile(r"\b(?:machine learning|scikit-?learn|sklearn)\b", re.I),
    "Statistics": re.compile(r"\b(?:statistics|statistical|regression)\b", re.I),
    "Data Analysis": re.compile(r"\b(?:data analysis|data analytics|data analyst)\b", re.I),
    "Streamlit": re.compile(r"\bstreamlit\b", re.I),
    "ETL": re.compile(r"\b(?:etl|elt|data pipelines?|informatica)\b", re.I),
    "Data Engineering": re.compile(r"\b(?:data engineering|databricks|py ?spark|airflow)\b", re.I),
    "LangChain": re.compile(r"\b(?:langchain|llm|generative ai|gen ?ai|rag)\b", re.I),
}


def detect_skills(text: str) -> List[str]:
    text = fold(text)
    return [skill for skill in RESUME_SKILLS
            if skill in SKILL_PATTERNS and SKILL_PATTERNS[skill].search(text)]


# ==========================================================================
# DISCOVERY SCORING  (relevance for ranking, NOT suitability)
# ==========================================================================

ROLE_EXACT_RE = re.compile(r"\bdata\s+analyst\b", re.I)
ROLE_RELATED_RE = re.compile(
    r"\b(?:bi analyst|business intelligence|reporting analyst|mis analyst|"
    r"analytics associate|sql analyst|etl analyst|analytics engineer|"
    r"bi developer|business analyst|data analytics|research analyst|"
    r"analytics analyst|data analysis)\b", re.I)
FRESHER_RE = re.compile(
    r"\b(?:fresher|freshers|fresh graduate|entry[\s\-]?level|junior|trainee|"
    r"graduate|associate|0\s*-\s*[12]\s*(?:years?|yrs?)|0\s*to\s*[12]\s*(?:years?|yrs?))\b",
    re.I)
SENIOR_RE = re.compile(
    r"\b(?:senior|sr\.?|lead|principal|architect|manager|director|head|"
    r"[3-9]\+?\s*(?:years?|yrs?))\b", re.I)


def score_discovery(record: JobRecord) -> Tuple[int, str]:
    """
    Preliminary relevance score, 0-100. Senior jobs lose points but are
    kept - the analyzer makes the final call.
    """
    text = fold(f"{record.job_title} {record.snippet} {record.description[:800]}")
    location_text = fold(f"{record.location} {text}")
    score = 0
    notes: List[str] = []

    folded_title = fold(record.job_title)
    if ROLE_EXACT_RE.search(folded_title):
        score += 25
        notes.append("role:exact+25")
    elif ROLE_RELATED_RE.search(folded_title):
        score += 18
        notes.append("role:related+18")
    elif ROLE_EXACT_RE.search(text) or ROLE_RELATED_RE.search(text):
        score += 10
        notes.append("role:body+10")

    skills = detect_skills(text)
    skill_points = min(20, 4 * len(skills))
    if skill_points:
        score += skill_points
        notes.append(f"skills:{len(skills)}+{skill_points}")

    if any(re.search(rf"\b{re.escape(locality)}\b", location_text, re.I)
           for locality in PUNE_LOCALITIES):
        score += 20
        notes.append("location:pune+20")
    elif re.search(r"\b(?:remote|work from home|hybrid)\b", location_text, re.I):
        score += 10
        notes.append("location:remote+10")
    elif re.search(r"\bindia\b", location_text, re.I):
        score += 5
        notes.append("location:india+5")

    if FRESHER_RE.search(text):
        score += 12
        notes.append("fresher+12")
    if SENIOR_RE.search(folded_title):
        score -= 10
        notes.append("senior-10")          # penalised, never dropped

    if record.page_type == "individual":
        score += 15
        notes.append("url:individual+15")
    elif record.page_type == "listing":
        score -= 5
        notes.append("url:listing-5")

    if record.freshness == FRESH_24:
        score += 10
        notes.append("fresh:24h+10")
    elif record.freshness == FRESH_48:
        score += 6
        notes.append("fresh:48h+6")
    elif record.freshness == FRESH_OLD:
        score += 2
        notes.append("fresh:older+2")
    else:
        notes.append("fresh:unknown+0")    # unknown is not punished

    if record.fetch_status == "fetched" and record.description:
        score += 5
        notes.append("enriched+5")

    return max(0, min(100, score)), " ".join(notes)


# ==========================================================================
# DEDUPLICATION
# ==========================================================================

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(text).lower()).strip()


def dedupe(records: Sequence[JobRecord]) -> List[JobRecord]:
    """
    Primary   : normalized URL (or board job id)
    Secondary : title + company + location
    Tertiary  : title + company, only within the same source domain
    Records with an unknown company never merge on the weaker keys.
    """
    kept: List[JobRecord] = []
    by_key: Dict[str, JobRecord] = {}

    def better(new: JobRecord, old: JobRecord) -> bool:
        if (new.page_type == "individual") != (old.page_type == "individual"):
            return new.page_type == "individual"
        if len(new.description) != len(old.description):
            return len(new.description) > len(old.description)
        return new.discovery_score > old.discovery_score

    for record in records:
        keys: List[str] = []
        if record.job_id:
            keys.append(f"id::{domain_of(record.job_url)}::{record.job_id}")
        if record.normalized_url:
            keys.append(f"url::{record.normalized_url}")

        title, company = _slug(record.job_title), _slug(record.company)
        if company and company != "unknown":
            keys.append(f"tcl::{title}|{company}|{_slug(record.location)}")
            keys.append(f"tc::{domain_of(record.job_url)}|{title}|{company}")

        existing = next((by_key[key] for key in keys if key in by_key), None)
        if existing is not None:
            if better(record, existing):
                for key in keys:
                    by_key[key] = record
                kept[kept.index(existing)] = record
                # carry over the earlier query attribution
                record.search_query = record.search_query or existing.search_query
            continue

        for key in keys:
            by_key[key] = record
        kept.append(record)

    return kept


# ==========================================================================
# CSV OUTPUT
# ==========================================================================

FULL_COLUMNS = [
    "job_title", "company", "location", "country", "experience", "freshness",
    "date_posted", "source", "job_url", "normalized_url", "job_id",
    "description", "snippet", "skills", "search_query", "search_keyword",
    "page_type", "origin", "fetch_status", "discovery_score",
    "score_breakdown", "found_at",
]

# exact schema consumed by job_analyzer.py
RESULT_COLUMNS = [
    "job_title", "company", "location", "country", "experience", "freshness",
    "source", "job_url", "description", "skills", "search_query",
    "discovery_score", "found_at",
]


def write_csv(path: str, records: Sequence[JobRecord], columns: List[str]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = record.as_dict()
            writer.writerow({column: row.get(column, "") for column in columns})


# ==========================================================================
# REPORTING
# ==========================================================================

def print_report(stats: RunStats, ranked: Sequence[JobRecord], outdir: str) -> None:
    bar = "=" * 56
    say("")
    say(bar)
    say("AI JOB SEARCH ENGINE")
    say(bar)
    say(f"Target Role:          {TARGET_ROLE}")
    say(f"Target City:          {TARGET_CITY}")
    say(f"Country:              {TARGET_COUNTRY}")
    say("")
    say(f"Queries planned:      {stats.queries_planned}")
    say(f"Queries executed:     {stats.queries_executed}")
    say(f"Queries failed:       {stats.queries_failed}")
    say(f"API errors:           {stats.api_errors}")
    say(f"Raw results:          {stats.raw_results}")
    say(f"Unique jobs:          {stats.unique_jobs}")
    say(f"Individual jobs:      {stats.individual_jobs}")
    say(f"Listing pages:        {stats.listing_pages}")
    say(f"Mined from listings:  {stats.mined_from_listings}")
    say(f"Fresh jobs:           {stats.fresh_jobs}")
    say(f"Unknown freshness:    {stats.unknown_freshness}")
    say("")

    say(bar)
    say("TOP 20 DISCOVERY RESULTS")
    say(bar)
    if not ranked:
        say("  No individual job candidates discovered in this run.")
    for rank, record in enumerate(ranked[:20], start=1):
        say(f"\n{rank:>2}. {truncate(record.job_title, 90)}")
        say(f"    Company   : {record.company}")
        say(f"    Location  : {record.location or 'not stated'}")
        say(f"    Source    : {record.source}")
        say(f"    Freshness : {record.freshness}")
        say(f"    Score     : {record.discovery_score}")
        say(f"    URL       : {record.job_url}")

    say("")
    say(bar)
    say("SEARCH COMPLETE")
    say(bar)
    say(f"Raw results:              {stats.raw_results}")
    say(f"Unique results:           {stats.unique_jobs}")
    say(f"Individual job candidates:{stats.individual_jobs:>4}")
    say(f"24h jobs:                 {stats.fresh_jobs}")
    say(f"Unknown freshness:        {stats.unknown_freshness}")
    say(f"Queries executed:         {stats.queries_executed}")
    say(f"Queries failed:           {stats.queries_failed}")
    say("")
    say("Files created:")
    for filename in OUTPUT_FILES:
        say(f"  - {os.path.join(outdir, filename) if outdir not in ('', '.') else filename}")
    say("")


# ==========================================================================
# PIPELINE
# ==========================================================================

def run_pipeline(client: SerperClient, queries: List[SearchQuery], stats: RunStats,
                 fetcher: PageFetcher, max_fetches: int, outdir: str,
                 reference: Optional[datetime] = None) -> List[JobRecord]:
    reference = reference or now_utc()
    raw: List[JobRecord] = []

    # ---- 1. search ----------------------------------------------------
    for index, query in enumerate(queries, start=1):
        logger.info("[%d/%d] %s%s", index, len(queries), query.query,
                    f" (page {query.page})" if query.page > 1 else "")
        for item in client.search(query):
            record = parse_serp_result(item, query, reference)
            if record is not None:
                raw.append(record)

    stats.raw_results = len(raw)
    for record in raw:
        record.discovery_score, record.score_breakdown = score_discovery(record)

    # ---- 2. deduplicate ------------------------------------------------
    unique = dedupe(raw)
    stats.unique_jobs = len(unique)

    individual = [record for record in unique if record.page_type == "individual"]
    listings = [record for record in unique if record.page_type == "listing"]
    others = [record for record in unique if record.page_type == "unknown"]
    stats.listing_pages = len(listings)

    # ---- 3. mine individual jobs out of listing pages -------------------
    mined: List[JobRecord] = []
    if fetcher.enabled and listings:
        budget = max(0, max_fetches - len(individual))
        for listing in sorted(listings, key=lambda item: -item.discovery_score)[:budget]:
            for url in mine_listing_page(listing, fetcher):
                child = JobRecord(
                    job_title=listing.job_title,
                    company=UNKNOWN,
                    location=listing.location,
                    source=source_of(url),
                    job_url=url,
                    normalized_url=normalize_url(url),
                    job_id=extract_job_id(url),
                    search_query=listing.search_query,
                    search_keyword=listing.search_keyword,
                    page_type="individual",
                    origin="listing_extraction",
                )
                mined.append(child)
        stats.mined_from_listings = len(mined)

    candidates = dedupe(individual + mined + others)
    candidates = [record for record in candidates if record.page_type == "individual"
                  or (record.page_type == "unknown" and record.discovery_score >= 35)]

    # ---- 4. enrich individual pages ------------------------------------
    if fetcher.enabled:
        for record in sorted(candidates, key=lambda item: -item.discovery_score)[:max_fetches]:
            if record.fetch_status == "not_fetched":
                enrich_record(record, fetcher, reference)
                record.skills = ", ".join(
                    detect_skills(f"{record.job_title} {record.description}")) or record.skills

    # ---- 5. final scoring, defaults, ranking ---------------------------
    for record in candidates:
        record.discovery_score, record.score_breakdown = score_discovery(record)
        record.experience = record.experience or NOT_SPECIFIED
        record.company = record.company or UNKNOWN
        record.freshness = record.freshness or FRESH_UNKNOWN
        record.country = TARGET_COUNTRY

    candidates.sort(key=lambda item: (item.discovery_score,
                                      item.page_type == "individual",
                                      item.freshness != FRESH_UNKNOWN),
                    reverse=True)

    stats.individual_jobs = len(candidates)
    stats.fresh_jobs = sum(1 for record in candidates if record.freshness == FRESH_24)
    stats.unknown_freshness = sum(1 for record in candidates
                                  if record.freshness == FRESH_UNKNOWN)

    # ---- 6. write the seven CSVs ----------------------------------------
    fresh = [record for record in candidates if record.freshness == FRESH_24]
    write_csv(os.path.join(outdir, "all_raw_jobs.csv"), raw, FULL_COLUMNS)
    write_csv(os.path.join(outdir, "all_unique_jobs.csv"), unique, FULL_COLUMNS)
    write_csv(os.path.join(outdir, "individual_jobs.csv"), candidates, FULL_COLUMNS)
    write_csv(os.path.join(outdir, "fresh_jobs_24h.csv"), fresh, FULL_COLUMNS)
    write_csv(os.path.join(outdir, "job_results.csv"), candidates, RESULT_COLUMNS)
    write_csv(os.path.join(outdir, "top_10_jobs.csv"), candidates[:10], RESULT_COLUMNS)
    write_csv(os.path.join(outdir, "top_20_jobs.csv"), candidates[:20], RESULT_COLUMNS)

    return candidates


# ==========================================================================
# SELF TEST  (scenario from requirement 40 - no API calls, no network)
# ==========================================================================

def _fixture_results() -> List[Dict[str, Any]]:
    """20 LinkedIn listings, 15 Naukri listings, 10 Indeed, 10 Foundit,
    10 Shine, 10 other - with deliberate duplicates."""
    items: List[Dict[str, Any]] = []
    for index in range(20):
        items.append({"title": f"Data Analyst Jobs in Pune - {index} openings",
                      "link": f"https://www.linkedin.com/jobs/search?keywords=data%20analyst&page={index}",
                      "snippet": "Browse data analyst jobs in Pune on LinkedIn"})
    for index in range(15):
        items.append({"title": "Data Analyst Jobs In Pune - 2450 Vacancies",
                      "link": f"https://www.naukri.com/data-analyst-jobs-in-pune-{index}",
                      "snippet": "Apply to data analyst jobs in Pune"})
    for index in range(10):
        items.append({"title": f"Junior Data Analyst - Acme Analytics {index}",
                      "link": f"https://in.indeed.com/viewjob?jk=abc{index}def{index}&utm_source=x",
                      "snippet": "SQL, Power BI, Excel. Fresher friendly.",
                      "date": "2 hours ago"})
    for index in range(10):
        items.append({"title": f"BI Analyst - Delta Systems {index} - Hinjewadi",
                      "link": f"https://www.foundit.in/job/bi-analyst-delta-{index}00{index}",
                      "snippet": "Power BI, DAX, SQL. 0-2 years.", "date": "1 day ago"})
    for index in range(10):
        items.append({"title": f"Data Analyst Trainee - Quantly {index}",
                      "link": f"https://www.shine.com/jobs/data-analyst-trainee/{index}55667",
                      "snippet": "Trainee role in Baner, Pune. Excel, SQL."})
    for index in range(10):
        items.append({"title": f"Senior Data Analyst - BigCorp {index}",
                      "link": f"https://boards.greenhouse.io/bigcorp/jobs/40000{index}",
                      "snippet": "5+ years of experience in analytics, Pune."})
    # duplicates: same jobs, different tracking params / http scheme
    items.append({"title": "Junior Data Analyst - Acme Analytics 0",
                  "link": "http://www.indeed.com/viewjob?jk=abc0def0&utm_campaign=dup",
                  "snippet": "duplicate of an existing Indeed job"})
    items.append({"title": "BI Analyst - Delta Systems 1 - Hinjewadi",
                  "link": "https://foundit.in/job/bi-analyst-delta-1001/?ref=dup",
                  "snippet": "duplicate of an existing Foundit job"})
    # non-India postings that must never reach job_results.csv
    items.append({"title": "[Job-30951] S\u00eanior Data Analyst, Brazil",
                  "link": "https://realanalystjobs.com/job/30951-senior-data-analyst",
                  "snippet": "CI&T is hiring. We work across India, Brazil and the US."})
    items.append({"title": "Data Analyst - Sao Paulo",
                  "link": "https://boards.greenhouse.io/globex/jobs/999111",
                  "snippet": "Analytics role based in Brazil."})
    return items


def run_selftest(outdir: str) -> int:
    say("=" * 56)
    say("SELF TEST - offline pipeline (no Serper calls, no fetching)")
    say("=" * 56)

    stats = RunStats()
    queries = plan_queries(DEFAULT_MAX_QUERIES)
    stats.queries_planned = len(queries)
    client = MockSerperClient(stats, _fixture_results())
    fetcher = PageFetcher(enabled=False, stats=stats)

    # 10 mock queries walk the whole fixture set (with overlap, so the
    # deduplication path is exercised as well)
    candidates = run_pipeline(client, queries[:10], stats, fetcher,
                              max_fetches=0, outdir=outdir)

    checks = [
        ("queries planned is 30-40", 30 <= len(queries) <= DEFAULT_MAX_QUERIES),
        ("no query uses risky operators",
         not any(re.search(r"\bOR\b|site:|intitle:|-\w+", query.query) for query in queries)),
        ("raw results collected", stats.raw_results > 0),
        ("duplicates were removed", stats.unique_jobs < stats.raw_results),
        ("listing pages detected", stats.listing_pages > 0),
        ("individual jobs survive listing-heavy results", stats.individual_jobs > 0),
        ("unknown-freshness jobs kept", stats.unknown_freshness > 0),
        ("senior jobs kept, not dropped",
         any("senior" in fold(record.job_title).lower() for record in candidates)),
        ("non-India postings dropped at discovery",
         not any(FOREIGN_PLACE_RE.search(fold(record.job_title))
                 for record in candidates)),
        ("job_results.csv is non-empty",
         os.path.exists(os.path.join(outdir, "job_results.csv"))
         and len(candidates) > 0),
        ("top 10 / top 20 ranked by score",
         all(candidates[index].discovery_score >= candidates[index + 1].discovery_score
             for index in range(min(19, len(candidates) - 1)))),
    ]

    failures = 0
    for label, passed in checks:
        failures += 0 if passed else 1
        say(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    say("")
    say(f"  raw={stats.raw_results} unique={stats.unique_jobs} "
        f"individual={stats.individual_jobs} listings={stats.listing_pages} "
        f"unknown_freshness={stats.unknown_freshness}")
    say("")
    say(f"SELF TEST RESULT: {len(checks) - failures}/{len(checks)} passed")
    return failures


# ==========================================================================
# MAIN
# ==========================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI job discovery engine (Serper) - high recall by design")
    parser.add_argument("--outdir", default=".", help="output directory")
    parser.add_argument("--max-queries", type=int, default=DEFAULT_MAX_QUERIES,
                        help="hard cap on Serper API calls for this run")
    parser.add_argument("--max-fetches", type=int, default=DEFAULT_MAX_FETCHES,
                        help="hard cap on job pages fetched for enrichment")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip all page fetching and listing mining")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the query plan and exit without calling the API")
    parser.add_argument("--selftest", action="store_true",
                        help="run the offline pipeline test and exit")
    parser.add_argument("--allow-foreign", action="store_true",
                        help="keep jobs advertised for other countries (off by default)")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)

    global STRICT_INDIA_ONLY
    if args.allow_foreign:
        STRICT_INDIA_ONLY = False

    if load_dotenv is not None:
        try:
            load_dotenv()
        except Exception:
            pass

    if args.outdir and not os.path.isdir(args.outdir):
        os.makedirs(args.outdir, exist_ok=True)

    if args.selftest:
        return 1 if run_selftest(args.outdir) else 0

    queries = plan_queries(args.max_queries)

    if args.dry_run:
        say("=" * 56)
        say(f"QUERY PLAN - {len(queries)} Serper calls")
        say("=" * 56)
        for index, query in enumerate(queries, start=1):
            page = f"  (page {query.page})" if query.page > 1 else ""
            say(f"{index:>2}. [{query.category:<8}] {query.query}{page}")
        return 0

    api_key = clean(os.getenv("SERPER_API_KEY"))
    if not api_key:
        say("ERROR: SERPER_API_KEY not found.")
        say("Create a .env file next to job_search.py containing:")
        say("    SERPER_API_KEY=your_key_here")
        return 1
    if requests is None:
        say("ERROR: the 'requests' package is required. "
            "Run: pip install requests beautifulsoup4 python-dotenv pandas python-dateutil")
        return 1

    stats = RunStats(queries_planned=len(queries))
    client = SerperClient(api_key, stats)
    fetcher = PageFetcher(enabled=not args.no_fetch, stats=stats)

    say("=" * 56)
    say("AI JOB SEARCH ENGINE - starting")
    say("=" * 56)
    say(f"Queries planned: {len(queries)}   Fetching: {'ON' if fetcher.enabled else 'OFF'}")
    say("")

    try:
        candidates = run_pipeline(client, queries, stats, fetcher,
                                  args.max_fetches, args.outdir)
    except KeyboardInterrupt:
        say("\nInterrupted by user - no files written.")
        return 130
    except Exception as error:
        logger.exception("Unexpected failure: %s", error)
        return 1

    print_report(stats, candidates, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
