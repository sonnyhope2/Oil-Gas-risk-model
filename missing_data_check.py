import pandas as pd
for sid in ["DCOILWTICO", "DCOILBRENTEU", "DHHNGSP"]:
    df = pd.read_csv(f"data/raw/{sid}.csv", parse_dates=["observation_date"])
    miss = df[df[sid].isna()].groupby(df["observation_date"].dt.year).size()
    print(f"\n{sid} missing by year (2005+):\n{miss[miss.index >= 2005].to_string()}")
    print("Max:", df.loc[df[sid].idxmax(), ["observation_date", sid]].tolist())
    print("Min:", df.loc[df[sid].idxmin(), ["observation_date", sid]].tolist())