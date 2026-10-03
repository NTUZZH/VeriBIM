"""Validator wrapper with the exact settings and issue-key function of scripts/corpus/validate_schema.py
(ifcopenshell.validate.validate(f, logger, express_rules=False); key = Class.Attribute:last line of the message
template), but keeping every key (no top-10 truncation) and, on request, formatted samples per key."""
import re, logging, collections
import ifcopenshell, ifcopenshell.validate

class _H(logging.Handler):
    def __init__(s): super().__init__(); s.recs = []
    def emit(s, r): s.recs.append(r)

def key_of(r):
    a = r.args if isinstance(r.args, tuple) else ()
    ent = re.search(r"=(Ifc\w+)\(", str(a[0])) if a else None
    att = re.search(r"attribute (\w+)", str(a[-1])) if a else None
    return f"{ent.group(1) if ent else '?'}.{att.group(1) if att else '?'}:{r.msg.strip().splitlines()[-1][:40]}"

_n = [0]
def validate_keys(f, samples=0):
    """f: ifcopenshell.file. Returns (Counter of keys, {key: [formatted message, ...]})."""
    _n[0] += 1
    h = _H(); lg = logging.getLogger(f"vkeys{_n[0]}"); lg.handlers = [h]; lg.propagate = False; lg.setLevel(logging.DEBUG)
    ifcopenshell.validate.validate(f, lg, express_rules=False)
    kinds = collections.Counter(); smp = collections.defaultdict(list)
    for r in h.recs:
        k = key_of(r); kinds[k] += 1
        if samples and len(smp[k]) < samples:
            try: smp[k].append(r.getMessage()[:1500])
            except Exception as ex: smp[k].append(repr(r.msg)[:300])
    lg.handlers = []
    return kinds, dict(smp)
