"""Build the obstruction AABB index, once, for in-scope sources no generator cache holds."""
import json, glob, os, sys, time, resource
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clearance_check as cc
srcs = set()
for f in glob.glob(os.path.dirname(os.path.abspath(__file__)) + '/inscope_*.jsonl'):
    for l in open(f):
        srcs.add(json.loads(l)['input_ifc'])
miss = [s for s in srcs if not any(os.path.exists(os.path.join(d, cc.cache_key(cc.ROOT + s) + '.npz'))
                                   for d in cc.INDEX_DIRS + [cc.OWN_CACHE])]
print(len(srcs), 'sources;', len(miss), 'without an index', flush=True)
for s in sorted(miss, key=lambda s: os.path.getsize(cc.ROOT + s)):
    t = time.time()
    idx = cc.source_index(cc.ROOT + s)
    print(f'{time.time() - t:6.1f}s {len(idx["guid"]):6d} elements  rss {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB  {s}', flush=True)
