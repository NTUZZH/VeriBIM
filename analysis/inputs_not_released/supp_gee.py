"""GEE for a paired two-arm comparison of task completion, clustered by building: logistic link, exchangeable working
correlation, bias-reduced (Mancl-DeRouen) covariance. The environment of the generators has no statsmodels, so
this module ports, step by step, the code path that the old chain ran through statsmodels 0.14.6:

    stats/run_stats.statsmodels_fits and
    macros/make_macros_rev2.gee_bias_reduced:
        sm.GEE(y, add_constant(arm), groups=building, family=Binomial(), cov_struct=Exchangeable())
          .fit(cov_type='bias_reduced', maxiter=200)

Ported pieces of statsmodels 0.14.6 (genmod/generalized_estimating_equations.py, genmod/cov_struct.py,
genmod/generalized_linear_model.py, genmod/families):
  starting values   GLM(y, X, Binomial()).fit(): IRLS from mu = (y + 0.5) / 2, weighted least squares by lstsq,
                    stop when two successive deviances differ by at most 1e-8, at most 100 iterations
  GEE.fit           one Fisher-scoring step per iteration, then an update of the exchangeable correlation;
                    stop when the norm of the score (at the parameters before the step) is below 1e-6 after at
                    least one correlation update, at most `maxiter` iterations; ddof_scale = number of columns of X
  Exchangeable      update() and covariance_matrix_solve() as in cov_struct.Exchangeable
  covariances       GEE._covmat (scale 1 for the binomial family) and GEE._bc_covmat
  standard error    square root of the diagonal of the bias-reduced covariance

`gee_bias_reduced` then applies the rule of make_macros_rev2.gee_bias_reduced (finite standard error, |beta| < 15,
standard error < 20, else separation) and returns the same dictionary. The port is checked against the GEE values
that statsmodels wrote into stats/results/comparisons.csv (supp_check_standin.py).
"""
import math
import warnings

import numpy as np
from scipy import stats

FLOAT_EPS = np.finfo(float).eps


# ---------------------------------------------------------------- binomial family, logit link (statsmodels families)
def _clean_p(p):
    """links.Logit._clean and varfuncs.Binomial._clean: clip to [eps, 1 - eps]."""
    return np.clip(p, FLOAT_EPS, 1.0 - FLOAT_EPS)


def _linkinv(z):
    """links.Logit.inverse."""
    z = np.asarray(z)
    t = np.exp(-z)
    return 1.0 / (1.0 + t)


def _linkinv_deriv(z):
    """links.Logit.inverse_deriv."""
    t = np.exp(z)
    return t / (1 + t) ** 2


def _link(p):
    """links.Logit.__call__."""
    p = _clean_p(p)
    return np.log(p / (1.0 - p))


def _link_deriv(p):
    """links.Logit.deriv."""
    p = _clean_p(p)
    return 1.0 / (p * (1 - p))


def _variance(mu):
    """varfuncs.Binomial (n = 1)."""
    p = _clean_p(mu)
    return p * (1 - p)


def _deviance(y, mu):
    """families.Binomial deviance with unit weights and scale 1 (_resid_dev summed)."""
    endog_mu = np.clip(y / (mu + 1e-20), FLOAT_EPS, np.inf)
    one_minus = np.clip((1 - y) / (1 - mu + 1e-20), FLOAT_EPS, np.inf)
    resid_dev = y * np.log(endog_mu) + (1 - y) * np.log(one_minus)
    return float(np.sum(2 * resid_dev))


def _glm_start(y, X, maxiter=100, tol=1e-8):
    """GLM._fit_irls with default arguments (start mu = (y + .5) / 2, deviance criterion, atol = tol, rtol = 0)."""
    mu = (y + 0.5) / 2
    lin_pred = _link(mu)
    dev = _deviance(y, mu)
    crit = [np.inf, dev]
    params = np.zeros(X.shape[1])
    for it in range(maxiter):
        w = 1.0 / (_link_deriv(mu) ** 2 * _variance(mu))
        wlsendog = lin_pred + _link_deriv(mu) * (y - mu)
        sw = np.sqrt(w)
        params = np.linalg.lstsq(X * sw[:, None], wlsendog * sw, rcond=-1)[0]
        lin_pred = X @ params
        mu = _linkinv(lin_pred)
        crit.append(_deviance(y, mu))
        if np.allclose(crit[it + 1], crit[it + 2], atol=tol, rtol=0.0):
            break
    return params


