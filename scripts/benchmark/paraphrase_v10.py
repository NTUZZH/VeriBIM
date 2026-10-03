"""Paraphrase every training instruction of the v6 corpus with the locally served base model.
Same prompt and checks as the val-100 diagnostic; quotes normalised before the check; three attempts; the
original is kept where all attempts fail. Output: task_id -> paraphrase map + report."""
import json, re, sys, time, urllib.request, concurrent.futures as cf, collections
SRC, OUT, REP = sys.argv[1:4]
PROMPT = ("Rewrite the change request below the way a different person would phrase it in a short message to a BIM modeller. "
         "Rules: (1) It asks for exactly the same operation on exactly the same elements: a rename stays a rename, a move stays a move, a rotation stays a rotation, a copy stays a copy, a new element stays a new element. Never say delete, remove, get rid of, replace, instead, or new one unless the original request says so. "
         "(2) Every fact stays exactly: numbers with units, quoted names in single quotes, GlobalIds, Ifc class names, directions with their axis, storey names, and every spatial relation attached to the same element as in the original. Add nothing, drop nothing, invent no reason; if the request asks a question or leaves something open, keep it open. "
         "(3) Change the wording: a different opening, different phrasing of the same action, a different order of the parts, a natural human tone. Returning the text unchanged or nearly unchanged is a failure. "
         "(4) Output only the rewritten request, one paragraph, nothing else.\n\nRequest:\n")
# quoted names: an opening quote is not preceded by a letter (so "wall's" is not a quote) and the name has no newline
QUOTE = r"(?<![A-Za-z])'([^'\n]{1,120})'(?![A-Za-z])"
FACT = QUOTE + r"|\b\d+(?:\.\d+)?\b|\bIfc[A-Z][A-Za-z]+\b|\b[0-9A-Za-z_$]{22}\b"
# spans that must survive verbatim (case-insensitive): the noun an identifier or name is attached to, an offset
# relation with its reference, a dimension with its unit word; a 9B paraphraser otherwise re-attaches them
# attachments that must survive: the noun an identifier or name is attached to must sit within 60 characters before
# the identifier in the rewrite, an offset phrase must keep its number, direction and axis and be followed within 90
# characters by its reference; dimensions keep number and unit word together
ATTACH = re.compile(r"\b(\w+) (?:with GlobalId|named) ('[^'\n]+')")
OFFSET = re.compile(r"(\d+(?:\.\d+)? ?m (?:north|south|east|west|above|below) \([+-][XYZ]\)) (?:of|from) (?:the )?(\w+) (?:named|with GlobalId) ('[^'\n]+')")
DIM2 = re.compile(r"(\d+(?:\.\d+)?) ?(m|mm|cm) (wide|high|long|thick|deep|tall|along the wall)")
COORD = re.compile(r"\(-?\d+(?:\.\d+)?, -?\d+(?:\.\d+)?, -?\d+(?:\.\d+)?\) ?m")
def attachment_problems(orig, new):
    out = []
    for noun, key in ATTACH.findall(orig):
        if not re.search(r"\b" + re.escape(noun) + r"\b[^'\n]{0,60}" + re.escape(key), new, re.I): out.append('attach: %s %s' % (noun, key[:30]))
    for phrase, noun, key in OFFSET.findall(orig):
        m = re.search(re.escape(phrase) + r".{0,90}" + re.escape(key), new, re.I | re.S)
        if not m: out.append('offset: %s -> %s' % (phrase, key[:30]))
    for num, unit, word in DIM2.findall(orig):
        stem = {'wide': 'wid', 'high': 'h(?:igh|eight)', 'long': 'l(?:ong|ength)', 'thick': 'thick', 'deep': 'd(?:eep|epth)', 'tall': 'tall', 'along the wall': '(?:along|from (?:the |its )?start|start point|from the end)'}[word]
        q = re.escape(num) + r" ?" + unit
        if not (re.search(q + r".{0,30}" + stem, new, re.I | re.S) or re.search(stem + r".{0,30}" + q, new, re.I | re.S)):
            out.append('dim: %s %s %s' % (num, unit, word))
    for c in COORD.findall(orig):
        if c.lower() not in new.lower(): out.append('coord: ' + c)
    return out
