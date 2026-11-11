"""
06_plots.py
Step 6: figures of the backtest results, for the README.

  figures/var99_<series>.png       losses vs 99% VaR for each model, exceedances marked
  figures/covid_zoom.png           99% VaR through the 2020 crash (WTI and Brent)
  figures/exceedance_regimes.png   99% exceedance rate, calm vs stress, by model
  figures/parameters.png           rolling GARCH persistence and EVT tail shape
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config as cfg

COLORS = {"HS": "tab:blue", "GARCH-t": "tab:orange", "EVT": "tab:green", "GARCH-EVT": "tab:purple"}
LEVEL = 0.99


def var_paths(fc):
    """One figure per series: four panels (one per model) of daily losses with
    the 99% VaR forecast; red dots are exceedances (loss > VaR)."""
    for name in cfg.SERIES:
        d = fc[(fc["series"] == name) & (fc["level"] == LEVEL)]
        # Clip the y-axis so ordinary days stay readable; extreme days are noted
        cap = 1.2 * max(d["VaR"].quantile(0.99), d["loss"].abs().quantile(0.998))
        fig, axes = plt.subplots(len(cfg.MODELS), 1, figsize=(12, 10), sharex=True)
        for ax, model in zip(axes, cfg.MODELS):
            m = d[d["model"] == model]
            hits = m[m["loss"] > m["VaR"]]
            ax.plot(m["date"], m["loss"], color="grey", lw=0.4, label="daily loss")
            ax.plot(m["date"], m["VaR"], color=COLORS[model], lw=1, label="99% VaR")
            ax.scatter(hits["date"], hits["loss"].clip(upper=cap), color="red", s=8,
                       zorder=3, label=f"exceedances ({len(hits)}, expected {0.01 * len(m):.0f})")
            off = ((m["loss"].abs() > cap) | (m["VaR"] > cap)).sum()
            ax.set_ylim(-cap / 2, cap)
            ax.set_title(f"{model}" + (f"  (axis clipped on {off} days)" if off else ""), fontsize=10)
            ax.set_ylabel("loss, %")
            ax.legend(loc="upper left", fontsize=8, ncol=3)
        fig.suptitle(f"{name}: daily loss vs one-day 99% VaR forecast", fontsize=12)
        fig.tight_layout()
        fig.savefig(cfg.FIG_DIR / f"var99_{name}.png", dpi=150)
        plt.close(fig)


def covid_zoom(fc):
    start, end = "2020-02-15", "2020-06-15"
    cap = 30
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, name in zip(axes, ["WTI", "Brent"]):
        d = fc[(fc["series"] == name) & (fc["level"] == LEVEL)
               & (fc["date"] >= start) & (fc["date"] <= end)]
        loss = d.drop_duplicates("date")
        ax.bar(loss["date"], loss["loss"].clip(-cap, cap), color="lightgrey", label="daily loss")
        for _, row in loss[loss["loss"] > cap].iterrows():
            ax.annotate(f"{row['loss']:.0f}% loss\n(off scale)", (row["date"], cap),
                        xytext=(10, -30), textcoords="offset points", fontsize=8,
                        arrowprops={"arrowstyle": "->"})
        for model in cfg.MODELS:
            m = d[d["model"] == model]
            ax.plot(m["date"], m["VaR"], color=COLORS[model], lw=1.5, label=model)
        ax.set(title=f"{name}: 99% VaR through the 2020 crash", ylabel="loss, %",
               ylim=(-cap / 2, cap * 1.05))
        ax.tick_params(axis="x", rotation=30)
        ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(cfg.FIG_DIR / "covid_zoom.png", dpi=150)
    plt.close(fig)


def exceedance_regimes():
    reg = pd.read_csv(cfg.RESULTS_DIR / "backtest_regimes.csv")
    reg = reg[np.isclose(reg["level"], LEVEL)]
    fig, axes = plt.subplots(1, len(cfg.SERIES), figsize=(14, 4.5), sharey=True)
    width = 0.38
    x = np.arange(len(cfg.MODELS))
    for ax, name in zip(axes, cfg.SERIES):
        d = reg[reg["series"] == name].set_index(["regime", "model"])["rate_%"]
        ax.bar(x - width / 2, [d.get(("calm", m), np.nan) for m in cfg.MODELS], width, label="calm")
        ax.bar(x + width / 2, [d.get(("stress", m), np.nan) for m in cfg.MODELS], width, label="stress")
        ax.axhline(100 * (1 - LEVEL), color="black", ls="--", lw=1, label="expected (1%)")
        ax.set_xticks(x, cfg.MODELS)
        ax.set(title=name, ylabel="exceedance rate, %")
        ax.legend(fontsize=8)
    fig.suptitle("99% VaR exceedance rate: calm vs stress days", fontsize=12)
    fig.tight_layout()
    fig.savefig(cfg.FIG_DIR / "exceedance_regimes.png", dpi=150)
    plt.close(fig)


def parameters():
    garch = pd.read_csv(cfg.RESULTS_DIR / "garch_params.csv", parse_dates=["refit_date"])
    evt = pd.read_csv(cfg.RESULTS_DIR / "evt_params.csv", parse_dates=["date"])
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    for name in cfg.SERIES:
        g = garch[garch["series"] == name]
        e = evt[evt["series"] == name]
        axes[0].plot(g["refit_date"], g["persistence"], label=name)
        axes[1].plot(g["refit_date"], g["nu"], label=name)
        axes[2].plot(e["date"], e["xi"], lw=0.8, label=name)
    axes[0].set(title=r"GARCH persistence $\alpha + \beta$ (near 1 = long-lived volatility)")
    axes[1].set(title=r"GARCH Student-t degrees of freedom $\nu$ (lower = fatter tails)")
    axes[2].set(title=r"EVT tail shape $\xi$ of losses (higher = heavier tail)")
    for ax in axes:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(cfg.FIG_DIR / "parameters.png", dpi=150)
    plt.close(fig)


def main():
    cfg.FIG_DIR.mkdir(exist_ok=True)
    fc = pd.read_csv(cfg.RESULTS_DIR / "forecasts.csv", parse_dates=["date"])
    var_paths(fc)
    covid_zoom(fc)
    exceedance_regimes()
    parameters()
    print(f"Saved figures to {cfg.FIG_DIR}")


if __name__ == "__main__":
    main()
