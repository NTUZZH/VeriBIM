"""Page previews of the packets (A4, the margins and font sizes of build_packets.py), for checking by eye.

No office suite is installed on this machine, so the Word files cannot be converted to PDF here. This
script lays out the same content (heading, request box, views, text box, answer lines) with the same
widths and font sizes, reports the estimated page height of every page, and writes PNG previews.
Run: taskset -c 16-23 python preview_pages.py audit A01,A02 | rewrite R1-01,R3-07 | fit
"""
import json, os, sys, textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = ''
PREV = os.path.join(HERE, 'previews')
CM = 1 / 2.54
PT = 1 / 72 * 2.54          # cm per point
TEXT_W = 17.0
USABLE_H = 29.7 - 1.6 - 1.5
plt.rcParams['font.family'] = ['Liberation Serif', 'Noto Serif CJK SC']


def chars_per_line(size_pt, width_cm):
    return int(width_cm / (size_pt * PT * 0.47))      # mean Times glyph width is about 0.47 em


def line_h(size_pt):
    return size_pt * PT * 1.16


def img_h(path, width_cm=8.35):
    w, h = Image.open(path).size
    return width_cm * h / w


def layout(kind, label, recs, cases):
    """List of drawing items (kind, y_top_cm, payload) and the total height in cm."""
    items, y = [], 0.0

    def text(t, size, bold=False, width=TEXT_W, before=0.0, after=3.0, indent=0.0):
        nonlocal y
        y += before * PT
        n = chars_per_line(size, width - indent)
        for ln in (textwrap.wrap(t, n) or ['']):
            items.append(('text', y, (ln, size, bold, indent)))
            y += line_h(size)
        y += after * PT

    def box(label_, lines, size, bullets=False):
        nonlocal y
        top = y
        y += 0.12
        text(label_, 9, bold=True, width=TEXT_W - 0.4, after=1, indent=0.2)
        for ln in lines:
            text(('•  ' if bullets else '') + ln, size, width=TEXT_W - 0.4 - (0.35 if bullets else 0), after=1.5,
                 indent=0.2 + (0.35 if bullets else 0))
        y += 0.12
        items.append(('box', top, y - top))

    def view_rows(rd):
        nonlocal y
        rows = [('before_plan.png', 'after_plan.png')]
        if os.path.exists(os.path.join(rd, 'before_elev.png')) and os.path.exists(os.path.join(rd, 'after_elev.png')):
            rows.append(('before_elev.png', 'after_elev.png'))
        for a, b in rows:
            h = max(img_h(os.path.join(rd, a)), img_h(os.path.join(rd, b)))
            items.append(('img', y, (os.path.join(rd, a), 0.0)))
            items.append(('img', y, (os.path.join(rd, b), 8.5)))
            y += h + 0.05
    text(label, 14, bold=True, after=4)
    if kind == 'audit':
        c = cases[label]
        rd = os.path.join(HERE, 'renders_audit', label)
        v = json.load(open(os.path.join(rd, 'view.json')))
        box('Request', [recs[c['task_id']]['instruction']], 10.5)
        y += 4 * PT
        view_rows(rd)
        y += 4 * PT
        box('Differences between the BEFORE and AFTER model files', v['facts'], 9.5, bullets=True)
        text('Q1  Does the AFTER model carry out the request correctly?', 10, True, before=5, after=1)
        text('      □ yes        □ partly        □ no', 10.5, after=2)
        text('Q2  If not fully: what is wrong?', 10, True, before=4, after=1)
        text('_' * 88, 10.5, before=8, after=0)
        text('Q3  Would you accept this model into the project without further changes?', 10, True, before=6, after=1)
        text('      □ yes        □ no', 10.5, after=0)
    else:
        rd = os.path.join(HERE, 'renders', label)
        v = json.load(open(os.path.join(rd, 'view.json')))
        view_rows(rd)
        y += 5 * PT
        note = v['note'][0].upper() + v['note'][1:]
        box('What changed', [note], 10.5)
        text('Your request (one to three sentences):', 10, True, before=6, after=2)
        for _ in range(4):
            text('_' * 88, 10.5, before=9, after=0)
    return items, y


def draw(items, path):
    fig = plt.figure(figsize=(21 * CM, 29.7 * CM), dpi=110)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 21)
    ax.set_ylim(29.7, 0)
    ax.axis('off')
    x0, y0 = 2.0, 1.6
    ax.add_patch(Rectangle((x0, y0), TEXT_W, USABLE_H, fill=False, ec='#DDDDDD', lw=0.5, ls='--'))
    for kind, y, p in items:
        if kind == 'text':
            t, size, bold, ind = p
            ax.text(x0 + ind, y0 + y, t, fontsize=size, fontweight='bold' if bold else 'normal', va='top')
        elif kind == 'box':
            ax.add_patch(Rectangle((x0, y0 + y), TEXT_W, p, fc='#F2F4F6', ec='#404040', lw=0.6, zorder=-1))
        elif kind == 'img':
            f, dx = p
            im = Image.open(f)
            w = 8.35
            h = w * im.size[1] / im.size[0]
            ax.imshow(im, extent=(x0 + dx, x0 + dx + w, y0 + y + h, y0 + y), zorder=1)
    ax.set_xlim(0, 21)
    ax.set_ylim(29.7, 0)
    fig.savefig(path)
    plt.close(fig)


def main():
    kind = sys.argv[1]
    draw_ = json.load(open(os.path.join(HERE, 'draw.json')))
    cases = {c['label']: c for c in draw_['audit_cases']}
    want = {c['task_id'] for c in draw_['audit_cases']}
    recs = {}
    for line in open(ROOT + 'runs_local/bench_v4/tasks.v4c.jsonl'):
        import json as _j
        r = _j.loads(line)
        if r['task_id'] in want:
            recs[r['task_id']] = r
    os.makedirs(PREV, exist_ok=True)
    if kind == 'fit':
        out = {}
        for lab in sorted(cases):
            if os.path.exists(os.path.join(HERE, 'renders_audit', lab, 'view.json')):
                out[lab] = round(layout('audit', lab, recs, cases)[1], 1)
        for b, ids in enumerate(draw_['rewrite_blocks'], start=1):
            for i in range(len(ids)):
                lab = f'R{b}-{i + 1:02d}'
                if os.path.exists(os.path.join(HERE, 'renders', lab, 'view.json')):
                    out[lab] = round(layout('rewrite', lab, recs, cases)[1], 1)
        over = {k: v for k, v in out.items() if v > USABLE_H}
        print(json.dumps({'usable_cm': USABLE_H, 'n': len(out), 'max': max(out.values()) if out else None,
                          'over': over}, indent=1))
        json.dump(out, open(os.path.join(PREV, 'page_heights.json'), 'w'), indent=1)
        return
    for lab in sys.argv[2].split(','):
        items, h = layout(kind, lab, recs, cases)
        draw(items, os.path.join(PREV, f'{lab}.png'))
        print(lab, round(h, 1), 'cm of', USABLE_H)


if __name__ == '__main__':
    main()
