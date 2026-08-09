import pandas as pd
from pathlib import Path


# Project paths
PROJECT_DIR = Path(__file__).resolve().parent.parent

RAW_FILE = (
    PROJECT_DIR
    / "data"
    / "raw"
    / "data_reports_monthly.csv"
)

PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
OUTPUT_FILE = PROCESSED_DIR / "monthly_cleaned.csv"


def clean_data():

    print("Loading TLC monthly data...")

    df = pd.read_csv(RAW_FILE)

    print(f"Original rows: {len(df)}")
    print(f"Original columns: {len(df.columns)}")

    # --------------------------------------------------
    # 1. Clean column names
    # --------------------------------------------------

    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace("/", "_")
        .str.replace("%", "percent")
    )

    # --------------------------------------------------
    # 2. Convert Month/Year to date
    # --------------------------------------------------

    df["month_year"] = pd.to_datetime(
        df["month_year"],
        format="%Y-%m"
    )

    # --------------------------------------------------
    # 3. Convert numeric columns
    # --------------------------------------------------

    numeric_columns = [
        "trips_per_day",
        "farebox_per_day",
        "unique_drivers",
        "unique_vehicles",
        "vehicles_per_day",
        "trips_per_day_shared",
    ]

    for column in numeric_columns:

        df[column] = (
            df[column]
            .astype(str)
            .str.replace(",", "", regex=False)
            .replace("-", pd.NA)
        )

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    # --------------------------------------------------
    # 4. Convert percentage column
    # --------------------------------------------------

    df["percent_of_trips_paid_with_credit_card"] = (
        df["percent_of_trips_paid_with_credit_card"]
        .astype(str)
        .str.replace("%", "", regex=False)
        .replace("-", pd.NA)
    )

    df["percent_of_trips_paid_with_credit_card"] = pd.to_numeric(
        df["percent_of_trips_paid_with_credit_card"],
        errors="coerce"
    )

    # --------------------------------------------------
    # 5. Check duplicates
    # --------------------------------------------------

    duplicates = df.duplicated().sum()

    print(f"Duplicate rows found: {duplicates}")

    if duplicates > 0:
        df = df.drop_duplicates()

    # --------------------------------------------------
    # 6. Create processed directory
    # --------------------------------------------------

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------
    # 7. Save cleaned data
    # --------------------------------------------------

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print("\nCleaning completed successfully!")

    print(f"Cleaned rows: {len(df)}")
    print(f"Cleaned columns: {len(df.columns)}")

    print("\nCleaned data types:")
    print(df.dtypes)

    print("\nSaved file:")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    clean_data()