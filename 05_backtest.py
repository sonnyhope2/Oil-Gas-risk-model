"""
05_backtest.py
Step 5: backtest the forecasts and compare models in calm and stress periods.

VaR tests, on the hit sequence I_t = 1 if loss_t > VaR_t else 0:
  Kupiec POF         Is the exceedance RATE right? (unconditional coverage)
  Christoffersen     Are exceedances INDEPENDENT, or do they cluster?
  Conditional cov.   Both at once: LR_cc = LR_uc + LR_ind ~ chi2(2)
ES checks (VaR tests say nothing about HOW BIG losses are beyond VaR):
  Acerbi-Szekely Z2  Realised tail losses vs forecast ES. Z2 near 0 is good;
                     Z2 < -0.70 suggests ES is too low (approximate 5% critical
                     value, derived for the 97.5% level, so only applied there).
  ES ratio           Mean loss on exceedance days / mean forecast ES on those days.
                     1 = accurate, above 1 = ES too low.
Scores (lower = better). These rank models even where tests have little power:
  Quantile loss      Consistent scoring function for VaR.
  FZ0 loss           Consistent joint score for (VaR, ES) (Patton, Ziegel & Chen 2019).

Outputs: results/backtest_full.csv, backtest_regimes.csv, backtest_events.csv,
         model_ranking.csv
"""
import numpy as np
import pandas as pd
from scipy.special import xlogy
from scipy.stats import chi2

import config as cfg

Z2_CRITICAL_5PCT = -0.70
TABLE_COLS = ["n", "exceed", "expected", "rate_%", "p_uc", "p_ind", "p_cc",
              "Z2", "Z2_test", "ES_ratio", "QL", "FZ0"]


# ----------------------------------------------------------- tests ------
def kupiec(hits, p):
    """Kupiec proportion-of-failures test. H0: P(exceedance) = p."""
    n, x = len(hits), hits.sum()
    p_hat = x / n
    log_l0 = xlogy(n - x, 1 - p) + xlogy(x, p)
    log_l1 = xlogy(n - x, 1 - p_hat) + xlogy(x, p_hat)
    return -2 * (log_l0 - log_l1)


def christoffersen(prev, hits):
    """Christoffersen independence test. H0: today's exceedance probability does
    not depend on whether yesterday was an exceedance (no clustering).
    Uses pairs (I_{t-1}, I_t), so it also works on non-contiguous subsamples."""
    n00 = np.sum((prev == 0) & (hits == 0))
    n01 = np.sum((prev == 0) & (hits == 1))
    n10 = np.sum((prev == 1) & (hits == 0))
    n11 = np.sum((prev == 1) & (hits == 1))
    pi01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    pi11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    log_l0 = xlogy(n00 + n10, 1 - pi) + xlogy(n01 + n11, pi)
    log_l1 = (xlogy(n00, 1 - pi01) + xlogy(n01, pi01)
              + xlogy(n10, 1 - pi11) + xlogy(n11, pi11))
    return -2 * (log_l0 - log_l1)


def evaluate(d, q):
    """All tests and scores for one series / model / level / subsample."""
    p = 1 - q
    hits = d["hit"].to_numpy()
    loss, var = d["loss"].to_numpy(), d["VaR"].to_numpy()
    es = np.maximum(d["ES"].to_numpy(), 1e-6)  # ES > 0 needed for the log in FZ0
    n, x = len(d), hits.sum()

    lr_uc = kupiec(hits, p)
    pairs = d["prev_hit"].notna().to_numpy()
    lr_ind = christoffersen(d["prev_hit"].to_numpy()[pairs], hits[pairs])

    z2 = 1 - np.sum(loss * hits / es) / (n * p)
    es_ratio = loss[hits == 1].mean() / es[hits == 1].mean() if x else np.nan
    ql = np.mean((q - (loss < var)) * (loss - var))
    fz0 = np.mean(hits * (loss - var) / (p * es) + var / es + np.log(es) - 1)

    return {"n": n, "exceed": int(x), "expected": n * p, "rate_%": 100 * x / n,
            "p_uc": chi2.sf(lr_uc, 1), "p_ind": chi2.sf(lr_ind, 1),
            "p_cc": chi2.sf(lr_uc + lr_ind, 2), "Z2": z2, "ES_ratio": es_ratio,
            "QL": ql, "FZ0": fz0}


