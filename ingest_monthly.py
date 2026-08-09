import pandas as pd
from pathlib import Path


# Project paths
PROJECT_DIR = Path(__file__).resolve().parent
RAW_FILE = PROJECT_DIR / "data" / "raw" / "data_reports_monthly.csv"


def load_data():
    print("Loading TLC monthly data...")

    df = pd.read_csv(RAW_FILE)

    print("\nData loaded successfully!")
    print(f"Rows: {df.shape[0]}")
    print(f"Columns: {df.shape[1]}")

    print("\nColumn names:")
    for column in df.columns:
        print("-", column)

    print("\nFirst 5 rows:")
    print(df.head())

    return df


if __name__ == "__main__":
    load_data()