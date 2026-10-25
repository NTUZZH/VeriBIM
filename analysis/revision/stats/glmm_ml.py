"""Maximum-likelihood logistic mixed models for a paired two-arm comparison of task completion.

Data: one row per task and arm, y = 1 when the checker counts the task as completed, arm = 1 for arm A.
Linear predictor: logit P(y = 1) = beta0 + beta1 * arm + random intercepts.

  fit_building_quadrature   random intercept per building; the marginal likelihood is integrated on a dense
                            grid (trapezoid rule on the standardized effect, 1,601 points on [-8, 8]), so the
                            fit is ML without a Laplace approximation.
  fit_building_task         random intercept per building and per task (task nested in building), the paired
                            model; the two-level integral is evaluated on dense grids (401 x 401 points on
                            [-8, 8]), which is cheap because every task contributes one of four outcome patterns.
  fit_laplace               crossed random intercepts for any list of grouping factors (building and sampling
                            cell), Laplace approximation of the marginal likelihood (as lme4 with nAGQ = 1).

Each fit returns beta, the Wald standard error of beta1 from the numerical Hessian of the negative log-likelihood
(variance components at the boundary are held fixed), the likelihood-ratio p-value for beta1 = 0, and the
random-effect variances. beta1 is bounded to [-25, 25]; |beta1| > 15 or a standard error above 20 means
quasi-complete separation (the odds ratio is not estimable); it is flagged, and only the likelihood-ratio test,
which stays defined as the bound of the likelihood, is reported for it.
"""
import math
import numpy as np
from scipy import optimize, special

BOUND_B1 = 25.0
LOGSIG_MIN, LOGSIG_MAX = math.log(1e-4), math.log(20.0)
ZG = np.linspace(-8, 8, 1601)
LWZ = -0.5 * ZG ** 2 - 0.5 * math.log(2 * math.pi) + math.log(ZG[1] - ZG[0])   # log(phi(z) dz)
LWZ_T = LWZ.copy()
LWZ_T[[0, -1]] += math.log(0.5)                                                  # trapezoid end weights
ZB = np.linspace(-8, 8, 401)                     # building grid of the two-level model
LWB = -0.5 * ZB ** 2 - 0.5 * math.log(2 * math.pi) + math.log(ZB[1] - ZB[0])
LWB[[0, -1]] += math.log(0.5)
ZU = np.linspace(-8, 8, 401)                     # task grid of the two-level model
LWU = -0.5 * ZU ** 2 - 0.5 * math.log(2 * math.pi) + math.log(ZU[1] - ZU[0])
LWU[[0, -1]] += math.log(0.5)


def _logp(eta, y):
    """log P(y | eta) for Bernoulli y, numerically stable."""
    return -np.logaddexp(0.0, -eta) if y == 1 else -np.logaddexp(0.0, eta)


# ---------------------------------------------------------------- building random intercept, quadrature
def _bld_suff(y, arm, grp):
    G = sorted(set(grp))
    gi = {g: i for i, g in enumerate(G)}
    S = np.zeros((len(G), 4))       # successes arm1, trials arm1, successes arm0, trials arm0
    for yy, aa, gg in zip(y, arm, grp):
        j = gi[gg]
        if aa == 1:
            S[j, 0] += yy; S[j, 1] += 1
        else:
            S[j, 2] += yy; S[j, 3] += 1
    return S


def _nll_bld(par, S, b1_fixed=None):
    b0, b1, ls = (par[0], par[1], par[2]) if b1_fixed is None else (par[0], b1_fixed, par[1])
    s = math.exp(ls)
    e1 = b0 + b1 + s * ZG
    e0 = b0 + s * ZG
    l1p, l1n = -np.logaddexp(0, -e1), -np.logaddexp(0, e1)
    l0p, l0n = -np.logaddexp(0, -e0), -np.logaddexp(0, e0)
    ll = (S[:, [0]] * l1p + (S[:, [1]] - S[:, [0]]) * l1n + S[:, [2]] * l0p + (S[:, [3]] - S[:, [2]]) * l0n)
    return -float(special.logsumexp(ll + LWZ_T, axis=1).sum())


