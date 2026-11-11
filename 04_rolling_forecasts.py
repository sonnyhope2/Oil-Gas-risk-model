"""
04_rolling_forecasts.py
Step 4: out-of-sample, one-day-ahead VaR and ES forecasts for every model.

For each day t from WINDOW onwards, every model is estimated using only the
previous WINDOW returns (days t-WINDOW .. t-1) and forecasts the loss on day t.
Nothing from day t or later is used, so the backtest is genuinely out-of-sample.

  HS, EVT     re-estimated every day on the latest window
  GARCH-t,    parameters re-estimated every REFIT_EVERY days; the conditional
  GARCH-EVT   variance is updated every day with the newest return

Run time: a few minutes (the daily EVT refits dominate).
Outputs: results/forecasts.csv, results/garch_params.csv, results/evt_params.csv
"""
import time

import numpy as np
import pandas as pd

import config as cfg
from risk_models import fit_garch_t, garch_state, hs_var_es, pot_var_es, std_t_var_es


def run_series(name, df):
    dates = df["date"].to_numpy()
    r = df["log_return"].to_numpy()
    losses = -r
    n = len(r)
    forecasts, garch_log, evt_log = [], [], []
    prev_params = None
    n_failed = 0

    for start in range(cfg.WINDOW, n, cfg.REFIT_EVERY):
        # ---- Refit GARCH on the window ending the day before `start` ----
        window = r[start - cfg.WINDOW:start]
        res, converged = fit_garch_t(window, starting_values=prev_params,
                                     fallback_params=prev_params)
        n_failed += not converged
        g, z, sigma2 = garch_state(res, window)  # sigma2 = forecast variance for day `start`
        prev_params = res.params.to_numpy()

        # Tail of the standardised shock: Student-t (GARCH-t) or GPD (GARCH-EVT)
        t_tail = std_t_var_es(g["nu"], cfg.LEVELS)
        z_tail, (_, xi_z, _) = pot_var_es(-z, cfg.LEVELS, cfg.EVT_TAIL_FRACTION)
        garch_log.append({"series": name, "refit_date": dates[start], **g,
                          "persistence": g["alpha"] + g["beta"],
                          "converged": converged, "xi_resid": xi_z})

        # ---- Daily forecasts until the next refit ----
        for t in range(start, min(start + cfg.REFIT_EVERY, n)):
            sigma = np.sqrt(sigma2)
            hist = losses[t - cfg.WINDOW:t]
            hs = hs_var_es(hist, cfg.LEVELS)
            evt, (u, xi, beta) = pot_var_es(hist, cfg.LEVELS, cfg.EVT_TAIL_FRACTION)
            evt_log.append((name, dates[t], u, xi, beta))

            for q in cfg.LEVELS:
                # Loss = -mu - sigma * z, so loss quantile = -mu + sigma * (quantile of -z)
                forecasts += [
                    (name, dates[t], "HS", q, *hs[q], losses[t]),
                    (name, dates[t], "GARCH-t", q, -g["mu"] + sigma * t_tail[q][0],
                     -g["mu"] + sigma * t_tail[q][1], losses[t]),
                    (name, dates[t], "EVT", q, *evt[q], losses[t]),
                    (name, dates[t], "GARCH-EVT", q, -g["mu"] + sigma * z_tail[q][0],
                     -g["mu"] + sigma * z_tail[q][1], losses[t]),
                ]

            # Today's return is known by tomorrow: update tomorrow's variance
            eps = r[t] - g["mu"]
            sigma2 = g["omega"] + g["alpha"] * eps ** 2 + g["beta"] * sigma2

    fc = pd.DataFrame(forecasts, columns=["series", "date", "model", "level", "VaR", "ES", "loss"])
    evt_df = pd.DataFrame(evt_log, columns=["series", "date", "threshold", "xi", "beta"])
    return fc, pd.DataFrame(garch_log), evt_df, n_failed


def main():
    cfg.RESULTS_DIR.mkdir(exist_ok=True)
    df = pd.read_csv(cfg.DATA_DIR / "returns_long.csv", parse_dates=["date"])

    all_fc, all_garch, all_evt = [], [], []
    for name in cfg.SERIES:
        t0 = time.time()
        s = df[df["series"] == name].sort_values("date").reset_index(drop=True)
        fc, garch, evt, n_failed = run_series(name, s)
        all_fc.append(fc)
        all_garch.append(garch)
        all_evt.append(evt)
        n_days = fc["date"].nunique()
        print(f"{name}: {n_days} forecast days ({fc['date'].min().date()} to "
              f"{fc['date'].max().date()}), {len(garch)} GARCH refits, "
              f"{n_failed} non-converged, {time.time() - t0:.0f}s")

    fc = pd.concat(all_fc, ignore_index=True)
    garch = pd.concat(all_garch, ignore_index=True)
    evt = pd.concat(all_evt, ignore_index=True)
    fc.to_csv(cfg.RESULTS_DIR / "forecasts.csv", index=False)
    garch.to_csv(cfg.RESULTS_DIR / "garch_params.csv", index=False)
    evt.to_csv(cfg.RESULTS_DIR / "evt_params.csv", index=False)

    # ---- Sanity checks ----
    print("\nMissing VaR/ES forecasts (EVT ES is undefined if xi >= 1):")
    print(fc[["VaR", "ES"]].isna().groupby([fc["series"], fc["model"]]).sum().to_string())

    print("\nRange of rolling EVT shape estimates (xi):")
    print(evt.groupby("series")["xi"].describe()[["min", "50%", "max"]].round(3).to_string())

    print("\nRange of rolling GARCH parameters:")
    print(garch.groupby("series")[["persistence", "nu", "xi_resid"]]
          .agg(["min", "median", "max"]).round(3).to_string())

    # A single extreme return can dominate the GARCH likelihood and push beta
    # towards 0 (volatility treated as short-lived). Flag windows where that happens.
    low = garch[garch["persistence"] < 0.8]
    print(f"\nGARCH refits with persistence < 0.8: {len(low)}")
    if len(low):
        print(low.groupby("series")["refit_date"].agg(["count", "min", "max"]).to_string())

    print("\nAverage 99% VaR forecast by model (%):")
    print(fc[fc["level"] == 0.99].pivot_table(index="series", columns="model",
                                                values="VaR", aggfunc="mean").round(2).to_string())

    print("\n99% VaR on 2020-04-21 vs realised loss (the WTI negative-price episode):")
    day = fc[(fc["date"] == "2020-04-21") & (fc["level"] == 0.99)]
    print(day.pivot_table(index="series", columns="model", values="VaR").round(2)
          .join(day.groupby("series")["loss"].first().round(2)).to_string())

    print(f"\nSaved {len(fc)} forecast rows to {cfg.RESULTS_DIR}")


if __name__ == "__main__":
    main()
