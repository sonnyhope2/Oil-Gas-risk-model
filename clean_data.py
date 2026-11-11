"""
02_clean_data.py
Step 2: clean raw FRED prices and compute daily log returns.

Decisions (see README):
  - Common sample starts 2008-01-01 (pre-2008 EIA data has irregular gaps,
    especially Henry Hub in 2005-07).
  - Missing days are DROPPED, not filled. Forward-filling creates fake zero
    returns and interpolation invents a smooth path; both understate volatility.
  - Non-positive prices (WTI on 2020-04-20) are dropped like missing days, so the
    next return spans the gap. This keeps the size of the shock in the data
    instead of deleting the stress event. The affected return is flagged.
  - Returns are log returns x 100 (percent). Scaling helps GARCH optimisers converge.

Run:  python 02_clean_data.py
Output: data/processed/returns_long.csv and returns_wide.csv
"""

from pathlib import Path
import numpy as np
import pandas as pd

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed")
SERIES = {"DCOILWTICO": "WTI", "DCOILBRENTEU": "Brent", "DHHNGSP": "HenryHub"}
START = "2008-01-01"
GAP_FLAG_DAYS = 5  # a normal weekend is 3 calendar days, a long weekend 4


def clean_series(sid: str, name: str) -> pd.DataFrame:
    df = pd.read_csv(RAW_DIR / f"{sid}.csv", parse_dates=["observation_date"])
    df = df.rename(columns={"observation_date": "date", sid: "price"})
    df = df[df["date"] >= START].dropna(subset=["price"]).sort_values("date")

    # Record and drop non-positive prices (log is undefined for them)
    nonpos = df[df["price"] <= 0]
    for _, row in nonpos.iterrows():
        print(f"[{name}] dropping non-positive price {row['price']} on {row['date'].date()}")
    df = df[df["price"] > 0].reset_index(drop=True)

    df["log_return"] = 100 * np.log(df["price"]).diff()
    df["gap_days"] = df["date"].diff().dt.days
    df["long_gap"] = df["gap_days"] > GAP_FLAG_DAYS

    # Flag the first return after each dropped non-positive price
    df["after_nonpositive"] = False
    for d in nonpos["date"]:
        nxt = df.index[df["date"] > d]
        if len(nxt):
            df.loc[nxt[0], "after_nonpositive"] = True

    df["series"] = name
    return df.iloc[1:]  # first row has no previous price, so no return


def summary_stats(long: pd.DataFrame) -> pd.DataFrame:
    g = long.groupby("series")["log_return"]
    return pd.DataFrame({
        "n": g.count(),
        "start": long.groupby("series")["date"].min().dt.date,
        "mean": g.mean(),
        "std": g.std(),
        "min": g.min(),
        "max": g.max(),
        "skew": g.skew(),
        "excess_kurt": g.apply(pd.Series.kurt),  # normal distribution = 0
    }).round(3)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    long = pd.concat([clean_series(s, n) for s, n in SERIES.items()],
                     ignore_index=True)

    print("\n=== Summary statistics (daily log returns, %) ===")
    print(summary_stats(long).to_string())

    print(f"\n=== Returns spanning more than {GAP_FLAG_DAYS} calendar days ===")
    print(long.groupby("series")["long_gap"].sum().to_string())

    print("\n=== Return after a dropped non-positive price ===")
    print(long.loc[long["after_nonpositive"],
                   ["series", "date", "price", "log_return", "gap_days"]].to_string(index=False))

    cols = ["series", "date", "price", "log_return", "gap_days"]
    for name, grp in long.groupby("series"):
        print(f"\n=== {name}: 5 largest losses ===")
        print(grp.nsmallest(5, "log_return")[cols].to_string(index=False))
        print(f"=== {name}: 5 largest gains ===")
        print(grp.nlargest(5, "log_return")[cols].to_string(index=False))

    long.to_csv(OUT_DIR / "returns_long.csv", index=False)
    long.pivot(index="date", columns="series", values="log_return") \
        .to_csv(OUT_DIR / "returns_wide.csv")
    print(f"\nSaved {len(long)} rows to {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()