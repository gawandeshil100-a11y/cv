Shil Gawande — Data Engineering & Analytics Portfolio

Data Analyst / Data Engineer · Pune, India · ENTC graduate, 2026 · Immediate joiner

I build pipelines that are honest about their own data. Across these three projects the recurring theme is the same: validate before you trust, and make failure visible instead of silent. Referential integrity is asserted rather than assumed, missing values are their own category rather than a convenient default, and a fact-validation gate can halt a pipeline outright.

Core stack: Python · SQL · Snowflake · Power BI · pandas · scikit-learn · Streamlit

Projects at a glance
#	Project	Domain	Stack	Scale
1	Urban Mobility Analytics	Public transport	Python · Snowflake · Power BI	4-page report, 3-view semantic layer
2	AI Job Application & Resume Intelligence	Applied AI / automation	Python · Streamlit · Serper API	~13,900 lines, 10 modules
3	Supply Chain Analytics	Operations / logistics	Python · scikit-learn · Power BI	164,250-row simulation, 11 tables
1. Urban Mobility — Data Engineering & Analytics Case Study

Repo: urban-mobility-analytics · Stack: Python (pandas) · Snowflake · SQL · Power BI · DAX

An end-to-end pipeline on NYC TLC monthly mobility indicators, from raw CSV to executive dashboard.

raw CSV → profile → clean → validate → Snowflake → SQL views → Power BI

What it does. Four Python stages bracket the transformation with independent quality reports: quality_check.py profiles the raw file (nulls, duplicates, dtypes, distributions), clean_monthly.py standardises column names, parses dates with an explicit format, strips thousands separators and maps - placeholders to nulls, and validate_cleaned.py re-runs the same checks on the output. Comparing the two reports is the evidence that the cleaning worked — numeric columns should have moved from object to int64/float64.

Data then lands in Snowflake as an untouched base table, with all business logic in three versioned views:

VW_MONTHLY_MOBILITY — clean pass-through, decoupling the report from the physical table
VW_MOBILITY_KPIS — row-level trips-per-vehicle and trips-per-driver with divide-by-zero guards
VW_POWERBI_MONTHLY — pre-aggregated to monthly grain so Power BI imports a compact dataset

Engineering decisions worth calling out. Ratios in the aggregate view are computed as SUM / NULLIF(SUM, 0) rather than averaging row-level ratios — avoiding the average-of-averages error that quietly corrupts most first-attempt dashboards. Business logic lives in views, not transformed tables, so changing a KPI definition is a redeploy rather than a reload.

Power BI report: 4 pages, 24 visuals, 5 DAX measures — Executive Dashboard, Monthly Mobility & Fare Analysis, Driver vs Vehicle Utilisation, and Payment & Trip Behaviour Analysis, with a licence-class slicer and date hierarchy.

2. AI Job Application & Resume Intelligence Platform

Repo: ai-job-intelligence · Stack: Python · Streamlit · Serper API · python-docx · ReportLab Scale: ~13,900 lines across 10 modules

A six-stage pipeline that discovers job postings, filters them with evidence-based rules, generates a role-tailored resume from an immutable master profile, and blocks the output if any protected fact was altered.

The design constraint that shapes everything: the system may re-word, but it may never invent.

Why that constraint matters

Automated resume tools fail two ways. They hallucinate — adding a skill you don't have or inflating a metric, leaving you unable to defend your own CV in the interview. And they over-accept — treating a missing experience field as "fresher-friendly" and a missing date as "posted recently," so the shortlist fills with senior roles and dead listings. This pipeline is built against both.

Architecture
DISCOVERY (high recall)  →  ANALYSIS (high precision)  →  RESUME PIPELINE
job_search.py               job_analyzer.py               pipeline.py
1,707 lines                 2,163 lines                   1,565 lines
                                                          ├─ customize
master CV → resume_parser.py → master_resume.json  ───────┤─ VALIDATE ◄ gate
                               (SHA-256 verified)         └─ render DOCX/PDF

Discovery and precision are deliberately separate stages. Search casts wide — it does not reject senior roles, undated postings or unknown companies. Filtering happens downstream, so retuning the filter never costs coverage and every rejection stays auditable against the raw set. Discovery plans ~40 Serper queries sized to the free tier, normalises URLs (stripping tracking parameters while keeping the ones that identify a posting), mines listing pages across eight job boards, and reads JSON-LD JobPosting data where publishers provide it.

The analyzer's rules: numeric experience evidence beats vague seniority wording; "Senior" in a title with no numeric evidence resolves to Senior/Experienced; missing experience is never read as fresher-friendly and a missing date is never read as fresh — each becomes its own category. A high skill score can never promote a senior role into eligibility. Every decision stores the evidence string it was based on.

The validation gate is the centrepiece. resume_validator.py (2,532 lines) diffs generated output against the master profile: locked facts unmodified, project identity preserved, factual numbers intact token by token, education and certifications byte-identical, and no technology claimed that doesn't appear in the master. pipeline.py computes a SHA-256 checksum of master_resume.json before the run and asserts it unchanged after — immutability enforced structurally, not merely intended. If any check fails, the pipeline halts and no document is rendered. There is no override flag.

