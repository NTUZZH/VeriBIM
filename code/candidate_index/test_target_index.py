#!/usr/bin/env python
"""Unit tests: python -m unittest test_target_index (run from this folder, CPU only)."""
import json, os, re, unittest
import index_ifc, match, apply_hint, eval_recall

BENCH = os.path.join(index_ifc.P, 'tasks/benchmark/tasks.v4d.jsonl')
RAW = [l.rstrip('\n') for l in open(BENCH) if l.strip()]
TASKS = [json.loads(l) for l in RAW]
# the element a create task must find, by edit kind (written out independently of required_guids)
CREATE_KEY = {'replace_filling': 'replaced_guid', 'create_filling': 'host_guid',
              'copy_element': 'source_guid', 'array_elements': 'source_guid', 'create_box': 'storey_guid',
              'create_wall_with_door': 'storey_guid'}


def sample(op, n=10):
    return sorted((t for t in TASKS if t['operation'] == op and t['edit_kind'] != 'clarify'), key=lambda t: t['task_id'])[:n]


class RequiredGuids(unittest.TestCase):
    def check_exists(self, t, guids):
        idx = index_ifc.load(t['input_ifc'])
        known = {e['g'] for e in idx['elements']} | set(idx['storeys'])
        for g in guids:
            self.assertIn(g, known, t['task_id'])

    def test_delete_update(self):
        for op in ('delete', 'update'):
            for t in sample(op):
                req = eval_recall.required_guids(t)
                self.assertEqual(req, t['target']['guids'], t['task_id'])
                self.assertTrue(req and set(req) <= set(t['edit_guids']['target']), t['task_id'])
                self.check_exists(t, req)

    def test_create(self):
        pool = sorted((t for t in TASKS if t['operation'] == 'create' and t['edit_kind'] in CREATE_KEY), key=lambda t: t['task_id'])
        first = {}
        for t in pool:
            first.setdefault(t['edit_kind'], t)
        picked = list(first.values()) + [t for t in pool if t not in first.values()][:10 - len(first)]
        self.assertEqual(len(picked), 10)
        self.assertEqual({t['edit_kind'] for t in picked}, set(CREATE_KEY))
        for t in picked:
            req = eval_recall.required_guids(t)
            self.assertEqual(req, [t['edit_params'][CREATE_KEY[t['edit_kind']]]], t['task_id'])
            self.check_exists(t, req)

    def test_clarify_has_none(self):
        clar = [t for t in TASKS if t['edit_kind'] == 'clarify'][:10]
        self.assertTrue(all(eval_recall.required_guids(t) == [] for t in clar if t['operation'] != 'create' or not
                            any((t.get('edit_params') or {}).get(k) for k in ('replaced_guid', 'source_guid', 'host_guid', 'storey_guid'))))


class Index(unittest.TestCase):
    def test_schemas(self):
        files = {'IFC2X3': 'data/corpus/gni/IFC-models/2026_BIMprojects/model_7_structure.ifc',
                 'IFC4': 'data/corpus/gni/IFC-models/2026_BIMprojects/model_8_structure.ifc',
                 'IFC4X3': 'runs_local/corpus_v10/migrator_v2/files/G8structure__IFC4X3.ifc'}
        for schema, path in files.items():
            idx = index_ifc.load(path)
            self.assertEqual(idx['schema'], schema)
            self.assertGreater(len(idx['elements']), 100)
            self.assertTrue(all(e['c'] not in ('IfcBuildingStorey', 'IfcSite', 'IfcBuilding') for e in idx['elements']))
            geo = [e for e in idx['elements'] if e['lo']]
            self.assertGreater(len(geo), 0.9 * len(idx['elements']))
            self.assertTrue(all(e['sec'] in ('north', 'east', 'south', 'west') for e in geo if e['sg']))

    def test_tool_number(self):
        self.assertEqual(index_ifc.tool_number('Basic Wall:Generic - 200mm:819562'), '819562')
        self.assertIsNone(index_ifc.tool_number('Room 12'))


class Matcher(unittest.TestCase):
    def setUp(self):
        self.t = sample('delete')[0]
        self.idx = index_ifc.load(self.t['input_ifc'])

    def test_guid_first_and_deterministic(self):
        g = sorted(e['g'] for e in self.idx['elements'])[5]
        r1 = match.rank(self.idx, f'Delete the element {g} from the model.')
        r2 = match.rank(self.idx, f'Delete the element {g} from the model.')
        self.assertEqual(r1[0][1], g)
        self.assertEqual([x[1] for x in r1], [x[1] for x in r2])
        for (s1, g1, _), (s2, g2, _) in zip(r1, r1[1:]):
            self.assertTrue(s1 > s2 or (s1 == s2 and g1 < g2))

    def test_no_match(self):
        app, listed = apply_hint.hint(self.idx, 'Please make the model nicer.')
        self.assertEqual(listed, [])
        self.assertTrue(app.endswith('\n- (no candidate matched)'))


class Apply(unittest.TestCase):
    LINE = re.compile(r"^- [0-9A-Za-z_$]{22} \| Ifc\w+ \| name '.*' \| storey '.*' \| room '.*' \| (north|east|south|west|unknown) side \| "
                      r"(\d+\.\d\d|\?) x (\d+\.\d\d|\?) x (\d+\.\d\d|\?) m$")

    def test_fields_and_format(self):
        for raw, rec in list(zip(RAW, TASKS))[::105]:
            app, listed = apply_hint.hint(index_ifc.load(rec['input_ifc']), apply_hint.request_text(rec))
            self.assertTrue(app.startswith(apply_hint.HEAD))
            self.assertLess(len(app), 1200)
            body = app[len(apply_hint.HEAD):].split('\n')
            self.assertLessEqual(len(body), 10)
            for l in body:
                self.assertTrue(self.LINE.match(l) or l == apply_hint.NONE, l)
            out = apply_hint.rewrite_line(raw, rec, app)
            new = json.loads(out)
            self.assertEqual(new['task_id'], rec['task_id'])
            for k in rec:
                if k in ('prompt', 'instruction'):
                    self.assertEqual(new[k], rec[k] + app)
                else:
                    self.assertEqual(new[k], rec[k])
            strip = lambda s, r: re.sub(r'"(prompt|instruction)": "(?:[^"\\]|\\.)*"', '', s)
            self.assertEqual(strip(out, new), strip(raw, rec))  # every other byte unchanged


if __name__ == '__main__':
    unittest.main()
