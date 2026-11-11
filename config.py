"""
config.py
Settings shared by every script, so each modelling choice lives in one place.
Change a number here and every later script picks it up.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "processed"
RESULTS_DIR = BASE_DIR / "results"
FIG_DIR = BASE_DIR / "figures"

SERIES = ["WTI", "Brent", "HenryHub"]
MODELS = ["HS", "GARCH-t", "EVT", "GARCH-EVT"]

# Confidence levels. 99% VaR is the Basel backtesting standard, 97.5% ES is the
# Basel FRTB capital measure, and 95% is common for internal risk limits.
LEVELS = [0.95, 0.975, 0.99]

# Rolling estimation window: 1000 trading days (about 4 years). Long enough for
# stable GARCH and tail estimates, short enough to adapt as markets change.
WINDOW = 1000

# GARCH parameters are re-estimated every 20 trading days (about monthly).
# Between refits the variance is still updated DAILY with each new return, so
# forecasts react to shocks immediately; only the parameters are held fixed.
REFIT_EVERY = 20

# EVT threshold: the largest 10% of losses in the window (about 100 points).
# Trade-off: a higher threshold fits GPD theory better (less bias) but leaves
# fewer points to estimate from (more variance). 03_diagnostics.py checks it.
EVT_TAIL_FRACTION = 0.10

# Stress regime: days whose trailing 21-day volatility, measured up to the day
# BEFORE the forecast, is in the top 10% of the backtest period (per series).
STRESS_VOL_WINDOW = 21
STRESS_QUANTILE = 0.90

# Named stress episodes, reported separately. Add more as (start, end) pairs.
EVENTS = {
    "Covid crash (Mar-May 2020)": ("2020-03-01", "2020-05-31"),
    "Russia-Ukraine (Feb-Jun 2022)": ("2022-02-24", "2022-06-30"),
}