Also includes: a Streamlit ATS analyser scoring resume-vs-JD skill overlap across eight skill families, and a template-based interview question bank per recommended job.

3. Supply Chain Analytics — Digital Twin & Intelligence Hub

Repo: supply-chain-analytics · Stack: Python · pandas · NumPy · scikit-learn · Power BI

Two complementary projects: a discrete-event simulation that generates a relational dataset, and an analytics layer that turns a flat SKU table into a four-page BI report.

3a. Digital Twin Simulation

Takes a 91,250-row transactional extract and simulates a full calendar year day by day, producing 11 SQL-ready tables including a 164,250-row daily inventory ledger (SKU × warehouse × day), 7,114 orders, 7,114 shipments and a data dictionary.

Demand is modelled multiplicatively — annual seasonality as a sine wave at ±25% amplitude, weekly multipliers from 0.85 to 1.2 peaking Saturday, and promotional windows on ~12% of SKUs producing 1.8× spikes for 7–21 days. Replenishment uses an order-up-to policy with a 14-day cover target, reorder point of mean_daily_demand × lead_time + safety_stock, quantities clipped to supplier minimums, and lead times drawn from a clipped normal — with random disruption events adding 3–10 days at each supplier's disruption probability.

What makes it more than a data generator: primary-key uniqueness is asserted on all ten tables and foreign-key containment is checked with hard assertions (shipments.order_id ⊆ orders.order_id, and so on). The notebook then re-reads its own output and audits it, reporting a full validation scorecard. That second pass caught a real bug in the first — a date-parsing heuristic matching any column containing time had wrongly coerced the numeric Supplier_Lead_Time_Days to datetime. The fix anchors matching on date-like names and requires >50% successful parses before accepting a conversion.

Output is SQL Server-friendly by construction: booleans as 0/1, dates as YYYY-MM-DD, floats rounded — the CSVs load without type negotiation. Seeded at 42 throughout, so the same input regenerates the identical dataset.

3b. Intelligence Hub

Engineers five composite 0–100 scores from a 100-SKU dataset — Inventory Health (weighted adequacy and lead-time safety), Supplier Performance, Logistics Efficiency, Cost Efficiency and Revenue per Unit — each computed only when its numeric bases exist, min-max normalised, and guarded against zero denominators. Adds four quantile-derived categorical bands.

Machine learning: K-Means product segmentation on standardised price and efficiency features, plus K-Means supplier risk clustering on performance, lead time, defect rate and shipping time. A cost-prediction regression is included and documented as a negative result — R² = −0.610, worse than predicting the mean, because 100 rows split across 13 predictors cannot generalise. It's reported honestly in the repo rather than buried, with the structural fix (feature selection, k-fold CV, regularisation) on the roadmap.

Power BI report: 4 pages, 24 visuals — Executive Overview, Product & Inventory Analytics, Supplier & Logistics Analytics, and Machine Learning Insights, the last showing actual vs. predicted cost so the model's gap is visible rather than hidden.

Skills demonstrated
Skill	Where
SQL (DDL, views, window functions, null-safe aggregation)	Urban Mobility
Cloud data warehousing (Snowflake)	Urban Mobility
Python data pipelines (pandas, profiling, cleaning, validation)	All three
Power BI + DAX	Urban Mobility, Supply Chain
Dimensional modelling & referential integrity	Supply Chain digital twin
Discrete-event simulation	Supply Chain digital twin
scikit-learn (K-Means, PCA, regression, pipelines, imputation)	Supply Chain hub
Feature engineering (composite scoring, normalisation)	Supply Chain hub
Software architecture (10-module system, orchestration, adapters)	Job Intelligence
API integration with retries and backoff	Job Intelligence
Web scraping & structured data extraction (JSON-LD)	Job Intelligence
Document generation (python-docx, ReportLab)	Job Intelligence
Streamlit applications	Job Intelligence
Data quality engineering (assertions, audit passes, gates)	All three
Engineering principles across all three
Validate before and after. Independent quality reports bracket every transformation, so changes are evidenced rather than assumed.
Absence is never evidence of a good outcome. Unknown experience, unknown dates and missing columns get their own handling instead of defaulting to whatever is convenient.
Assert, don't hope. Primary keys, foreign keys and file checksums are enforced in code, not documented as intentions.
Gates over warnings. A failed fact check halts rendering. A duplicate key raises. Silence is not success.
Degrade gracefully. Optional dependencies are wrapped so modules run in reduced mode instead of crashing.
Report negative results. A model that doesn't work is documented as not working, with the structural reason.
Certifications & publications
Deloitte Data Analytics Job Simulation — Forage
Tata Data Analytics Job Simulation — Forage
ExcelR Data Analytics Training (2026)
Two peer-reviewed IRJMETS publications on an ESP8266 agricultural robot (10.56726/IRJMETS90247, 10.56726/IRJMETS90900)
