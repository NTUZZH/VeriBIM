"""Fig. 9, the training chain on the 2,100-task benchmark: completion per IFC version and pooled for the
untrained model with the library note (an estimate from its partial read; a
missing version keeps an empty slot), imitation, + preferences and + reinforcement, with 95 % bootstrap
intervals over tasks. A stage whose read is missing keeps its slot and is marked 'pending' in the legend.
    python make_fig09.py ../../tables/exhibit_data.json [--outdir DIR]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from exhibit_style import *   # noqa: F401,F403
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
data, outdir, preview = load(sys.argv)
outdir = outdir or HERE
GROUPS = ['ALL', 'IFC2X3', 'IFC4', 'IFC4X3']
GLABEL = {'ALL': 'All versions', 'IFC2X3': 'IFC2X3', 'IFC4': 'IFC4', 'IFC4X3': 'IFC4X3'}
STAGES = [('base', 'Qwen3.5-9B, untrained'), ('sft', 'Imitation'),
          ('dpo', '+ preferences'), ('grpo', data.get('grpo_label', '+ reinforcement (not adopted)'))]

fig, ax = plt.subplots(figsize=(WIDTH_MM * MM, 70 * MM))
fig.subplots_adjust(left=0.075, right=0.99, top=0.83, bottom=0.1)
xs = np.arange(len(GROUPS))
w = 0.19
offs = (np.arange(len(STAGES)) - 1.5) * w
hs, ls = [], []
for j, (key, label) in enumerate(STAGES):
    a = arm(data, 2100, key)
    fill, edge, hatch = STAGE_STYLE[key]
    for i, g in enumerate(GROUPS):
        v = (a or {}).get('comp' if g == 'ALL' else g)
        if not v:
            continue
        m, lo, hi = v[:3]
        ax.bar(xs[i] + offs[j], m, w * 0.92, color=fill, edgecolor=edge, lw=0.6, hatch=hatch, zorder=2)
        ax.errorbar(xs[i] + offs[j], m, yerr=[[m - lo], [hi - m]], fmt='none', zorder=3, **ERR)
    hs.append(plt.Rectangle((0, 0), 1, 1, fc=fill, ec=edge, lw=0.6, hatch=hatch))
    est = bool(a and a.get('estimate'))
    ls.append(label + (' (estimate)' if est else '' if a else ' (pending)'))
ax.set_xticks(xs, [GLABEL[g] for g in GROUPS])
ax.tick_params(axis='x', length=0)
ax.set_xlim(-0.5, len(GROUPS) - 0.5)
ax.set_ylim(0, 1.04)
ax.set_yticks(np.linspace(0, 1, 6))
ax.set_ylabel('Completion on the 2,100-task benchmark')
ax.grid(axis='y', color='#D9D9D9', lw=0.4, zorder=0)
ax.axvline(0.5, color='#BFBFBF', lw=0.5, zorder=0)
boxed_legend(fig, handles=hs, labels=ls, loc='upper center', ncol=4, bbox_to_anchor=(0.5, 0.995))
save(fig, outdir, 'fig09_ablation')