# ---------------------------------------------------------------- building + task random intercepts, quadrature
def _pair_suff(ya, yb, grp):
    G = sorted(set(grp))
    gi = {g: i for i, g in enumerate(G)}
    P = np.zeros((len(G), 4))        # pattern counts: (1,1), (1,0), (0,1), (0,0) for (A, B)
    for a, b, g in zip(ya, yb, grp):
        P[gi[g], {(1, 1): 0, (1, 0): 1, (0, 1): 2, (0, 0): 3}[(int(a), int(b))]] += 1
    return P


def _nll_bt(par, P, b1_fixed=None):
    if b1_fixed is None:
        b0, b1, lsb, lsu = par
    else:
        b0, lsb, lsu = par
        b1 = b1_fixed
    sb, su = math.exp(lsb), math.exp(lsu)
    base = b0 + sb * ZB[:, None] + su * ZU[None, :]          # building grid x task grid
    eA, eB = base + b1, base
    lApos, lAneg = -np.logaddexp(0, -eA), -np.logaddexp(0, eA)
    lBpos, lBneg = -np.logaddexp(0, -eB), -np.logaddexp(0, eB)
    # log g_pattern(building value) = log sum_u w(u) P(pattern | b, u)
    lg = np.stack([special.logsumexp(x + LWU[None, :], axis=1) for x in
                   (lApos + lBpos, lApos + lBneg, lAneg + lBpos, lAneg + lBneg)], axis=1)   # (len(ZB), 4)
    ll = P @ lg.T                                                # (groups, len(ZB))
    return -float(special.logsumexp(ll + LWB[None, :], axis=1).sum())


# ---------------------------------------------------------------- crossed random intercepts, Laplace
class _Laplace:
    def __init__(self, y, arm, factors):
        # aggregate identical (arm, levels) rows into binomial counts
        key = {}
        for yy, aa, *lv in zip(y, arm, *factors):
            k = (aa,) + tuple(lv)
            s, n = key.get(k, (0, 0))
            key[k] = (s + yy, n + 1)
        ks = list(key)
        self.s = np.array([key[k][0] for k in ks], float)
        self.n = np.array([key[k][1] for k in ks], float)
        self.x = np.array([k[0] for k in ks], float)
        self.levels = []
        cols = []
        for f in range(len(factors)):
            L = sorted({k[1 + f] for k in ks})
            li = {l: i for i, l in enumerate(L)}
            self.levels.append(len(L))
            Zf = np.zeros((len(ks), len(L)))
            for r, k in enumerate(ks):
                Zf[r, li[k[1 + f]]] = 1
            cols.append(Zf)
        self.Z = np.hstack(cols)
        self.v0 = np.zeros(self.Z.shape[1])

    def nll(self, b0, b1, logsig):
        lam = np.concatenate([np.full(m, math.exp(ls)) for m, ls in zip(self.levels, logsig)])
        ZL = self.Z * lam[None, :]
        fixed = b0 + b1 * self.x
        v = self.v0.copy()
        for _ in range(100):
            eta = fixed + ZL @ v
            mu = special.expit(eta)
            g = ZL.T @ (self.s - self.n * mu) - v
            H = ZL.T @ (ZL * (self.n * mu * (1 - mu))[:, None]) + np.eye(len(v))
            step = np.linalg.solve(H, g)
            # damped Newton on the concave penalized log-likelihood
            t, f0 = 1.0, self._h(fixed, ZL, v)
            while t > 1e-6 and self._h(fixed, ZL, v + t * step) < f0 - 1e-12:
                t /= 2
            v = v + t * step
            if np.max(np.abs(t * step)) < 1e-10:
                break
        self.v0 = v
        eta = fixed + ZL @ v
        mu = special.expit(eta)
        H = ZL.T @ (ZL * (self.n * mu * (1 - mu))[:, None]) + np.eye(len(v))
        sign, logdet = np.linalg.slogdet(H)
        return -(self._h(fixed, ZL, v) - 0.5 * logdet)

    def _h(self, fixed, ZL, v):
        eta = fixed + ZL @ v
        return float(np.sum(self.s * -np.logaddexp(0, -eta) + (self.n - self.s) * -np.logaddexp(0, eta)) - 0.5 * v @ v)


