import ifcopenshell.ifcopenshell_wrapper as w, json, os, sys
a, b = sys.argv[1], sys.argv[2]
sa, sb = w.schema_by_name(a), w.schema_by_name(b)
mp = {}
if (a, b) == ("IFC4", "IFC4X3_ADD2"):
    mp = json.load(open(os.path.join(os.path.dirname(w.__file__), 'util', 'attribute_4x3_to_4.json')))
else:
    mp = json.load(open(os.path.join(os.path.dirname(w.__file__), 'util', 'attribute_4_to_2x3.json')))
for d in sb.entities():
    try: o = sa.declaration_by_name(d.name())
    except Exception: continue
    na = [x.name() for x in o.all_attributes()]
    nb = [(x.name(), x.optional()) for x in d.all_attributes()]
    der = d.derived()
    miss = [(n, opt) for i, (n, opt) in enumerate(nb) if n not in na and not der[i]]
    if miss:
        m = mp.get(d.name(), {})
        print(d.name(), [(n, 'opt' if opt else 'MAND', m.get(n)) for n, opt in miss], 'old:', [n for n in na if n not in [x for x, _ in nb]])
