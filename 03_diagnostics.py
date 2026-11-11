"""
03_diagnostics.py
Step 3: full-sample diagnostics that justify the model choices, BEFORE backtesting.

  1. Fat tails:   skew, excess kurtosis, Jarque-Bera  -> a normal model would understate risk
  2. Clustering:  Ljung-Box on returns and on squared returns -> motivates GARCH
  3. GARCH(1,1)-t on the full sample -> persistence, half-life of shocks, tail thickness (nu)
  4. GPD on the largest 10% of losses -> tail shape xi; threshold diagnostics (plots)

Outputs: results/diagnostics.csv, figures/returns.png, figures/qq_normal.png,
         figures/evt_threshold.png
"""
import matplotlib
matplotlib.use("Agg")  # save figures to file without opening windows
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

import config as cfg
from risk_models import fit_garch_t, fit_gpd, garch_state, pot_var_es


def ljung_box(x, lags=10):
    """Ljung-Box Q test: are the first `lags` autocorrelations jointly zero?"""
    x = np.asarray(x) - np.mean(x)
    n = len(x)
    denom = np.sum(x ** 2)
    acf = np.array([np.sum(x[k:] * x[:-k]) / denom for k in range(1, lags + 1)])
    q_stat = n * (n + 2) * np.sum(acf ** 2 / (n - np.arange(1, lags + 1)))
    return q_stat, stats.chi2.sf(q_stat, lags)


def diagnose(name, r):
    losses = -r
    out = {"series": name, "n": len(r), "mean": r.mean(), "std": r.std(ddof=1),
           "skew": stats.skew(r), "excess_kurt": stats.kurtosis(r)}
    out["jarque_bera_p"] = stats.jarque_bera(r).pvalue
    out["ljung_box_r_p"] = ljung_box(r)[1]          # linear predictability
    out["ljung_box_r2_p"] = ljung_box(r ** 2)[1]    # volatility clustering

    res, ok = fit_garch_t(r)
    g, z, _ = garch_state(res, r)
    persistence = g["alpha"] + g["beta"]
    out.update({f"garch_{k}": v for k, v in g.items()})
    out["garch_converged"] = ok
    out["garch_persistence"] = persistence
    # Days for a volatility shock to decay by half: persistence^h = 0.5
    out["garch_half_life_days"] = np.log(0.5) / np.log(persistence) if persistence < 1 else np.inf

    _, (u, xi, beta) = pot_var_es(losses, cfg.LEVELS, cfg.EVT_TAIL_FRACTION)
    out.update({"gpd_threshold": u, "gpd_xi": xi, "gpd_beta": beta,
                "tail_index": 1 / xi if xi > 0 else np.inf})
    # Tail of the GARCH residuals: what is left after removing clustering
    _, (_, xi_z, _) = pot_var_es(-z, cfg.LEVELS, cfg.EVT_TAIL_FRACTION)
    out["gpd_xi_garch_resid"] = xi_z

    print(f"\n--- {name}: GARCH(1,1)-t full-sample estimates (robust std. errors) ---")
    print(pd.DataFrame({"estimate": res.params, "std_err": res.std_err,
                        "p_value": res.pvalues}).round(4).to_string())
    return out


def threshold_plots(returns):
    """Mean excess plot and xi-stability plot for each series.
    If losses above u follow a GPD with xi > 0, the mean excess e(u) = E[L - u | L > u]
    is roughly linear and upward-sloping in u, and the xi estimate is stable as
    u rises. The chosen threshold should sit where both settle down."""
    fig, axes = plt.subplots(2, len(cfg.SERIES), figsize=(14, 7))
    chosen = 1 - cfg.EVT_TAIL_FRACTION
    for j, name in enumerate(cfg.SERIES):
        losses = -returns[name]
        pct = np.arange(0.80, 0.985, 0.005)
        thresholds = np.quantile(losses, pct)
        mean_excess = [np.mean(losses[losses > u] - u) for u in thresholds]
        xis = [fit_gpd(losses[losses > u] - u)[0] for u in thresholds]

        ax = axes[0, j]
        ax.plot(thresholds, mean_excess, "o-", ms=3)
        ax.axvline(np.quantile(losses, chosen), color="red", ls="--",
                   label=f"chosen threshold ({chosen:.0%} quantile)")
        ax.set(title=f"{name}: mean excess plot", xlabel="threshold u (loss, %)",
               ylabel="mean excess e(u)")
        ax.legend(fontsize=8)

        ax = axes[1, j]
        ax.plot(pct * 100, xis, "o-", ms=3)
        ax.axvline(chosen * 100, color="red", ls="--")
        ax.set(title=f"{name}: shape estimate vs threshold",
               xlabel="threshold quantile (%)", ylabel=r"GPD shape $\xi$")
    fig.tight_layout()
    fig.savefig(cfg.FIG_DIR / "evt_threshold.png", dpi=150)
    plt.close(fig)


def descriptive_plots(df):
    fig, axes = plt.subplots(len(cfg.SERIES), 1, figsize=(12, 8), sharex=True)
    for ax, name in zip(axes, cfg.SERIES):
        s = df[df["series"] == name]
        ax.plot(s["date"], s["log_return"], lw=0.5)
        ax.set(title=f"{name} daily log returns (%)", ylabel="%")
    fig.tight_layout()
    fig.savefig(cfg.FIG_DIR / "returns.png", dpi=150)
    plt.close(fig)

    # QQ plots against the normal: points bending away from the line in the
    # corners are the fat tails a normal VaR model would miss
    fig, axes = plt.subplots(1, len(cfg.SERIES), figsize=(14, 4.5))
    for ax, name in zip(axes, cfg.SERIES):
        r = df.loc[df["series"] == name, "log_return"].to_numpy()
        zs = np.sort((r - r.mean()) / r.std(ddof=1))
        theo = stats.norm.ppf((np.arange(1, len(zs) + 1) - 0.5) / len(zs))
        ax.scatter(theo, zs, s=4)
        lim = [theo.min(), theo.max()]
        ax.plot(lim, lim, color="red", lw=1)
        ax.set(title=f"{name}: QQ plot vs normal", xlabel="normal quantile",
               ylabel="standardised return")
    fig.tight_layout()
    fig.savefig(cfg.FIG_DIR / "qq_normal.png", dpi=150)
    plt.close(fig)


def main():
    cfg.RESULTS_DIR.mkdir(exist_ok=True)
    cfg.FIG_DIR.mkdir(exist_ok=True)
    df = pd.read_csv(cfg.DATA_DIR / "returns_long.csv", parse_dates=["date"])
    returns = {s: df.loc[df["series"] == s, "log_return"].to_numpy() for s in cfg.SERIES}

    table = pd.DataFrame([diagnose(s, returns[s]) for s in cfg.SERIES]).set_index("series")
    table.to_csv(cfg.RESULTS_DIR / "diagnostics.csv")
    print("\n=== Full-sample diagnostics ===")
    print(table.T.round(4).to_string())

    descriptive_plots(df)
    threshold_plots(returns)
    print(f"\nSaved results/diagnostics.csv and figures to {cfg.FIG_DIR}")


if __name__ == "__main__":
    main()