PLACEHOLDER = re.compile(r"\[insert|\[reason|\[your|X{3}|\.\.\.\]|TBD|leave (?:the )?reason|reason open|get in touch|\(reason", re.I)
VERBS = {"delete": r"\b(?:delete|remove|removal|take out|taking out|get rid of|erase|drop|discard|demolish)\b", "replace": r"\b(?:replace|replacing|replacement|instead|new one|swap)\b", "copy": r"\b(?:cop(?:y|ies)|duplicate)\b", "move": r"\b(?:move|moving|shift|relocate|translate|offset by)\b", "rotate": r"\b(?:rotate|rotation|turn)\b", "rename": r"\b(?:rename|renaming|call it|named to|name it|new name)\b", "create": r"\b(?:add|insert|create|model a new|put in|place a new|new (?:wall|door|window|column|slab|space|element))\b"}
def verb_problems(orig, new):
    out = []
    for k, pat in VERBS.items():
        if re.search(pat, new, re.I) and not re.search(pat, orig, re.I): out.append("verb added: " + k)
        if k in ("copy", "move", "rotate", "rename", "delete") and re.search(pat, orig, re.I) and not re.search(pat, new, re.I): out.append("verb lost: " + k)
    return out
DIRW = r"\b(north|south|east|west|above|below|left|right|nearest|furthest|farthest|opposite|between|second|third|first|last|not|without|no|only)\b"
def norm(s): return s.replace('“', "'").replace('”', "'").replace('"', "'").replace('’', "'")
def facts(s):
    out = set(m.group(0) for m in re.finditer(FACT, s)); out |= set(w.lower() for w in re.findall(DIRW, s, re.I)); return out
def chat(text):
    body = {"model": "Qwen3.5-9B", "max_tokens": 500, "temperature": 0.6, "top_p": 0.9, "messages": [{"role": "user", "content": PROMPT + text}], "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request('http://127.0.0.1:8000/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=600) as r: return json.loads(r.read())['choices'][0]['message']['content'].strip()
def one(t):
    orig = t['instruction']; need = facts(orig); last = ['no answer']
    for attempt in range(3):
        try: new = norm(chat(orig))
        except Exception as e: time.sleep(3); last = [str(e)[:60]]; continue
        new = new.split('\n\n')[0].strip() if len(new) > 2 * len(orig) + 200 else new
        missing = [x for x in need if x not in new and x.lower() not in new.lower()]
        missing += attachment_problems(orig, new) + verb_problems(orig, new)
        if PLACEHOLDER.search(new): missing.append('placeholder')
        w0 = set(re.findall(r"[a-z]+", re.sub(FACT, " ", orig).lower())); w1 = set(re.findall(r"[a-z]+", re.sub(FACT, " ", new).lower()))
        overlap = len(w0 & w1) / max(1, len(w0)); same_open = orig.split()[:3] == new.split()[:3]
        extra_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", new)) - set(re.findall(r"\b\d+(?:\.\d+)?\b", orig))
        if not missing and not extra_nums and overlap < 0.8 and not same_open and len(new) < 3 * len(orig) + 100:
            return t['task_id'], new, attempt + 1, []
        last = missing or (['extra numbers %s' % sorted(extra_nums)] if extra_nums else ['overlap %.2f same_open %s len %d' % (overlap, same_open, len(new))])
    return t['task_id'], None, 3, last
tasks = [json.loads(l) for l in open(SRC)]
done = {}
try:
    for l in open(OUT): r = json.loads(l); done[r['task_id']] = r
except FileNotFoundError: pass
todo = [t for t in tasks if t['task_id'] not in done]
print('tasks', len(tasks), 'already done', len(done), 'to do', len(todo), flush=True)
fails = collections.Counter(); n = 0; t0 = time.time()
with open(OUT, 'a') as fh, cf.ThreadPoolExecutor(16) as ex:
    for tid, new, att, missing in ex.map(one, todo):
        fh.write(json.dumps({'task_id': tid, 'paraphrase': new, 'attempts': att, 'fail': missing}, ensure_ascii=False) + '\n'); fh.flush()
        n += 1
        if new is None: fails[missing[0][:20] if missing else '?'] += 1
        if n % 500 == 0: print(f'{n}/{len(todo)} {time.time()-t0:.0f}s fails {sum(fails.values())}', flush=True)
rows = [json.loads(l) for l in open(OUT)]
rep = {'tasks': len(tasks), 'paraphrased': sum(1 for r in rows if r['paraphrase']), 'kept_original': sum(1 for r in rows if not r['paraphrase']), 'fail_kinds': dict(fails), 'attempts': dict(collections.Counter(r['attempts'] for r in rows))}
json.dump(rep, open(REP, 'w'), indent=1); print(json.dumps(rep))
