"""
risk_models.py
VaR and ES estimators used by the diagnostics and the rolling backtest.

Sign convention: everything works on LOSSES (loss = -return, in %), so VaR and
ES are positive numbers. VaR_q is the loss exceeded with probability 1 - q;
ES_q is the average loss on the days when VaR_q is exceeded.

Models
  HS         Historical simulation: empirical quantile of the last WINDOW losses.
  GARCH-t    GARCH(1,1), constant mean, Student-t errors (fat tails + clustering).
  EVT        Peaks over threshold: GPD fitted to the largest losses (unconditional).
  GARCH-EVT  McNeil & Frey (2000): GARCH filters out volatility clustering, then a
             GPD models the tail of the standardised residuals.
"""
import warnings

import numpy as np
from arch import arch_model
from arch.utility.exceptions import StartingValueWarning
from scipy import stats


# ---------------------------------------------------------------- HS ------
def hs_var_es(losses, levels):
    """Historical simulation: read VaR/ES straight off the empirical distribution."""
    out = {}
    for q in levels:
        var = np.quantile(losses, q)
        es = losses[losses >= var].mean()
        out[q] = (var, es)
    return out


# ---------------------------------------------------------------- EVT -----
def fit_gpd(excesses):
    """Maximum-likelihood fit of a Generalised Pareto Distribution to excesses
    over the threshold (location fixed at 0). Returns (xi, beta):
      xi   shape: > 0 means a power-law (heavy) tail; tail index = 1 / xi
      beta scale
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # harmless optimiser noise
        xi, _, beta = stats.genpareto.fit(excesses, floc=0)
    return xi, beta


def pot_var_es(losses, levels, tail_fraction):
    """Peaks-over-threshold VaR and ES (McNeil, Frey & Embrechts, ch. 5).

    Threshold u = (1 - tail_fraction) quantile of the losses. Above u, losses are
    modelled by a GPD; below u we never need a model because VaR_q sits above u.
    Returns ({q: (VaR, ES)}, (u, xi, beta)).
    """
    n = len(losses)
    u = np.quantile(losses, 1 - tail_fraction)
    excesses = losses[losses > u] - u
    n_u = len(excesses)
    xi, beta = fit_gpd(excesses)

    out = {}
    for q in levels:
        assert q > 1 - tail_fraction, "VaR level must lie above the EVT threshold"
        # (prob. of exceeding VaR) / (prob. of exceeding u)
        ratio = n / n_u * (1 - q)
        if abs(xi) < 1e-6:  # xi -> 0 limit: exponential tail
            var = u - beta * np.log(ratio)
            es = var + beta
        else:
            var = u + beta / xi * (ratio ** (-xi) - 1)
            # ES is only finite if xi < 1 (the tail has a finite mean)
            es = (var + beta - xi * u) / (1 - xi) if xi < 1 else np.nan
        out[q] = (var, es)
    return out, (u, xi, beta)


# -------------------------------------------------------------- GARCH -----
def fit_garch_t(returns, starting_values=None, fallback_params=None):
    """Fit a constant-mean GARCH(1,1) with Student-t errors:

        r_t = mu + eps_t,   eps_t = sigma_t * z_t,   z_t ~ t(nu) scaled to variance 1
        sigma_t^2 = omega + alpha * eps_{t-1}^2 + beta * sigma_{t-1}^2

    If the optimiser fails to converge and fallback_params (the last good
    estimates) are given, the window is filtered with those fixed parameters.
    Returns (result, converged).
    """
    am = arch_model(returns, mean="Constant", vol="GARCH", p=1, q=1,
                    dist="t", rescale=False)
    with warnings.catch_warnings():
        # Last window's estimates are used as a warm start; if they sit on a
        # constraint boundary arch ignores them and uses its own defaults.
        warnings.simplefilter("ignore", StartingValueWarning)
        res = am.fit(disp="off", show_warning=False, starting_values=starting_values)
    converged = res.convergence_flag == 0
    if not converged and fallback_params is not None:
        res = am.fix(fallback_params)
    return res, converged


def garch_state(res, returns):
    """Extract parameters, standardised residuals and next-day variance."""
    p = res.params
    params = {"mu": p["mu"], "omega": p["omega"], "alpha": p["alpha[1]"],
              "beta": p["beta[1]"], "nu": p["nu"]}
    sigma = np.asarray(res.conditional_volatility)
    eps = np.asarray(returns) - params["mu"]
    z = eps / sigma
    # One-step-ahead variance forecast for the day after the window
    next_var = params["omega"] + params["alpha"] * eps[-1] ** 2 + params["beta"] * sigma[-1] ** 2
    return params, z, next_var


def std_t_var_es(nu, levels):
    """VaR and ES of -z, where z is Student-t(nu) rescaled to unit variance.

    For a standard t: VaR_q = t_q and ES_q = f(t_q) / (1-q) * (nu + t_q^2) / (nu - 1).
    Multiplying by sqrt((nu-2)/nu) converts to the unit-variance version that
    GARCH uses, so that sigma_t is the true conditional standard deviation.
    """
    scale = np.sqrt((nu - 2) / nu)
    out = {}
    for q in levels:
        tq = stats.t.ppf(q, nu)
        es = stats.t.pdf(tq, nu) / (1 - q) * (nu + tq ** 2) / (nu - 1)
        out[q] = (scale * tq, scale * es)
    return out