# ---------------------------------------------------------------- the GEE
class _Gee:
    def __init__(self, y, X, groups):
        y = np.asarray(y, float)
        X = np.asarray(X, float)
        labels, ix = np.unique(np.asarray(groups), return_inverse=True)
        idx = [np.flatnonzero(ix == k) for k in range(len(labels))]      # row order kept inside a group
        self.y_li = [y[i] for i in idx]
        self.X_li = [X[i, :] for i in idx]
        self.y, self.X = y, X
        self.nobs = len(y)
        self.ddof = X.shape[1]
        self.dep = 0.0
        self.update_dep = max(len(v) for v in self.y_li) > 1

    def means(self, params):
        self.cached = []
        for Xi in self.X_li:
            lpr = Xi @ params
            self.cached.append((_linkinv(lpr), lpr))

    def solve(self, expval, stdev, rhs):
        """cov_struct.Exchangeable.covariance_matrix_solve."""
        k = len(expval)
        c = self.dep / (1.0 - self.dep)
        c /= 1.0 + self.dep * (k - 1)
        out = []
        for x in rhs:
            if x.ndim == 1:
                x1 = x / stdev
                yv = x1 / (1.0 - self.dep)
                yv -= c * sum(x1)
                yv /= stdev
            else:
                x1 = x / stdev[:, None]
                yv = x1 / (1.0 - self.dep)
                yv -= c * x1.sum(0)
                yv /= stdev[:, None]
            out.append(yv)
        return out

    def update_mean(self):
        """GEE._update_mean_params."""
        bmat, score = 0, 0
        for yi, Xi, (expval, lpr) in zip(self.y_li, self.X_li, self.cached):
            resid = yi - expval
            dmat = Xi * _linkinv_deriv(lpr)[:, None]
            sdev = np.sqrt(_variance(expval))
            vinv_d, vinv_resid = self.solve(expval, sdev, (dmat, resid))
            bmat = bmat + dmat.T @ vinv_d
            score = score + dmat.T @ vinv_resid
        try:
            update = np.linalg.solve(bmat, score)
        except np.linalg.LinAlgError:
            update = np.linalg.pinv(bmat) @ score
        return update, score

    def update_assoc(self):
        """cov_struct.Exchangeable.update (no weights)."""
        residsq_sum, scale = 0.0, 0.0
        fsum1, fsum2, n_pairs = 0.0, 0.0, 0.0
        for yi, (expval, _) in zip(self.y_li, self.cached):
            stdev = np.sqrt(_variance(expval))
            resid = (yi - expval) / stdev
            ssr = np.sum(resid * resid)
            scale += ssr
            fsum1 += len(yi)
            residsq_sum += (resid.sum() ** 2 - ssr) / 2
            ngrp = len(resid)
            npr = 0.5 * ngrp * (ngrp - 1)
            fsum2 += npr
            n_pairs += npr
        scale /= (fsum1 * (self.nobs - self.ddof) / float(self.nobs))
        residsq_sum /= scale
        self.dep = residsq_sum / (fsum2 * (n_pairs - self.ddof) / float(n_pairs))

    def fit(self, maxiter=200, ctol=1e-6):
        """GEE.fit(cov_type='bias_reduced', maxiter=maxiter) with the default params_niter = 1, first_dep_update = 0."""
        params = _glm_start(self.y, self.X)
        self.means(params)
        del_params, n_assoc = -1.0, 0
        for itr in range(maxiter):
            update, score = self.update_mean()
            params = params + update
            self.means(params)
            del_params = float(np.sqrt(np.sum(score ** 2)))
            if del_params < ctol and (n_assoc > 0 or self.update_dep is False):
                break
            if self.update_dep:
                self.update_assoc()
                n_assoc += 1
        self.converged = del_params < ctol
        if not self.converged:
            warnings.warn('GEE: iteration limit reached prior to convergence')
        # GEE._covmat (scale = 1 for the binomial family, scaling_factor = 1)
        bmat = 0
        for yi, Xi, (expval, lpr) in zip(self.y_li, self.X_li, self.cached):
            dmat = Xi * _linkinv_deriv(lpr)[:, None]
            sdev = np.sqrt(_variance(expval))
            vinv_d, = self.solve(expval, sdev, (dmat,))
            bmat = bmat + dmat.T @ vinv_d
        try:
            cov_naive = np.linalg.inv(bmat)
        except np.linalg.LinAlgError:
            cov_naive = np.linalg.pinv(bmat)
        # GEE._bc_covmat
        bcm = 0
        for yi, Xi, (expval, lpr) in zip(self.y_li, self.X_li, self.cached):
            resid = yi - expval
            dmat = Xi * _linkinv_deriv(lpr)[:, None]
            sdev = np.sqrt(_variance(expval))
            vinv_d = self.solve(expval, sdev, (dmat,))[0]
            hmat = (vinv_d @ cov_naive @ dmat.T).T
            aresid = np.linalg.solve(np.eye(len(resid)) - hmat, resid)
            srt = self.solve(expval, sdev, (aresid,))[0]
            srt = dmat.T @ srt
            bcm = bcm + np.outer(srt, srt)
        cov_bc = cov_naive @ bcm @ cov_naive
        self.params = params
        self.bse = np.sqrt(np.diag(cov_bc))
        return self


def gee_bias_reduced(ya, yb, bl):
    """make_macros_rev2.gee_bias_reduced on the port: rows are arm A (arm = 1) then arm B (arm = 0), clusters are
    buildings; returns beta1, its standard error, the separation flag, the odds ratio and the Wald p."""
    ya, yb = np.asarray(ya, float), np.asarray(yb, float)
    n = len(ya)
    y = np.concatenate([ya, yb])
    arm = np.r_[np.ones(n), np.zeros(n)]
    X = np.column_stack([np.ones(2 * n), arm])
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore')
        r = _Gee(y, X, list(bl) * 2).fit(maxiter=200)
    b1, se = float(r.params[1]), float(r.bse[1])
    ok = math.isfinite(se) and se > 0 and abs(b1) < 15 and se < 20
    return {'beta1': b1, 'se_beta1': se, 'separation': not ok, 'odds_ratio': math.exp(b1) if ok else math.nan,
            'wald_p': float(2 * stats.norm.sf(abs(b1 / se))) if ok else math.nan, 'working_correlation': float(r.dep),
            'converged': bool(r.converged)}
