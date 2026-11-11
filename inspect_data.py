"""
01_inspect_data.py
Step 1 of the oil & gas VaR/ES project: inspect raw downloads before any cleaning.

Put your downloaded files in ./data/raw/ (CSV or Excel), then run:
    python 01_inspect_data.py

It makes NO assumptions about format yet. It prints:
  1. the raw first lines of each file (so we see headers / junk rows exactly as delivered)
  2. a pandas view: shape, dtypes, head, tail
  3. basic checks: date range, missing values, non-numeric entries, non-positive prices
"""

from pathlib import Path
import pandas as pd

RAW_DIR = Path("data/raw")
N_LINES = 8


def show_raw_lines(path: Path) -> None:
    """Print the first few lines exactly as stored (CSV/TXT only)."""
    print(f"\n--- Raw first {N_LINES} lines ---")
    with open(path, "r", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= N_LINES:
                break
            print(repr(line.rstrip("\n")))


def load_any(path: Path) -> dict:
    """Return {sheet_name: DataFrame}. CSVs get a single entry."""
    if path.suffix.lower() in (".csv", ".txt"):
        return {"csv": pd.read_csv(path)}
    # Excel: read every sheet, since EIA files keep data on a non-first sheet
    return pd.read_excel(path, sheet_name=None)


def summarise(df: pd.DataFrame, label: str) -> None:
    print(f"\n=== {label} ===")
    print(f"Shape: {df.shape}")
    print("\nDtypes:\n", df.dtypes)
    print("\nHead:\n", df.head(N_LINES))
    print("\nTail:\n", df.tail(5))

    # Missing values per column (FRED sometimes uses '.' or blanks for holidays)
    print("\nNulls per column:\n", df.isna().sum())

    for col in df.columns:
        # How many entries fail to parse as numbers? (catches '.', text, etc.)
        numeric = pd.to_numeric(df[col], errors="coerce")
        n_bad = numeric.isna().sum() - df[col].isna().sum()
        if numeric.notna().sum() > 0.5 * len(df):          # mostly numeric -> treat as price
            print(f"\n[{col}] non-numeric entries: {n_bad}")
            print(f"[{col}] min={numeric.min():.4f}  max={numeric.max():.4f}")
            print(f"[{col}] values <= 0: {(numeric <= 0).sum()}")
        else:
            # Maybe a date column: try parsing
            dates = pd.to_datetime(df[col], errors="coerce")
            if dates.notna().sum() > 0.5 * len(df):
                print(f"\n[{col}] looks like dates: {dates.min().date()} -> "
                      f"{dates.max().date()} ({dates.notna().sum()} rows)")


def main() -> None:
    files = sorted(p for p in RAW_DIR.glob("*") if p.suffix.lower()
                   in (".csv", ".txt", ".xls", ".xlsx"))
    if not files:
        print(f"No files found in {RAW_DIR.resolve()}")
        return

    for path in files:
        print("\n" + "#" * 70 + f"\nFILE: {path.name}\n" + "#" * 70)
        if path.suffix.lower() in (".csv", ".txt"):
            show_raw_lines(path)
        for sheet, df in load_any(path).items():
            summarise(df, f"{path.name} / sheet: {sheet}")


if __name__ == "__main__":
    main()

#after running above, found 1117 missing values in DCOILWTICO.csv, and 0 or negative values in the same column.
df = pd.read_csv("data/raw/DCOILWTICO.csv", parse_dates=["observation_date"])
missing = df[df["DCOILWTICO"].isna()]
print(missing.groupby(missing["observation_date"].dt.year).size())
print(df.loc[df["DCOILWTICO"] <= 0])

#48 days missing in 2011, are these scattered? 

m = df[df["DCOILWTICO"].isna() & (df["observation_date"].dt.year == 2011)]
print(m["observation_date"].dt.strftime("%Y-%m-%d").tolist())