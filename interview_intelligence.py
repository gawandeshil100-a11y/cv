import csv
import json
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

INPUT_FILE = "recommended_jobs.csv"
OUTPUT_CSV = "interview_questions.csv"
OUTPUT_JSON = "interview_questions.json"


# ============================================================
# LOAD JOBS
# ============================================================

def load_jobs():
    path = Path(INPUT_FILE)

    if not path.exists():
        print(f"ERROR: {INPUT_FILE} not found.")
        print("Run job_analyzer.py first.")
        return []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        jobs = list(reader)

    return jobs


# ============================================================
# GENERATE QUESTIONS
# ============================================================

def generate_questions(job):
    job_title = job.get("job_title", "")
    company = job.get("company", "")
    skills = job.get("matched_skills", "")
    experience = job.get("experience", "")

    questions = []

    # SQL
    questions.extend([
        {
            "category": "SQL",
            "difficulty": "Medium",
            "priority": "HIGH",
            "question": "Explain the difference between INNER JOIN, LEFT JOIN and FULL OUTER JOIN.",
            "skills_tested": "SQL"
        },
        {
            "category": "SQL",
            "difficulty": "Medium",
            "priority": "HIGH",
            "question": "How would you find the second highest salary from a table?",
            "skills_tested": "SQL"
        },
        {
            "category": "SQL",
            "difficulty": "Hard",
            "priority": "HIGH",
            "question": "How would you use a window function to rank products by revenue?",
            "skills_tested": "SQL, Window Functions"
        },
    ])

    # Python
    questions.extend([
        {
            "category": "Python",
            "difficulty": "Medium",
            "priority": "HIGH",
            "question": "How would you use Pandas to clean and analyze a dataset?",
            "skills_tested": "Python, Pandas"
        },
        {
            "category": "Python",
            "difficulty": "Medium",
            "priority": "MEDIUM",
            "question": "What is the difference between a list, tuple and dictionary in Python?",
            "skills_tested": "Python"
        },
    ])

    # Power BI
    questions.extend([
        {
            "category": "Power BI",
            "difficulty": "Medium",
            "priority": "HIGH",
            "question": "How would you design a Power BI dashboard for business performance analysis?",
            "skills_tested": "Power BI, Data Visualization"
        },
        {
            "category": "Power BI",
            "difficulty": "Hard",
            "priority": "HIGH",
            "question": "What is DAX and how have you used it in Power BI?",
            "skills_tested": "Power BI, DAX"
        },
    ])

    # Excel
    questions.extend([
        {
            "category": "Excel",
            "difficulty": "Easy",
            "priority": "MEDIUM",
            "question": "Explain how you would use Pivot Tables for data analysis.",
            "skills_tested": "Excel"
        },
        {
            "category": "Excel",
            "difficulty": "Medium",
            "priority": "MEDIUM",
            "question": "What is the difference between VLOOKUP, XLOOKUP and INDEX-MATCH?",
            "skills_tested": "Excel"
        },
    ])

    # Statistics
    questions.extend([
        {
            "category": "Statistics",
            "difficulty": "Medium",
            "priority": "MEDIUM",
            "question": "What is the difference between mean, median and mode?",
            "skills_tested": "Statistics"
        },
        {
            "category": "Statistics",
            "difficulty": "Medium",
            "priority": "MEDIUM",
            "question": "What is standard deviation and why is it useful?",
            "skills_tested": "Statistics"
        },
    ])

    # Business case
    questions.extend([
        {
            "category": "Business Case",
            "difficulty": "Hard",
            "priority": "VERY HIGH",
            "question": "A company's sales dropped by 15%. How would you investigate the reason?",
            "skills_tested": "Data Analysis, Business Analytics"
        },
        {
            "category": "Business Case",
            "difficulty": "Hard",
            "priority": "VERY HIGH",
            "question": "How would you identify the most important KPIs for a business dashboard?",
            "skills_tested": "Analytics, KPI, Dashboard"
        },
    ])

    # Resume / project
    questions.extend([
        {
            "category": "Resume",
            "difficulty": "Medium",
            "priority": "HIGH",
            "question": "Explain your most important data analytics project.",
            "skills_tested": "Resume, Projects"
        },
        {
            "category": "Resume",
            "difficulty": "Hard",
            "priority": "HIGH",
            "question": "Describe a difficult data problem you solved and how you solved it.",
            "skills_tested": "Problem Solving, Data Analytics"
        },
    ])

    # HR
    questions.extend([
        {
            "category": "HR",
            "difficulty": "Easy",
            "priority": "MEDIUM",
            "question": f"Why are you interested in the {job_title} position at {company}?",
            "skills_tested": "Communication, Motivation"
        },
        {
            "category": "HR",
            "difficulty": "Easy",
            "priority": "MEDIUM",
            "question": "Tell me about yourself and your background.",
            "skills_tested": "Communication"
        },
    ])

    # Add job information to every question
    for q in questions:
        q["job_title"] = job_title
        q["company"] = company
        q["experience"] = experience
        q["matched_skills"] = skills

    return questions


# ============================================================
# SAVE CSV
# ============================================================

def save_csv(questions):
    if not questions:
        return

    fields = [
        "job_title",
        "company",
        "category",
        "difficulty",
        "priority",
        "question",
        "skills_tested",
        "experience",
        "matched_skills"
    ]

    with open(
            OUTPUT_CSV,
            "w",
            encoding="utf-8-sig",
            newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(questions)


# ============================================================
# SAVE JSON
# ============================================================

def save_json(questions):
    with open(
            OUTPUT_JSON,
            "w",
            encoding="utf-8"
    ) as f:
        json.dump(
            questions,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("AI INTERVIEW INTELLIGENCE")
    print("=" * 70)

    jobs = load_jobs()

    if not jobs:
        return

    print(f"\nJobs received: {len(jobs)}")

    all_questions = []

    for i, job in enumerate(jobs, 1):
        print(
            f"\n[{i}/{len(jobs)}] "
            f"{job.get('job_title', 'Unknown')}"
        )

        questions = generate_questions(job)

        all_questions.extend(questions)

        print(
            f"Generated {len(questions)} interview questions"
        )

    save_csv(all_questions)
    save_json(all_questions)

    print("\n" + "=" * 70)
    print("INTERVIEW QUESTION GENERATION COMPLETE")
    print("=" * 70)

    print(f"\nTotal jobs      : {len(jobs)}")
    print(f"Total questions : {len(all_questions)}")

    print(f"\nCreated:")
    print(f"  {OUTPUT_CSV}")
    print(f"  {OUTPUT_JSON}")


if __name__ == "__main__":
    main()