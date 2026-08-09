import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(
    page_title="AI Job Application Intelligence",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 AI Job Application Intelligence")
st.write("AI-powered job search, analysis and interview preparation")

st.divider()

# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------

st.sidebar.title("Navigation")

page = st.sidebar.radio(
    "Choose Module",
    [
        "🏠 Dashboard",
        "🔎 Job Search",
        "📊 Job Analysis",
        "🎤 Interview Preparation",
        "📄 Resume Intelligence"
    ]
)

# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

if page == "🏠 Dashboard":

    st.header("Dashboard")

    col1, col2, col3, col4 = st.columns(4)

    # Job results
    if Path("job_results.csv").exists():
        jobs = pd.read_csv("job_results.csv")
        total_jobs = len(jobs)
    else:
        total_jobs = 0

    # Analyzed jobs
    if Path("analyzed_jobs.csv").exists():
        analyzed = pd.read_csv("analyzed_jobs.csv")
        analyzed_count = len(analyzed)
    else:
        analyzed_count = 0

    # Recommended jobs
    if Path("recommended_jobs.csv").exists():
        recommended = pd.read_csv("recommended_jobs.csv")
        recommended_count = len(recommended)
    else:
        recommended_count = 0

    # Interview questions
    if Path("interview_questions.csv").exists():
        questions = pd.read_csv("interview_questions.csv")
        question_count = len(questions)
    else:
        question_count = 0

    col1.metric("Jobs Found", total_jobs)
    col2.metric("Jobs Analyzed", analyzed_count)
    col3.metric("Recommended Jobs", recommended_count)
    col4.metric("Interview Questions", question_count)

    st.divider()

    st.subheader("Your AI Job Pipeline")

    st.markdown("""
    **1. 🔎 Job Search**

    Find relevant jobs using your job-search engine.

    **2. 📊 Job Analyzer**

    Analyze role, location, experience, skills and match score.

    **3. 📄 Resume Intelligence**

    Analyze and customize your resume for the selected job.

    **4. 🎤 Interview Intelligence**

    Generate interview questions based on the job and your profile.
    """)


# --------------------------------------------------
# JOB SEARCH
# --------------------------------------------------

elif page == "🔎 Job Search":

    st.header("🔎 Job Search")

    role = st.text_input(
        "Target Role",
        value="Data Analyst"
    )

    city = st.text_input(
        "Target City",
        value="Pune"
    )

    experience = st.selectbox(
        "Experience",
        [
            "Fresher",
            "0-1 years",
            "1-2 years",
            "2-3 years",
            "Any"
        ]
    )

    if st.button("🔎 Search Jobs", type="primary"):

        st.info(
            "Your existing job_search.py module will be connected here."
        )

        st.write("Role:", role)
        st.write("City:", city)
        st.write("Experience:", experience)


# --------------------------------------------------
# JOB ANALYSIS
# --------------------------------------------------

elif page == "📊 Job Analysis":

    st.header("📊 Job Analysis")

    if Path("analyzed_jobs.csv").exists():

        df = pd.read_csv("analyzed_jobs.csv")

        st.metric(
            "Jobs analyzed",
            len(df)
        )

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.warning(
            "analyzed_jobs.csv not found. Run job_analyzer.py first."
        )


# --------------------------------------------------
# INTERVIEW PREPARATION
# --------------------------------------------------

elif page == "🎤 Interview Preparation":

    st.header("🎤 Interview Preparation")

    if Path("interview_questions.csv").exists():

        df = pd.read_csv("interview_questions.csv")

        st.metric(
            "Questions available",
            len(df)
        )

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.warning(
            "interview_questions.csv not found."
        )


# --------------------------------------------------
# RESUME INTELLIGENCE
# --------------------------------------------------

elif page == "📄 Resume Intelligence":

    st.header("📄 Resume Intelligence")

    uploaded_file = st.file_uploader(
        "Upload your resume",
        type=["pdf", "docx"]
    )

    if uploaded_file:

        st.success(
            f"Resume uploaded: {uploaded_file.name}"
        )

        st.info(
            "Your existing resume modules will be connected here."
        )