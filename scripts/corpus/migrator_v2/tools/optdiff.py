import ifcopenshell.ifcopenshell_wrapper as w, sys
a, b = sys.argv[1], sys.argv[2]
sa, sb = w.schema_by_name(a), w.schema_by_name(b)
for d in sb.entities():
    try: o = sa.declaration_by_name(d.name())
    except Exception: continue
    oa = {x.name(): x for x in o.all_attributes()}
    der = d.derived()
    out = []
    for i, x in enumerate(d.all_attributes()):
        if der[i] or x.name() not in oa: continue
        y = oa[x.name()]
        if y.optional() and not x.optional(): out.append((x.name(), 'opt->MAND'))
        ta, tb = str(y.type_of_attribute()), str(x.type_of_attribute())
        if ta != tb: out.append((x.name(), 'type', ta[:60], tb[:60]))
    if out: print(d.name(), out)