def evaluate_groups(fc, by):
    rows = []
    for keys, d in fc.groupby(by, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        level = dict(zip(by, keys))["level"]
        rows.append({**dict(zip(by, keys)), **evaluate(d, level)})
    out = pd.DataFrame(rows)
    # The Z2 critical value was derived at 97.5%; leave the verdict blank elsewhere
    verdict = np.where(out["Z2"] < Z2_CRITICAL_5PCT, "reject", "ok")
    out["Z2_test"] = np.where(np.isclose(out["level"], 0.975), verdict, "")
    return out


# ----------------------------------------------------------- regimes ----
def add_regimes(fc, returns):
    """Label each forecast day calm or stress using trailing volatility measured
    up to the day BEFORE the forecast. Using only past information keeps the
    tests valid: selecting days by their own returns would mechanically put
    big losses (and exceedances) into the stress group."""
    returns = returns.sort_values(["series", "date"]).copy()
    returns["lag_vol"] = (returns.groupby("series")["log_return"]
                          .transform(lambda s: s.rolling(cfg.STRESS_VOL_WINDOW).std().shift(1)))
    fc = fc.merge(returns[["series", "date", "lag_vol"]], on=["series", "date"], how="left")
    cutoff = (fc.drop_duplicates(["series", "date"]).groupby("series")["lag_vol"]
              .quantile(cfg.STRESS_QUANTILE))
    fc["regime"] = np.where(fc["lag_vol"] > fc["series"].map(cutoff), "stress", "calm")
    print("Stress cut-off (trailing 21-day volatility, % per day):")
    print(cutoff.round(2).to_string())
    return fc


def print_table(df, title, index):
    print(f"\n=== {title} ===")
    show = df.set_index(index)[TABLE_COLS].round(3)
    print(show.to_string())


def main():
    fc = pd.read_csv(cfg.RESULTS_DIR / "forecasts.csv", parse_dates=["date"])
    returns = pd.read_csv(cfg.DATA_DIR / "returns_long.csv", parse_dates=["date"])

    fc = fc.dropna(subset=["VaR", "ES"]).sort_values(["series", "model", "level", "date"])
    fc["hit"] = (fc["loss"] > fc["VaR"]).astype(int)
    fc["prev_hit"] = fc.groupby(["series", "model", "level"])["hit"].shift(1)
    fc = add_regimes(fc, returns)

    # ---- Full sample ----
    full = evaluate_groups(fc, ["series", "model", "level"])
    full.to_csv(cfg.RESULTS_DIR / "backtest_full.csv", index=False)
    for q in cfg.LEVELS:
        print_table(full[full["level"] == q], f"FULL SAMPLE, {q:.1%} level", ["series", "model"])

    # ---- Calm vs stress ----
    reg = evaluate_groups(fc, ["regime", "series", "model", "level"])
    reg.to_csv(cfg.RESULTS_DIR / "backtest_regimes.csv", index=False)
    for q in cfg.LEVELS:
        cols = ["rate_%", "p_uc", "p_ind", "ES_ratio"]
        t = reg[reg["level"] == q].pivot_table(index=["series", "model"], columns="regime",
                                               values=cols)
        t = t.reindex(columns=pd.MultiIndex.from_product([cols, ["calm", "stress"]]))
        print(f"\n=== CALM vs STRESS, {q:.1%} level (expected rate {100 * (1 - q):.1f}%) ===")
        print(t.round(3).to_string())

    # ---- Named stress events (descriptive: too few days for tests to have power) ----
    ev_rows = []
    for event, (start, end) in cfg.EVENTS.items():
        d = fc[(fc["date"] >= start) & (fc["date"] <= end)]
        for (series, model, level), g in d.groupby(["series", "model", "level"]):
            worst = g.loc[g["loss"].idxmax()]
            ev_rows.append({"event": event, "series": series, "model": model, "level": level,
                            **evaluate(g, level), "worst_day": worst["date"].date(),
                            "worst_loss": worst["loss"], "VaR_on_worst_day": worst["VaR"],
                            "ES_on_worst_day": worst["ES"]})
    events = pd.DataFrame(ev_rows)
    events.to_csv(cfg.RESULTS_DIR / "backtest_events.csv", index=False)
    for event in cfg.EVENTS:
        e = events[(events["event"] == event) & (events["level"] == 0.99)]
        print(f"\n=== EVENT: {event}, 99% level ===")
        print(e.set_index(["series", "model"])[["n", "exceed", "expected", "ES_ratio", "FZ0",
                                                "worst_day", "worst_loss", "VaR_on_worst_day",
                                                "ES_on_worst_day"]].round(2).to_string())

    # ---- Ranking: which model scores best (lowest FZ0) in each setting? ----
    reg_all = pd.concat([full.assign(regime="full"), reg])
    reg_all["rank"] = reg_all.groupby(["regime", "series", "level"])["FZ0"].rank()
    ranking = reg_all.pivot_table(index="model", columns="regime", values="rank", aggfunc="mean")
    ranking = ranking[["full", "calm", "stress"]].sort_values("stress")
    ranking.to_csv(cfg.RESULTS_DIR / "model_ranking.csv")
    print("\n=== Average FZ0 rank (1 = best), across series and levels ===")
    print(ranking.round(2).to_string())

    by_series = reg_all[reg_all["regime"] == "stress"].pivot_table(
        index="model", columns="series", values="rank", aggfunc="mean")
    print("\n=== Average FZ0 rank in STRESS, by series ===")
    print(by_series.round(2).to_string())

    print(f"\nSaved backtest tables to {cfg.RESULTS_DIR}")


if __name__ == "__main__":
    main()
