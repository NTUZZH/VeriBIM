"""Cost of an edit on the 108-task subset: (a) mean wall-clock seconds per task, with the mean tool rounds
in an aligned column, and (b) the mean price per task at the providers' list prices (hosted_cost.py
formula); VeriBIM-9B runs locally and has no price per call. Rows as in Fig. 8 variant A.
    python make_fig_cost.py ../../tables/exhibit_data.json [--outdir DIR] [--preview]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from exhibit_style import *   # noqa: F401,F403
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
data, outdir, preview = load(sys.argv)
outdir = outdir or HERE
COM = data['commercial']
order = sorted(COM, key=lambda c: -(arm(data, 108, c[0], 'lib') or {'comp': [0]})['comp'][0])
rows = [(arm(data, 108, 'ours'), OURS, 0.0, data['ours_label'])]
y, ticks, labels = 0.0, [0.0], [data['ours_label']]
ys = [0.0]
y += 0.75
for mid, mlabel, _ in order:
    for k, (a, st) in enumerate((('lib', LIB), ('alone', ALONE))):
        rows.append((arm(data, 108, mid, a), st, y + 0.4 * k, mlabel))
    ticks.append(y + 0.2); labels.append(mlabel)
    y += 0.4 + 0.75
ymax = y - 0.75 + 0.4 + 0.35
fig, (a1, a2) = plt.subplots(1, 2, figsize=(WIDTH_MM * MM, 80 * MM), sharey=True,
                             gridspec_kw={'width_ratios': [1.25, 1.0], 'wspace': 0.1})
fig.subplots_adjust(left=0.165, right=0.985, top=0.93 if not preview else 0.9, bottom=0.25)
h = 0.36
secmax = max(r[0]['secs'] for r in rows if r[0]) if any(r[0] for r in rows) else 1
cmax = max(100 * r[0].get('usd_task', 0) for r in rows if r[0])
xr = secmax * 1.22
for a, st, yy, _ in rows:
    if not a:
        a1.text(secmax * 0.01, yy, 'pending', va='center', ha='left', style='italic', fontsize=7.5)
        a2.text(cmax * 0.01, yy, 'pending', va='center', ha='left', style='italic', fontsize=7.5)
        continue
    a1.barh(yy, a['secs'], height=h, color=st[0], edgecolor=st[1], lw=0.6, hatch=st[2], zorder=2)
    a1.text(xr * 0.985, yy, f"{a['rounds']:.1f}", va='center', ha='right', fontsize=7.5)
    cents = 100 * a.get('usd_task', 0.0)
    if 'usd_task' in a:
        a2.barh(yy, cents, height=h, color=st[0], edgecolor=st[1], lw=0.6, hatch=st[2], zorder=2)
    else:
        a2.text(cmax * 0.01, yy, 'no price per call (local)', va='center', ha='left', style='italic', fontsize=7.5)
a1.text(xr * 0.985, -0.62, 'Rounds', va='center', ha='right', fontsize=7.5, fontweight='bold')
a1.set_xlim(0, xr)
a2.set_xlim(0, cmax * 1.08)
a1.set_ylim(ymax, -0.8)
a1.set_yticks(ticks, labels)
for ax in (a1, a2):
    ax.tick_params(axis='y', length=0)
    ax.spines['left'].set_visible(False)
    ax.grid(axis='x', color='#D9D9D9', lw=0.4, zorder=0)
a1.set_xlabel('Wall-clock seconds per task')
a2.set_xlabel('Price per task at list price (US cents)')
for ax, tag in ((a1, '(a)'), (a2, '(b)')):
    ax.text(0.0, 1.0, tag, transform=ax.transAxes, ha='left', va='bottom', fontsize=8, fontweight='bold')
hs = [plt.Rectangle((0, 0), 1, 1, fc=s[0], ec=s[1], lw=0.6, hatch=s[2]) for s in (OURS, LIB, ALONE)]
boxed_legend(fig, handles=hs, labels=['VeriBIM-9B, with the library', 'Commercial model, with the library',
                                      'Commercial model, alone'], loc='lower center', ncol=3, bbox_to_anchor=(0.5, 0.0))
if preview:
    preview_mark(fig)
save(fig, outdir, 'fig_cost' + ('_preview' if preview else ''))
