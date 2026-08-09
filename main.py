import streamlit as st
import pandas as pd
import re
from io import BytesIO
from pypdf import PdfReader

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="AI Job Application Intelligence",
    page_icon="🤖",
    layout="wide"
)

# ============================================================
# CUSTOM STYLE
# ============================================================

st.markdown("""
<style>

.stApp {
    background: linear-gradient(135deg, #0f172a, #172554, #312e81);
    color: white;
}

.main-title {
    font-size: 42px;
    font-weight: 800;
    color: #60a5fa;
}

.subtitle {
    font-size: 18px;
    color: #cbd5e1;
}

.card {
    background: rgba(30, 41, 59, 0.85);
    padding: 22px;
    border-radius: 16px;
    border: 1px solid rgba(96,165,250,0.3);
    margin-bottom: 15px;
}

.score {
    font-size: 42px;
    font-weight: 800;
    color: #22c55e;
}

.skill {
    display: inline-block;
    background: #1d4ed8;
    color: white;
    padding: 7px 12px;
    margin: 4px;
    border-radius: 20px;
}

.missing {
    display: inline-block;
    background: #991b1b;
    color: white;
    padding: 7px 12px;
    margin: 4px;
    border-radius: 20px;
}

</style>
""", unsafe_allow_html=True)

# ============================================================
# TITLE
# ============================================================

st.markdown(
    '<div class="main-title">🤖 AI Job Application Intelligence Platform</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">Resume Intelligence • Job Matching • ATS Analysis • Skill Gap Detection</div>',
    unsafe_allow_html=True
)

st.divider()

# ============================================================
# SESSION STATE
# ============================================================

if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""

if "job_text" not in st.session_state:
    st.session_state.job_text = ""

# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("⚙️ Job Analysis")

role = st.sidebar.selectbox(
    "Target Role",
    [
        "Data Analyst",
        "Business Analyst",
        "BI Analyst",
        "Data Engineer",
        "AI/ML Analyst",
        "Python Developer"
    ]
)

# ============================================================
# RESUME UPLOAD
# ============================================================

st.subheader("📄 Resume")

resume_file = st.file_uploader(
    "Upload your resume",
    type=["pdf"],
    key="resume"
)

if resume_file:

    reader = PdfReader(BytesIO(resume_file.read()))

    resume_text = ""

    for page in reader.pages:
        text = page.extract_text()

        if text:
            resume_text += text + "\n"

    st.session_state.resume_text = resume_text

    st.success("Resume successfully extracted.")

# ============================================================
# JOB DESCRIPTION
# ============================================================

st.subheader("💼 Job Description")

job_text = st.text_area(
    "Paste the job description here",
    height=250,
    placeholder="Paste the complete job description..."
)

st.session_state.job_text = job_text

# ============================================================
# SKILL DATABASE
# ============================================================

skills = {

    "Python": [
        "python",
        "pandas",
        "numpy",
        "scikit-learn"
    ],

    "SQL": [
        "sql",
        "mysql",
        "postgresql",
        "sql server",
        "snowflake"
    ],

    "Data Visualization": [
        "power bi",
        "tableau",
        "streamlit",
        "plotly"
    ],

    "Excel": [
        "excel",
        "vlookup",
        "pivot table",
        "power query"
    ],

    "Cloud": [
        "aws",
        "azure",
        "gcp",
        "snowflake"
    ],

    "AI / ML": [
        "machine learning",
        "artificial intelligence",
        "scikit-learn",
        "tensorflow",
        "pytorch",
        "nlp",
        "langchain"
    ],

    "Data Engineering": [
        "etl",
        "elt",
        "airflow",
        "spark",
        "databricks",
        "data warehouse"
    ],

    "Business Analysis": [
        "business analysis",
        "requirements",
        "brd",
        "frd",
        "stakeholder",
        "process improvement"
    ]
}

# ============================================================
# SKILL EXTRACTION
# ============================================================

def extract_skills(text):

    text = text.lower()

    found = []

    for category, keywords in skills.items():

        for keyword in keywords:

            if keyword in text:

                found.append(keyword)

    return sorted(list(set(found)))


# ============================================================
# ANALYSIS BUTTON
# ============================================================

if st.button(
    "🚀 Analyze Resume & Job",
    type="primary",
    use_container_width=True
):

    if not st.session_state.resume_text:

        st.warning("Please upload your resume first.")

    elif not st.session_state.job_text:

        st.warning("Please paste the job description.")

    else:

        resume_skills = extract_skills(
            st.session_state.resume_text
        )

        job_skills = extract_skills(
            st.session_state.job_text
        )

        matched = list(
            set(resume_skills) &
            set(job_skills)
        )

        missing = list(
            set(job_skills) -
            set(resume_skills)
        )

        # ====================================================
        # MATCH SCORE
        # ====================================================

        if len(job_skills) > 0:

            score = (
                len(matched) /
                len(job_skills)
            ) * 100

        else:

            score = 0

        score = round(score, 1)

        # ====================================================
        # DASHBOARD
        # ====================================================

        st.divider()

        st.subheader("📊 Job Match Intelligence")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "🎯 ATS Match",
            f"{score}%"
        )

        c2.metric(
            "✅ Matched Skills",
            len(matched)
        )

        c3.metric(
            "❌ Missing Skills",
            len(missing)
        )

        c4.metric(
            "💼 Target Role",
            role
        )

        # ====================================================
        # SCORE
        # ====================================================

        st.markdown(
            f"""
            <div class="card">
                <h2>ATS Compatibility</h2>
                <div class="score">{score}%</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        # ====================================================
        # MATCHED SKILLS
        # ====================================================

        st.subheader("✅ Matching Skills")

        if matched:

            html = ""

            for skill in matched:

                html += (
                    f'<span class="skill">{skill}</span>'
                )

            st.markdown(
                html,
                unsafe_allow_html=True
            )

        else:

            st.info("No matching skills detected.")

        # ====================================================
        # MISSING SKILLS
        # ====================================================

        st.subheader("⚠️ Missing Skills")

        if missing:

            html = ""

            for skill in missing:

                html += (
                    f'<span class="missing">{skill}</span>'
                )

            st.markdown(
                html,
                unsafe_allow_html=True
            )

        else:

            st.success(
                "Excellent! No major missing skills detected."
            )

        # ====================================================
        # RECOMMENDATION
        # ====================================================

        st.subheader("🧠 AI Recommendation")

        if score >= 80:

            st.success(
                "🔥 Strong match. Your resume is highly aligned "
                "with this job description."
            )

        elif score >= 60:

            st.warning(
                "🟡 Moderate match. Add the missing skills "
                "where they genuinely apply to your experience."
            )

        else:

            st.error(
                "🔴 Low match. Consider improving your resume "
                "or targeting a more suitable role."
            )

        # ====================================================
        # SKILL GAP TABLE
        # ====================================================

        st.subheader("📋 Skill Gap Analysis")

        gap_data = []

        for skill in job_skills:

            gap_data.append(
                {
                    "Skill": skill,
                    "Resume": (
                        "✅ Present"
                        if skill in resume_skills
                        else "❌ Missing"
                    ),
                    "Job Requirement": "Required"
                }
            )

        if gap_data:

            gap_df = pd.DataFrame(gap_data)

            st.dataframe(
                gap_df,
                use_container_width=True,
                hide_index=True
            )

# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "AI Job Application Intelligence Platform | "
    "Python • Streamlit • NLP • Resume Intelligence"
)
