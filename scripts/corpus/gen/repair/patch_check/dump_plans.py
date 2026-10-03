"""Plan create_filling and replace_filling on the test fixture for many seeds and dump them,
so the patched and unpatched planners can be compared draw for draw."""
import json, os, sys, tempfile, shutil, random
from modifc_gen import ops
from modifc_gen.tests import test_filling_type as t
t.WORK = tempfile.mkdtemp(prefix="plans_", dir=sys.argv[2])
os.environ["MODIFC_GEOM_CACHE"] = os.path.join(t.WORK, "geom_index")
fixture = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "fixture.ifc")
if not os.path.exists(fixture):
    model, _ = t.building_with_fillings()
    model.write(fixture)
from modifc_gen.scene import Scene
scene = Scene(fixture)
by_name = {e.Name: e.GlobalId for e in scene.model.by_type("IfcProduct")}
guids = {"bare_wall": by_name["Bare wall"], "window": by_name["Old window"], "door": by_name["Old door"]}
out = []
def plain(v):
    if isinstance(v, (list, tuple)): return [plain(x) for x in v]
    if isinstance(v, dict): return {k: plain(x) for k, x in v.items()}
    return v if isinstance(v, (str, int, float, bool, type(None))) else repr(v)
for seed in range(60):
    for family in ("door", "window"):
        rng = random.Random(seed)
        p = ops.plan_create_filling(scene, family, scene.by_guid(guids["bare_wall"]), f"T{seed}", rng)
        out.append({"seed": seed, "what": f"create_{family}", "plan": None if p is None else
                    {"params": plain(p.params), "args": plain([c.args for c in p.calls])},
                    "next_draw": rng.random()})
    for old in ("window", "door"):
        rng = random.Random(seed)
        p = ops.plan_replace(scene, scene.by_guid(guids[old]), rng, f"T{seed}")
        out.append({"seed": seed, "what": f"replace_{old}", "plan": None if p is None else
                    {"params": plain(p.params), "args": plain([c.args for c in p.calls])},
                    "next_draw": rng.random()})
json.dump(out, open(sys.argv[1], "w"))
shutil.rmtree(t.WORK, ignore_errors=True)
print(len(out), "plans dumped")
