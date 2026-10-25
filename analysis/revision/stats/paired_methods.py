"""Tests and confidence intervals for a difference between two paired proportions.

Notation of the paired 2 x 2 table (A and B are two arms read on the same tasks):
    n11 = tasks both arms complete, n12 = tasks A completes and B fails (b),
    n21 = tasks B completes and A fails (c), n22 = tasks both fail, N = n11 + n12 + n21 + n22.
The difference is delta = p1 - p2 = (n12 - n21) / N, with p1 = (n11 + n12) / N and p2 = (n11 + n21) / N.

Methods (references in report.md):
  mcnemar_exact      exact conditional McNemar test, two-sided: min(1, 2 P(X <= min(b, c))), X ~ Bin(b + c, 1/2)
  mcnemar_midp       mid-p version: exact p minus P(X = min(b, c))   (Lancaster 1961; Fagerland et al. 2013)
  mcnemar_asymptotic chi-square statistic (b - c)^2 / (b + c), 1 df, no continuity correction
  newcombe           Newcombe (1998) method 10: square-and-add of Wilson score limits with the phi correction
  tango              Tango (1998) asymptotic score interval (inverts the score test of delta = delta0)
  bonett_price       Bonett and Price (2012) Wald interval with Laplace adjustment
  exact_conditional  Clopper-Pearson interval for pi = b / (b + c), conditional on b + c, mapped to the paired
                     odds ratio pi / (1 - pi) and to the difference (b + c) / N * (2 pi - 1) (b + c held fixed)
  midp_conditional   the same with mid-p tail probabilities
"""
import math
import numpy as np
from scipy import stats, optimize

Z95 = stats.norm.ppf(0.975)


# ---------------------------------------------------------------- tests
def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return float(min(1.0, 2.0 * stats.binom.cdf(min(b, c), n, 0.5)))


