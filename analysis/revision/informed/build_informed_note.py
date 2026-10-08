"""Assemble the note for the 'informed' commercial arm: the existing library note, the full
documentation of every public helper function, the task conventions, and three reference trajectories from
the imitation data as worked examples. Output: note_informed.md next to this script."""
import gzip, json, inspect, os, re, sys, random
ROOT='.'; HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT+'/code/harness/modifc_harness')
import veribim_geom as g
base=open(ROOT+'/runs_local/bench_v4/geom_prompt_note_frontier.md').read().rstrip()
parts=[base, "", "## Full reference of the helper library (signature and documentation of every function)", ""]
names=[n for n,o in inspect.getmembers(g, inspect.isfunction) if not n.startswith('_') and o.__module__=='veribim_geom']
for n in names:
    o=getattr(g,n); sig=str(inspect.signature(o)).replace("'", "")
    doc=inspect.getdoc(o) or ''
    parts.append(f"### geom.{n}{sig}"); parts.append(doc); parts.append("")
parts += ["## Conventions used by the instructions", "",
"- Positions 'along the wall from its start point' are measured along the wall's own x axis from the start of its body (geom.wall_box(wall)['start']), in metres, to the near edge of the door or window leaf; 'centred at' positions name the middle of the leaf (use along_is_centre=True).",
"- A sill height is measured above the base of the host wall. Widths and heights size the leaf.",
"- Directions such as +X, -Y, north or east are world axes of the building (+Y is north); 'in that storey's own coordinates' means the storey's placement frame (frame='storey'), a bare coordinate means the world frame.",
"- 'The wall opposite W across the space S' is the element bounding S that runs parallel to W (|cos| of the angle at least 0.9) and stands on the far side of the room's centre; among several, the one facing W over the longest stretch, then the one nearest the room's centre. geom.find_opposite applies this rule.",
"- Every length in an instruction is in metres whatever unit the file uses; the helper functions convert.",
"- Names are matched exactly against Name (and LongName for spaces). A GlobalId identifies one element.",
"- If the instruction leaves out a value or a reference the edit needs (which element, which size, which distance), do not edit and do not commit; reply with a question that names the missing value. This overrides the sentence about sensible defaults in the system message.",
"- Create exactly the requested element with the requested relationships (containment in the storey, the opening for a door or window, the type if named), change nothing else, and call commit() once when the edit is complete.",
"", "## Three worked examples (reference dialogues on other buildings)", ""]
pick=json.load(open(HERE+'/example_trajectories.json'))
order=['create_filling_opposite','translate','underspecified']
def clean(s): return re.sub(r"IFC model path: \S+", "IFC model path: <path to the working copy>", s or '')
for i,k in enumerate(order,1):
    r=pick[k]
    parts.append(f"### Example {i}")
    for m in r['messages'][1:]:
        role=m['role']; c=clean(m.get('content'))
        if role=='user': parts.append("User:\n"+c)
        elif role=='assistant':
            if c.strip(): parts.append("Assistant: "+c.strip())
            for t in m.get('tool_calls') or []:
                code=t['function']['arguments']['code'] if isinstance(t['function']['arguments'],dict) else json.loads(t['function']['arguments'])['code']
                parts.append("Assistant tool call execute_ifc_code:\n```python\n"+code.rstrip()+"\n```")
        elif role=='tool': parts.append("Tool result:\n```\n"+c.rstrip()[:1500]+"\n```")
    parts.append("")
text="\n".join(parts)
assert '/home/' not in text, 'local path leaked'
open(HERE+'/note_informed.md','w').write(text)
print('chars',len(text),'approx tokens',len(text)//4, 'functions',len(names))