# ---------------------------------------------------------------- generic optimizer and Hessian
def _minimize(fun, x0, bounds, polish=4000):
    best = None
    for start in x0:
        r = optimize.minimize(fun, start, method='L-BFGS-B', bounds=bounds, options={'maxiter': 2000, 'ftol': 1e-13, 'gtol': 1e-9})
        if best is None or r.fun < best.fun:
            best = r
    # polish
    r = optimize.minimize(fun, best.x, method='Nelder-Mead', options={'xatol': 1e-8, 'fatol': 1e-11, 'maxiter': polish})
    x = np.clip(r.x, [b[0] for b in bounds], [b[1] for b in bounds])
    fx = fun(x)
    return (x, fx) if fx <= best.fun else (best.x, best.fun)


def _hessian(fun, x, h=1e-4):
    k = len(x)
    H = np.zeros((k, k))
    f0 = fun(x)
    for i in range(k):
        for j in range(i, k):
            ei, ej = np.zeros(k), np.zeros(k)
            ei[i], ej[j] = h, h
            if i == j:
                H[i, i] = (fun(x + ei) - 2 * f0 + fun(x - ei)) / h ** 2
            else:
                H[i, j] = H[j, i] = (fun(x + ei + ej) - fun(x + ei - ej) - fun(x - ei + ej) + fun(x - ei - ej)) / (4 * h * h)
    return H


def _summarize(name, x, fx, fx0, fun, n_sig, sig_names, nobs, ngroups):
    """x = (b0, b1, logsig...). Standard error of b1 from the Hessian, boundary variance components held fixed."""
    from scipy import stats
    free = [0, 1] + [2 + i for i in range(n_sig) if LOGSIG_MIN + 0.05 < x[2 + i] < LOGSIG_MAX - 0.05]
    H = _hessian(fun, x)
    Hf = H[np.ix_(free, free)]
    se = math.nan
    try:
        cov = np.linalg.inv(Hf)
        if cov[1, 1] > 0:
            se = math.sqrt(cov[1, 1])
    except np.linalg.LinAlgError:
        pass
    b1 = float(x[1])
    # quasi-complete separation: beta1 runs off to the bound, or the curvature in beta1 vanishes
    sep = abs(b1) > 15.0 or not math.isfinite(se) or se > 20.0
    lr = max(0.0, 2 * (fx0 - fx))
    out = {'model': name, 'beta0': float(x[0]), 'beta1': b1, 'se_beta1': se,
           'odds_ratio': math.exp(b1) if not sep else (math.inf if b1 > 0 else 0.0),
           'or_lo': math.exp(b1 - 1.959964 * se) if (math.isfinite(se) and not sep) else math.nan,
           'or_hi': math.exp(b1 + 1.959964 * se) if (math.isfinite(se) and not sep) else math.nan,
           'wald_p': float(2 * stats.norm.sf(abs(b1 / se))) if (math.isfinite(se) and se > 0 and not sep) else math.nan,
           'lr_stat': lr, 'lr_p': float(stats.chi2.sf(lr, 1)),
           'loglik': -fx, 'loglik_null': -fx0, 'separation': bool(sep), 'n_obs': nobs, 'n_groups': ngroups,
           'boundary_variance': [sig_names[i] for i in range(n_sig) if 2 + i not in free]}
    for i, nm in enumerate(sig_names):
        out[f'var_{nm}'] = math.exp(2 * x[2 + i])
    return out


