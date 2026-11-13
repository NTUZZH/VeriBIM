#!/usr/bin/env python
"""apply_hint.py <tasks.jsonl> <out.jsonl> [--k 10] [--max-chars 1200]

Writes a copy of the task file in which the instruction text gets a list of at most K candidate elements from the
deterministic index (index_ifc.py) ranked by match.py. The appendix goes onto every instruction-bearing field the
record has ('prompt', which the harness reads, and 'instruction'); the request text that is matched is 'instruction'
when present, else 'prompt'. Every other byte of each line is left unchanged: the field value is replaced in place
inside the original JSON line, and the result is parsed back and compared field by field.
Length rule, fixed before any recall was measured: Name, storey and room values are shortened to 32, 16 and 20
characters (head, an ellipsis, and the tail that carries the authoring-tool number), and when the appendix would still
reach max-chars, the lowest-ranked lines are dropped until it is shorter."""
import json, sys
import index_ifc, match

HEAD = ("\n\nCandidate elements from a deterministic index of this model (the request's words matched these; "
        "verify in the file before editing):\n")
NONE = "- (no candidate matched)"


def short(s, n):
    s = match.norm(s)
    if len(s) <= n:
        return s
    tail = n // 2
    return s[:n - tail - 1] + '…' + s[-tail:]


def room_label(e, by_g):
    def label(g):
        s = by_g.get(g)
        return ' '.join(x for x in dict.fromkeys([s['n'], s['ln']]) if x) if s else g
    if e['c'] == 'IfcSpace':
        return label(e['g']) or 'none'
    names = [label(g) for g in (e['rooms'] or e['adj'])]
    return ' / '.join(names) if names else 'none'


def line(e, by_g):
    if e['lo']:
        dx, dy, dz = (abs(h - l) for h, l in zip(e['hi'], e['lo']))
        size = f"{max(dx, dy):.2f} x {min(dx, dy):.2f} x {dz:.2f} m"
    else:
        size = "? x ? x ? m"
    return (f"- {e['g']} | {e['c']} | name '{short(e['n'], 32)}' | storey '{short(e['st'], 16)}' | "
            f"room '{short(room_label(e, by_g), 20)}' | {e['sec'] or 'unknown'} side | {size}")


def hint(idx, text, k=10, max_chars=1200, ranked=None):
    """The appendix string and the GlobalIds it lists, in rank order."""
    by_g = {e['g']: e for e in idx['elements']}
    ranked = (ranked if ranked is not None else match.rank(idx, text))[:k]
    lines = [line(e, by_g) for _, _, e in ranked]
    while lines and len(HEAD + '\n'.join(lines)) >= max_chars:
        lines.pop()
    if not lines:
        return HEAD + NONE, []
    return HEAD + '\n'.join(lines), [g for _, g, _ in ranked[:len(lines)]]


def request_text(rec):
    return rec['instruction'] if rec.get('instruction') else rec['prompt']


def rewrite_line(raw, rec, appendix):
    """The original JSON line with the appendix added to each instruction field, other bytes untouched."""
    out = raw
    fields = [f for f in ('prompt', 'instruction') if isinstance(rec.get(f), str)]
    for f in fields:
        for ascii_ in (False, True):
            old = '"%s": %s' % (f, json.dumps(rec[f], ensure_ascii=ascii_))
            if out.count(old) == 1:
                out = out.replace(old, '"%s": %s' % (f, json.dumps(rec[f] + appendix, ensure_ascii=ascii_)))
                break
        else:
            raise SystemExit(f"cannot locate field {f} of {rec.get('task_id')} in its line")
    new = json.loads(out)
    assert set(new) == set(rec) and all(new[x] == rec[x] for x in rec if x not in fields)
    assert all(new[f] == rec[f] + appendix for f in fields)
    return out


def main(argv):
    args, k, mx = [], 10, 1200
    it = iter(argv)
    for a in it:
        if a == '--k':
            k = int(next(it))
        elif a == '--max-chars':
            mx = int(next(it))
        else:
            args.append(a)
    src, dst = args
    raws = [l.rstrip('\n') for l in open(src, encoding='utf-8') if l.strip()]
    out, lengths, differ = [], [], 0
    for raw in raws:
        rec = json.loads(raw)
        if isinstance(rec.get('prompt'), str) and isinstance(rec.get('instruction'), str) and rec['prompt'] != rec['instruction']:
            differ += 1
        app, guids = hint(index_ifc.load(rec['input_ifc']), request_text(rec), k, mx)
        assert len(app) < mx
        out.append(rewrite_line(raw, rec, app))
        lengths.append(len(app))
        print(f"{rec['task_id']}\t{len(app)} chars\t{len(guids)} lines")
    with open(dst, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')
    print(f"wrote {len(out)} tasks to {dst}; appendix length min {min(lengths)} max {max(lengths)} chars; "
          f"records whose prompt and instruction differ: {differ}", file=sys.stderr)


if __name__ == '__main__':
    main(sys.argv[1:])
