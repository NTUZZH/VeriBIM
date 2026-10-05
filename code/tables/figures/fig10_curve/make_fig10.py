"""Fig. 10, the two later training stages on the hard validation set (300 tasks).
(a) Preference stage: completion of each snapshot dpo_v10_cN at step N, the chosen snapshot (the final model) marked.
(b) Reinforcement stage (not adopted): completion of each snapshot grpo_v10_cN at step N, starting at step 0 from the
chosen preference snapshot, the highest snapshot marked. Both panels share the y axis and show the imitation model as
a dashed line. Until the hard-validation curve exists the script draws the saturated 500-task validation curve into
fig10_curve_provisional_val500.* with an in-figure provisional mark (one panel).
    python make_fig10.py ../../tables/exhibit_data.json [--outdir DIR]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from exhibit_style import *   # noqa: F401,F403
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
data, outdir, preview = load(sys.argv)
outdir = outdir or HERE
c = data['curve']
prov = c['provisional']
g = data.get('grpo_curve') if not prov else None
snaps = c['snaps']
PREF = dict(color=REF_LINE, lw=1.0, marker='o', ms=3.6, mfc=OURS[0], mec=REF_LINE, mew=0.7, zorder=3)
RL_EDGE, RL_FILL = '#B85C66', '#F2CACA'
RL = dict(color=RL_EDGE, lw=1.0, marker='s', ms=3.4, mfc=RL_FILL, mec=RL_EDGE, mew=0.7, zorder=3)
IMIT = dict(color='#7F7F7F', lw=0.8, ls=(0, (4, 2)), zorder=2)
RING = dict(ms=8.5, mfc='none', mec='#1A1A1A', mew=0.9, ls='none', zorder=4)

if prov or not g:
    # one panel: the preference stage only (provisional val-500 drawing, or no reinforcement curve yet)
    steps = [s[0] for s in snaps]
    comp = [s[2] for s in snaps]
    fig, ax = plt.subplots(figsize=(WIDTH_MM * MM, 62 * MM))
    fig.subplots_adjust(left=0.085, right=0.99, top=0.9 if prov else 0.95, bottom=0.17)
    ax.plot(steps, comp, label='Preference-stage snapshot', **PREF)
    if c['chosen']:
        ch = [s for s in snaps if s[1] == c['chosen']][0]
        ax.plot(ch[0], ch[2], marker='o', label='Chosen snapshot', **RING)
    if c['baseline']:
        ax.axhline(c['baseline'][0], label='Imitation model', **IMIT)
    vals = comp + ([c['baseline'][0]] if c['baseline'] else [])
    ax.set_ylim(min(0.90, np.floor((min(vals) - 0.02) * 50) / 50), 1.0)
    ax.set_xticks(steps)
    ax.set_xlim(0, max(steps) + 1)
    ax.set_xlabel('Preference-training step')
    n = snaps[0][4] if snaps else 0
    ax.set_ylabel('Completion, hard validation set' if not prov else f'Completion, {n}-task validation set')
    ax.grid(axis='y', color='#D9D9D9', lw=0.4, zorder=0)
    boxed_legend(ax, loc='lower right')
    if prov:
        fig.text(0.005, 0.995, 'Provisional: drawn from the saturated 500-task validation curve until the hard-validation '
                 'curve exists; not for the manuscript.', ha='left', va='top', fontsize=7, style='italic')
    save(fig, outdir, 'fig10_curve_provisional_val500' if prov else 'fig10_curve')
    sys.exit(0)

# two panels: preference stage | reinforcement stage, shared y axis
gs_ = g['snaps']
pmax = max(s[0] for s in snaps)
gmax = max(s[0] for s in gs_)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(WIDTH_MM * MM, 68 * MM), sharey=True,
                             gridspec_kw={'width_ratios': [pmax + 2, 0.55 * (min(gmax, 60) + 6)], 'wspace': 0.08})
fig.subplots_adjust(left=0.08, right=0.99, top=0.78, bottom=0.16)
base = c['baseline'][0] if c['baseline'] else None
# (a) preference stage, step 0 = the imitation model
final_rl = bool(data.get('final_is_grpo'))
PLAIN = dict(marker='D', ms=5.2, mfc='none', mec='#1A1A1A', mew=0.8, ls='none', zorder=4)
xs = [0] + [s[0] for s in snaps]
ys = ([base] if base is not None else [np.nan]) + [s[2] for s in snaps]
a1.plot(xs, ys, **PREF)
ch = [s for s in snaps if s[1] == c['chosen']]
if ch:
    a1.plot(ch[0][0], ch[0][2], **(PLAIN if final_rl else dict(marker='o', **RING)))
# (b) reinforcement stage, step 0 = the chosen preference snapshot; one line per run (leg)
start = g['start'][0] if g.get('start') else (ch[0][2] if ch else np.nan)
legs = {}
for sn in gs_:
    legs.setdefault(sn[5] if len(sn) > 5 else 'grpo', []).append(sn)
legs = sorted(legs.values(), key=lambda l: l[0][0])
LEG_LS = ['-', (0, (3, 1.5))]
LEG_MFC = [RL_FILL, 'white']
yr, xr = [start], [0]
for i, leg in enumerate(legs):
    prev_pts = [p for l in legs[:i] for p in l if p[0] < leg[0][0]]
    x0, y0 = (max(prev_pts)[0], max(prev_pts)[2]) if prev_pts else (0, start)
    lx, ly = [x0] + [p[0] for p in leg], [y0] + [p[2] for p in leg]
    a2.plot(lx, ly, **dict(RL, ls=LEG_LS[i % 2], mfc=LEG_MFC[i % 2]))
    xr += [p[0] for p in leg]
    yr += [p[2] for p in leg]
fin = [p for p in gs_ if p[1] == data.get('final')] if final_rl else []
pk = max(gs_, key=lambda s: (s[2], s[3] if s[3] == s[3] else 0))
if g.get('peak'):
    pk = next((p for p in gs_ if p[1] == g['peak']), pk)
if fin:
    a2.plot(fin[0][0], fin[0][2], marker='o', **RING)
if not fin or pk[1] != fin[0][1]:
    a2.plot(pk[0], pk[2], marker='s', **RING)
a2.plot(0, start, marker='o', ms=3.6, mfc=OURS[0], mec=REF_LINE, mew=0.7, ls='none', zorder=5)
a2.plot(0, start, **(PLAIN if final_rl else dict(marker='o', **RING)))
for ax in (a1, a2):
    if base is not None:
        ax.axhline(base, **IMIT)
    ax.grid(axis='y', color='#D9D9D9', lw=0.4, zorder=0)
vals = [v for v in ys + yr if v == v]
lo = np.floor((min(vals) - 0.03) * 50) / 50      # a wide band: the stages move the hard set by a few tasks only
hi = min(1.0, np.ceil((max(vals) + 0.03) * 50) / 50)
a1.set_ylim(lo, hi)
a1.set_yticks(np.round(np.arange(lo, hi + 1e-9, 0.02), 2))
a1.set_xlim(-0.8, pmax + 1)
a1.set_xticks(xs)
a2.set_xlim(-0.04 * gmax - 1, gmax * 1.04 + 1)
a2.set_xticks(sorted(set(xr)) if gmax <= 60 else list(range(0, int(gmax) + 1, 20)))
a2.tick_params(axis='y', length=0)
a1.set_xlabel('Preference-training step')
a2.set_xlabel('Reinforcement-training step')
a1.set_ylabel('Completion, hard validation set')
for ax, tag in ((a1, '(a)'), (a2, '(b)')):
    ax.text(0.0, 1.03, tag, transform=ax.transAxes, ha='left', va='bottom', fontsize=8, fontweight='bold')
L = plt.Line2D
handles, labels = [L([], [], **PREF)], ['Preference-stage snapshot']
if final_rl:
    handles.append(L([], [], **PLAIN)); labels.append('Preference-stage peak')
for i in range(len(legs)):
    handles.append(L([], [], **dict(RL, ls=LEG_LS[i % 2], mfc=LEG_MFC[i % 2])))
    labels.append('Reinforcement snapshot' + ('' if len(legs) == 1 else (', first run' if i == 0 else ', second run'))
                  + ('' if final_rl else ' (not adopted)'))
handles.append(L([], [], marker='o', **RING)); labels.append('Chosen snapshot (VeriBIM-9B)')
if not fin or pk[1] != fin[0][1]:
    handles.append(L([], [], marker='s', **RING)); labels.append('Highest reinforcement snapshot')
handles.append(L([], [], **IMIT)); labels.append('Imitation model')
boxed_legend(fig, handles=handles, labels=labels, loc='upper center', ncol=3, bbox_to_anchor=(0.5, 0.995))
save(fig, outdir, 'fig10_curve')
