import pandas as pd
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent

CLEAN_FILE = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "monthly_cleaned.csv"
)


def validate_data():

    print("Loading cleaned data...")

    df = pd.read_csv(CLEAN_FILE)

    print("\n========== CLEANED DATA VALIDATION ==========")

    print("\n1. Shape")
    print("Rows:", df.shape[0])
    print("Columns:", df.shape[1])

    print("\n2. Data Types")
    print(df.dtypes)

    print("\n3. Missing Values")
    print(df.isnull().sum())

    print("\n4. Duplicate Rows")
    print(df.duplicated().sum())

    print("\n5. Sample Data")
    print(df.head())

    print("\n6. Numeric Summary")
    print(df.describe())

    print("\n========== VALIDATION COMPLETE ==========")


if __name__ == "__main__":
    validate_data()