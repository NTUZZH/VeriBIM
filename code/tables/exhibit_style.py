"""Shared matplotlib style of the VeriBIM result figures (Figs. 8 to 10 and the cost figure).

Times metrics through Liberation Serif (TrueType, embedded as Type 42), black text, pale fills with
medium-depth edges from the manuscript palette (writing/figures/figure_palette.tex: cyan main colour,
blue-grey, pale rose, pale green and grey companions; no amber or yellow), boxed legends.
"""
import json, os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

FONT_DIR = '/usr/share/fonts/truetype/liberation'
for f in ('Regular', 'Bold', 'Italic', 'BoldItalic'):
    font_manager.fontManager.addfont(f'{FONT_DIR}/LiberationSerif-{f}.ttf')
plt.rcParams.update({
    'font.family': 'Liberation Serif', 'mathtext.fontset': 'custom', 'mathtext.rm': 'Liberation Serif',
    'mathtext.it': 'Liberation Serif:italic', 'mathtext.bf': 'Liberation Serif:bold',
    'font.size': 8, 'axes.labelsize': 8, 'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5, 'legend.fontsize': 7.5,
    'text.color': 'black', 'axes.labelcolor': 'black', 'xtick.color': 'black', 'ytick.color': 'black',
    'axes.edgecolor': '#1A1A1A', 'axes.linewidth': 0.6, 'axes.spines.top': False, 'axes.spines.right': False,
    'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'xtick.major.size': 3, 'ytick.major.size': 3,
    'hatch.linewidth': 0.5, 'hatch.color': '#555555', 'errorbar.capsize': 1.8,
    'pdf.fonttype': 42, 'ps.fonttype': 42, 'savefig.dpi': 300, 'figure.dpi': 150,
    'legend.frameon': True, 'legend.fancybox': False, 'legend.edgecolor': '#333333', 'legend.framealpha': 1.0,
    'legend.borderpad': 0.45, 'legend.handlelength': 1.6, 'legend.handleheight': 0.9, 'legend.columnspacing': 1.4,
    'legend.labelspacing': 0.35,
})
MM = 1 / 25.4
WIDTH_MM = 175.0

# fill, edge (medium depth), hatch
OURS = ('#9ED3D3', '#2E8B8B', '')
LIB = ('#C8D4E3', '#4F6D8F', '')
ALONE = ('#E6E6E6', '#7F7F7F', '////')
MODEL_STYLE = {                       # Fig. 8 variant B: one pale tint per commercial model plus a hatch
    'gpt-5.6-luna': ('#C8D4E3', '#4F6D8F', ''),
    'deepseek-v4-pro': ('#F2CACA', '#B85C66', '\\\\\\\\'),
    'claude-sonnet-5-5': ('#D3E7D3', '#5B8F5B', '////'),
    'gemini-3.8-flash': ('#E3E3E3', '#7F7F7F', '....'),
}
STAGE_STYLE = {                       # Fig. 9: lighter to deeper along the training chain
    'base': ('#E6E6E6', '#7F7F7F', '....'),
    'sft': ('#C8D4E3', '#4F6D8F', ''),
    'dpo': ('#9ED3D3', '#2E8B8B', ''),
    'grpo': ('#9ED3D3', '#2E8B8B', '////'),
}
REF_LINE = '#2E8B8B'
ERR = dict(ecolor='#1A1A1A', elinewidth=0.6, capsize=1.8, capthick=0.6)


def load(argv):
    path = argv[1]
    outdir = None
    preview = '--preview' in argv
    if '--outdir' in argv:
        outdir = argv[argv.index('--outdir') + 1]
    return json.load(open(path)), outdir, preview


def arm(data, *key):
    return data['arms'].get('|'.join(map(str, key)))


def boxed_legend(obj, **kw):
    leg = obj.legend(**kw)
    leg.get_frame().set_linewidth(0.5)
    return leg


def preview_mark(fig):
    fig.text(0.005, 0.995, 'Layout preview: local-model values taken from the 2,100-task read on the subset tasks; '
             'not for the manuscript.', ha='left', va='top', fontsize=7, style='italic')


def save(fig, outdir, stem):
    os.makedirs(outdir, exist_ok=True)
    fig.savefig(os.path.join(outdir, stem + '.pdf'))
    fig.savefig(os.path.join(outdir, stem + '.png'), dpi=300)
    plt.close(fig)