def fit_building_quadrature(ya, yb, grp):
    y = np.concatenate([ya, yb]).astype(int)
    arm = np.concatenate([np.ones(len(ya)), np.zeros(len(yb))]).astype(int)
    S = _bld_suff(y, arm, list(grp) + list(grp))
    bnd = [(-30, 30), (-BOUND_B1, BOUND_B1), (LOGSIG_MIN, LOGSIG_MAX)]
    p1, p0 = np.clip(np.mean(ya), .01, .99), np.clip(np.mean(yb), .01, .99)
    st = [np.array([special.logit(p0), special.logit(p1) - special.logit(p0), ls]) for ls in (math.log(0.3), math.log(1.5))]
    fun = lambda p: _nll_bld(p, S)
    x, fx = _minimize(fun, st, bnd)
    fun0 = lambda p: _nll_bld(p, S, b1_fixed=0.0)
    x0, fx0 = _minimize(fun0, [np.array([x[0], x[2]]), np.array([special.logit((p1 + p0) / 2), math.log(0.5)])], [bnd[0], bnd[2]])
    return _summarize('building random intercept (ML, quadrature)', x, fx, fx0, fun, 1, ['building'], len(y), {'building': S.shape[0]})


def fit_building_task(ya, yb, grp):
    P = _pair_suff(ya, yb, grp)
    bnd = [(-30, 30), (-BOUND_B1, BOUND_B1), (LOGSIG_MIN, LOGSIG_MAX), (LOGSIG_MIN, LOGSIG_MAX)]
    p1, p0 = np.clip(np.mean(ya), .01, .99), np.clip(np.mean(yb), .01, .99)
    st = [np.array([special.logit(p0), special.logit(p1) - special.logit(p0), math.log(0.5), lu]) for lu in (math.log(1.0), math.log(4.0))]
    fun = lambda p: _nll_bt(p, P)
    x, fx = _minimize(fun, st, bnd, polish=600)
    fun0 = lambda p: _nll_bt(p, P, b1_fixed=0.0)
    x0, fx0 = _minimize(fun0, [np.array([x[0], x[2], x[3]]), np.array([special.logit((p1 + p0) / 2), math.log(0.5), math.log(3.0)])],
                        [bnd[0], bnd[2], bnd[3]], polish=600)
    return _summarize('building and task random intercepts (ML, quadrature)', x, fx, fx0, fun, 2, ['building', 'task'],
                      2 * len(ya), {'building': P.shape[0], 'task': len(ya)})


def fit_laplace(ya, yb, factors, names, label):
    y = np.concatenate([ya, yb]).astype(int)
    arm = np.concatenate([np.ones(len(ya)), np.zeros(len(yb))]).astype(int)
    facs = [list(f) + list(f) for f in factors]
    M = _Laplace(y, arm, facs)
    k = len(factors)
    bnd = [(-30, 30), (-BOUND_B1, BOUND_B1)] + [(LOGSIG_MIN, LOGSIG_MAX)] * k
    p1, p0 = np.clip(np.mean(ya), .01, .99), np.clip(np.mean(yb), .01, .99)
    st = [np.array([special.logit(p0), special.logit(p1) - special.logit(p0)] + [ls] * k) for ls in (math.log(0.3), math.log(1.5))]
    fun = lambda p: M.nll(p[0], p[1], p[2:])
    x, fx = _minimize(fun, st, bnd)
    fun0 = lambda p: M.nll(p[0], 0.0, p[1:])
    x0, fx0 = _minimize(fun0, [np.concatenate([[x[0]], x[2:]]), np.array([special.logit((p1 + p0) / 2)] + [math.log(0.5)] * k)],
                        [bnd[0]] + bnd[2:])
    return _summarize(label, x, fx, fx0, fun, k, names, len(y), {n: m for n, m in zip(names, M.levels)})