def mcnemar_midp(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return float(min(1.0, 2.0 * stats.binom.cdf(k, n, 0.5) - stats.binom.pmf(k, n, 0.5)))


def mcnemar_asymptotic(b, c):
    if b + c == 0:
        return 1.0
    return float(stats.chi2.sf((b - c) ** 2 / (b + c), 1))


# ---------------------------------------------------------------- intervals
def wilson(x, n, z=Z95):
    if n == 0:
        return 0.0, 1.0
    p = x / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def newcombe(n11, n12, n21, n22, z=Z95):
    N = n11 + n12 + n21 + n22
    p1, p2 = (n11 + n12) / N, (n11 + n21) / N
    d = p1 - p2
    l1, u1 = wilson(n11 + n12, N, z)
    l2, u2 = wilson(n11 + n21, N, z)
    den = (n11 + n12) * (n21 + n22) * (n11 + n21) * (n12 + n22)
    phi = (n11 * n22 - n12 * n21) / math.sqrt(den) if den > 0 else 0.0
    lo = d - math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    hi = d + math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return max(-1.0, lo), min(1.0, hi)


def tango_z(n12, n21, N, d0):
    """Score statistic of H0: delta = d0, with the closed-form constrained MLE of p21 (Tango 1998)."""
    A = 2.0 * N
    B = -n12 - n21 + (2.0 * N - n12 + n21) * d0
    C = -n21 * d0 * (1.0 - d0)
    p21 = (math.sqrt(max(0.0, B * B - 4 * A * C)) - B) / (2 * A)
    var = N * (2 * p21 + d0 * (1 - d0))
    if var <= 0:
        return math.copysign(math.inf, (n12 - n21 - N * d0)) if (n12 - n21 - N * d0) != 0 else 0.0
    return (n12 - n21 - N * d0) / math.sqrt(var)


def tango(n11, n12, n21, n22, z=Z95):
    N = n11 + n12 + n21 + n22
    d = (n12 - n21) / N
    eps = 1e-10
    f_lo = lambda d0: tango_z(n12, n21, N, d0) - z
    f_hi = lambda d0: tango_z(n12, n21, N, d0) + z
    lo = -1.0 if f_lo(-1 + eps) < 0 else optimize.brentq(f_lo, -1 + eps, d, xtol=1e-12)
    hi = 1.0 if f_hi(1 - eps) > 0 else optimize.brentq(f_hi, d, 1 - eps, xtol=1e-12)
    return lo, hi


def tango_bruteforce_z(n12, n21, N, d0):
    """Same statistic with the constrained MLE found numerically (used only as a check of the closed form)."""
    n_conc = N - n12 - n21
    lo_b, hi_b = max(0.0, -d0) + 1e-12, (1 - d0) / 2 - 1e-12
    if hi_b <= lo_b:
        return tango_z(n12, n21, N, d0)

    def nll(p21):
        p12 = p21 + d0
        pc = 1 - p12 - p21
        return -(n12 * math.log(max(p12, 1e-300)) + n21 * math.log(max(p21, 1e-300)) + n_conc * math.log(max(pc, 1e-300)))
    r = optimize.minimize_scalar(nll, bounds=(lo_b, hi_b), method='bounded', options={'xatol': 1e-13})
    p21 = r.x
    return (n12 - n21 - N * d0) / math.sqrt(N * (2 * p21 + d0 * (1 - d0)))


def bonett_price(n11, n12, n21, n22, z=Z95):
    N = n11 + n12 + n21 + n22
    p12, p21 = (n12 + 1) / (N + 2), (n21 + 1) / (N + 2)
    d = p12 - p21
    se = math.sqrt((p12 + p21 - d * d) / (N + 2))
    return max(-1.0, d - z * se), min(1.0, d + z * se)


def clopper_pearson(x, n, alpha=0.05):
    lo = 0.0 if x == 0 else float(stats.beta.ppf(alpha / 2, x, n - x + 1))
    hi = 1.0 if x == n else float(stats.beta.ppf(1 - alpha / 2, x + 1, n - x))
    return lo, hi


def midp_binomial_interval(x, n, alpha=0.05):
    """Mid-p interval for a binomial proportion: P(X > x) + P(X = x)/2 = alpha/2 (lower), P(X < x) + P(X = x)/2 = alpha/2 (upper)."""
    def upper_tail(p):
        return stats.binom.sf(x, n, p) + 0.5 * stats.binom.pmf(x, n, p)

    def lower_tail(p):
        return stats.binom.cdf(x - 1, n, p) + 0.5 * stats.binom.pmf(x, n, p)
    eps = 1e-12
    lo = 0.0 if x == 0 else optimize.brentq(lambda p: upper_tail(p) - alpha / 2, eps, 1 - eps, xtol=1e-14)
    hi = 1.0 if x == n else optimize.brentq(lambda p: lower_tail(p) - alpha / 2, eps, 1 - eps, xtol=1e-14)
    return lo, hi


def conditional_intervals(n12, n21, N, alpha=0.05, mid=False):
    """Interval for pi = n12 / (n12 + n21) given n12 + n21, mapped to the paired odds ratio and to the difference."""
    nd = n12 + n21
    if nd == 0:
        return {'pi': (math.nan, math.nan), 'odds_ratio': (0.0, math.inf), 'diff': (0.0, 0.0)}
    lo, hi = (midp_binomial_interval if mid else clopper_pearson)(n12, nd, alpha)
    orr = (lo / (1 - lo) if lo < 1 else math.inf, hi / (1 - hi) if hi < 1 else math.inf)
    return {'pi': (lo, hi), 'odds_ratio': orr, 'diff': (nd / N * (2 * lo - 1), nd / N * (2 * hi - 1))}


def table(ya, yb):
    ya, yb = np.asarray(ya, int), np.asarray(yb, int)
    n11 = int(((ya == 1) & (yb == 1)).sum())
    n12 = int(((ya == 1) & (yb == 0)).sum())
    n21 = int(((ya == 0) & (yb == 1)).sum())
    n22 = int(((ya == 0) & (yb == 0)).sum())
    return n11, n12, n21, n22


def all_methods(n11, n12, n21, n22, alpha=0.05):
    z = stats.norm.ppf(1 - alpha / 2)
    N = n11 + n12 + n21 + n22
    out = {'N': N, 'diff': (n12 - n21) / N,
           'mcnemar_exact_p': mcnemar_exact(n12, n21), 'mcnemar_midp_p': mcnemar_midp(n12, n21),
           'mcnemar_asymptotic_p': mcnemar_asymptotic(n12, n21),
           'newcombe': newcombe(n11, n12, n21, n22, z), 'tango': tango(n11, n12, n21, n22, z),
           'bonett_price': bonett_price(n11, n12, n21, n22, z)}
    ce = conditional_intervals(n12, n21, N, alpha, mid=False)
    cm = conditional_intervals(n12, n21, N, alpha, mid=True)
    out['exact_conditional_diff'], out['exact_conditional_or'] = ce['diff'], ce['odds_ratio']
    out['midp_conditional_diff'], out['midp_conditional_or'] = cm['diff'], cm['odds_ratio']
    out['odds_ratio'] = (n12 / n21) if n21 > 0 else math.inf
    return out


# ---------------------------------------------------------------- self-checks
def self_check(seed=20261015, reps=4000):
    """(1) closed-form Tango statistic equals the numerically constrained one; (2) the exact p is dual to the
    Clopper-Pearson interval (pi interval excludes 1/2 iff p < 0.05) on every table with b + c <= 30; (3) coverage
    of each 95 % interval in two simulated settings of the 108-task size. Returns a dict for the report."""
    res = {}
    worst = 0.0
    for (n12, n21, N) in [(1, 3, 108), (0, 4, 300), (15, 2, 108), (13, 3, 2100), (0, 0, 108), (36, 0, 108), (3, 1, 108)]:
        for d0 in np.linspace(-0.9, 0.9, 37):
            if abs(d0) < 1e-9:
                continue
            a, bb = tango_z(n12, n21, N, d0), tango_bruteforce_z(n12, n21, N, d0)
            if math.isfinite(a) and math.isfinite(bb):
                worst = max(worst, abs(a - bb))
    res['tango_closed_form_vs_numeric_max_abs_diff'] = worst
    dual_bad = 0
    for nd in range(1, 31):
        for b in range(nd + 1):
            p = mcnemar_exact(b, nd - b)
            lo, hi = clopper_pearson(b, nd)
            if (p < 0.05) != (lo > 0.5 or hi < 0.5):
                dual_bad += 1
    res['exact_p_vs_clopper_pearson_disagreements_bplusc_le_30'] = dual_bad
    rng = np.random.default_rng(seed)
    cov = {}
    for name, (p12, p21, N) in {'N108_p12_0.01_p21_0.03': (0.01, 0.03, 108),
                                'N108_p12_0.10_p21_0.02': (0.10, 0.02, 108),
                                'N300_p12_0.01_p21_0.00': (0.01, 0.0, 300)}.items():
        true = p12 - p21
        hits = {k: 0 for k in ('newcombe', 'tango', 'bonett_price', 'exact_conditional_diff')}
        draws = rng.multinomial(N, [p12, p21, 1 - p12 - p21], size=reps)
        for n12, n21, nc in draws:
            m = all_methods(int(nc), int(n12), int(n21), 0)
            for k in hits:
                lo, hi = m[k]
                hits[k] += (lo - 1e-12 <= true <= hi + 1e-12)
        cov[name] = {k: v / reps for k, v in hits.items()}
    res['coverage_95'] = cov
    res['coverage_reps'] = reps
    return res


if __name__ == '__main__':
    import json
    print(json.dumps(self_check(), indent=1))
    print(all_methods(103, 1, 3, 1))
