import pandas as pd
from pathlib import Path


# Project paths
PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_FILE = PROJECT_DIR / "data" / "raw" / "data_reports_monthly.csv"


def quality_check():

    print("Loading TLC data...")

    df = pd.read_csv(RAW_FILE)

    print("\n========== DATA QUALITY REPORT ==========")

    # 1. Dataset size
    print("\n1. Dataset Shape")
    print("Rows:", df.shape[0])
    print("Columns:", df.shape[1])

    # 2. Column names
    print("\n2. Columns")
    print(df.columns.tolist())

    # 3. Missing values
    print("\n3. Missing Values")
    print(df.isnull().sum())

    # 4. Duplicate rows
    print("\n4. Duplicate Rows")
    print(df.duplicated().sum())

    # 5. Data types
    print("\n5. Data Types")
    print(df.dtypes)

    # 6. Numerical statistics
    print("\n6. Numerical Statistics")
    print(df.describe())

    # 7. First rows
    print("\n7. Sample Data")
    print(df.head())


if __name__ == "__main__":
    quality_check()