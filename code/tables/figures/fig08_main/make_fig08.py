"""Fig. 8, main result, in two finished variants drawn from writing/tables/exhibit_data.json.

Variant A (fig08_main_A): one panel, completion on the 108-task subset per model and arm as horizontal
bars with 95 % bootstrap intervals, VeriBIM-9B on top and a dashed line at its completion.
Variant B (fig08_main_B): two panels sharing the completion axis, per-IFC-version bars on the 108-task
subset (a) and the 324-task subset (b); bars are the models with the library, white diamonds the same
model alone. A local-model slot without a dedicated read is labelled 'pending'.
    python make_fig08.py ../../tables/exhibit_data.json [--outdir DIR] [--preview]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from exhibit_style import *   # noqa: F401,F403
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
data, outdir, preview = load(sys.argv)
outdir = outdir or HERE
VERS = ['IFC2X3', 'IFC4', 'IFC4X3']
COM = data['commercial']
ours108 = arm(data, 108, 'ours')
order = sorted(COM, key=lambda c: -(arm(data, 108, c[0], 'lib') or {'comp': [0]})['comp'][0])


def draw_bar(ax, y, a, style, h, horizontal=True, x=None):
    fill, edge, hatch = style
    m, lo, hi = a['comp'] if x is None else a[x][:3]
    if horizontal:
        ax.barh(y, m, height=h, color=fill, edgecolor=edge, linewidth=0.6, hatch=hatch, zorder=2)
        ax.errorbar(m, y, xerr=[[m - lo], [hi - m]], fmt='none', zorder=3, **ERR)
    return m


# ------------------------------------------------------------------ variant A
def variant_a():
    fig, ax = plt.subplots(figsize=(WIDTH_MM * MM, 84 * MM))
    fig.subplots_adjust(left=0.19, right=0.985, top=0.83 if not preview else 0.80, bottom=0.12)
    h, ticks, labels, y = 0.36, [], [], 0.0
    if ours108:
        draw_bar(ax, y, ours108, OURS, h)
        ax.axvline(ours108['comp'][0], color=REF_LINE, lw=0.8, ls=(0, (4, 2)), zorder=1)
    else:
        ax.text(0.01, y, 'pending', va='center', ha='left', style='italic', fontsize=7.5)
    ticks.append(y); labels.append(data['ours_label'])
    y += 0.75
    for mid, mlabel, _ in order:
        for k, (a, st) in enumerate((('lib', LIB), ('alone', ALONE))):
            r = arm(data, 108, mid, a)
            if r:
                draw_bar(ax, y + k * 0.4, r, st, h)
        ticks.append(y + 0.2); labels.append(mlabel)
        y += 0.4 + 0.75
    ax.set_yticks(ticks, labels)
    ax.tick_params(axis='y', length=0)
    ax.set_ylim(y - 0.75 + 0.4 + 0.35, -0.45)
    ax.set_xlim(0, 1.0)
    ax.set_xticks(np.linspace(0, 1, 6))
    ax.set_xlabel('Completion on the 108-task subset')
    ax.grid(axis='x', color='#D9D9D9', lw=0.4, zorder=0)
    ax.spines['left'].set_visible(False)
    hs = [plt.Rectangle((0, 0), 1, 1, fc=s[0], ec=s[1], lw=0.6, hatch=s[2]) for s in (OURS, LIB, ALONE)]
    boxed_legend(fig, handles=hs + [plt.Line2D([], [], color=REF_LINE, lw=0.8, ls=(0, (4, 2)))],
                 labels=['VeriBIM-9B, with the library', 'Commercial model, with the library',
                         'Commercial model, alone', 'Completion of VeriBIM-9B'],
                 loc='upper center', ncol=2, bbox_to_anchor=(0.5, 0.995 if not preview else 0.96))
    if preview:
        preview_mark(fig)
    save(fig, outdir, 'fig08_main_A' + ('_preview' if preview else ''))


# ------------------------------------------------------------------ variant B
def grouped(ax, n, models, width):
    xs = np.arange(len(VERS))
    k = len(models) + 1
    offs = (np.arange(k) - (k - 1) / 2) * width
    o = arm(data, n, 'ours')
    for i, g in enumerate(VERS):
        if o:
            m, lo, hi = o[g][:3]
            ax.bar(xs[i] + offs[0], m, width * 0.92, color=OURS[0], edgecolor=OURS[1], lw=0.6, zorder=2)
            ax.errorbar(xs[i] + offs[0], m, yerr=[[m - lo], [hi - m]], fmt='none', zorder=3, **ERR)
        else:
            ax.text(xs[i] + offs[0], 0.02, 'pending', rotation=90, ha='center', va='bottom', style='italic', fontsize=7)
        for j, (mid, _, _) in enumerate(models, start=1):
            fill, edge, hatch = MODEL_STYLE[mid]
            r = arm(data, n, mid, 'lib')
            if r:
                m, lo, hi = r[g][:3]
                ax.bar(xs[i] + offs[j], m, width * 0.92, color=fill, edgecolor=edge, lw=0.6, hatch=hatch, zorder=2)
                ax.errorbar(xs[i] + offs[j], m, yerr=[[m - lo], [hi - m]], fmt='none', zorder=3, **ERR)
            r = arm(data, n, mid, 'alone')
            if r:
                ax.plot(xs[i] + offs[j], r[g][0], marker='D', ms=3.4, mfc='white', mec='#1A1A1A', mew=0.7,
                        ls='none', zorder=4)
    ax.set_xticks(xs, VERS)
    ax.tick_params(axis='x', length=0)
    ax.set_xlim(-0.5, len(VERS) - 0.5)
    ax.grid(axis='y', color='#D9D9D9', lw=0.4, zorder=0)


def variant_b():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(WIDTH_MM * MM, 76 * MM), sharey=True,
                                 gridspec_kw={'width_ratios': [2.3, 1.0], 'wspace': 0.08})
    fig.subplots_adjust(left=0.075, right=0.99, top=0.75 if not preview else 0.72, bottom=0.14)
    grouped(a1, 108, order, 0.16)
    grouped(a2, 324, [c for c in COM if c[0] == 'claude-sonnet-5-5'], 0.28)
    a1.set_ylim(0, 1.04)
    a1.set_yticks(np.linspace(0, 1, 6))
    a1.set_ylabel('Completion')
    a1.set_xlabel('IFC version, 108-task subset')
    a2.set_xlabel('IFC version, 324-task subset')
    for ax, tag in ((a1, '(a)'), (a2, '(b)')):
        ax.text(0.0, 1.03, tag, transform=ax.transAxes, ha='left', va='bottom', fontsize=8, fontweight='bold')
    hs = [plt.Rectangle((0, 0), 1, 1, fc=OURS[0], ec=OURS[1], lw=0.6)]
    ls = [data['ours_label']]
    for mid, mlabel, _ in order:
        s = MODEL_STYLE[mid]
        hs.append(plt.Rectangle((0, 0), 1, 1, fc=s[0], ec=s[1], lw=0.6, hatch=s[2]))
        ls.append(f'{mlabel}, with the library')
    hs.append(plt.Line2D([], [], marker='D', ms=3.4, mfc='white', mec='#1A1A1A', mew=0.7, ls='none'))
    ls.append('Same commercial model, alone')
    boxed_legend(fig, handles=hs, labels=ls, loc='upper center', ncol=3,
                 bbox_to_anchor=(0.5, 0.995 if not preview else 0.955))
    if preview:
        preview_mark(fig)
    save(fig, outdir, 'fig08_main_B' + ('_preview' if preview else ''))


variant_a()
variant_b()
