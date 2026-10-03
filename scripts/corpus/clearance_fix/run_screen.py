"""Screen every in-scope task of the four sets with the clearance checker.

  python run_screen.py LANE     LANE in big, s0, s1
Tasks on sources above 60 MB go to lane big (one at a time), the rest are split
over s0 and s1 by source.  Each lane appends one JSON line per task to
results_<lane>.jsonl and skips task keys already there (resumable)."""
import json, os, sys, time, resource, zlib, traceback
import multiprocessing as mp
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SETS = ('bench_v4', 'val500', 'val100', 'pool')
BIG = 60e6


def lane_of(src_path):
    if os.path.getsize(src_path) > BIG:
        return 'big'
    return 's%d' % (zlib.crc32(src_path.encode()) % 2)


def work(item):
    import clearance_check as cc
    name, rec = item
    t = time.time()
    try:
        res = cc.check_task(rec)
        res['status'] = 'ok'
    except Exception as exc:
        res = {'task_id': rec['task_id'], 'status': 'error', 'error': repr(exc)[:300],
               'trace': traceback.format_exc()[-800:]}
    res.update(set=name, seconds=round(time.time() - t, 2),
               rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
    return res


def main():
    lane = sys.argv[1]
    import clearance_check as cc
    out = os.path.join(HERE, f'results_{lane}.jsonl')
    done = set()
    if os.path.exists(out):
        for l in open(out):
            r = json.loads(l)
            done.add((r['set'], r['task_id']))
    items = []
    for name in SETS:
        for l in open(os.path.join(HERE, f'inscope_{name}.jsonl')):
            r = json.loads(l)
            if (name, r['task_id']) in done:
                continue
            if lane_of(cc.ROOT + r['input_ifc']) == lane:
                items.append((name, r))
    items.sort(key=lambda x: x[1]['input_ifc'])
    print(lane, len(items), 'tasks to screen', flush=True)
    t0 = time.time()
    with mp.get_context('fork').Pool(1, maxtasksperchild=8) as pool, open(out, 'a') as f:
        for k, res in enumerate(pool.imap(work, items, chunksize=1), 1):
            f.write(json.dumps(res, default=str) + '\n'); f.flush()
            if k % 25 == 0:
                print(f'{lane} {k}/{len(items)} {time.time() - t0:.0f}s', flush=True)
    print(lane, 'done', f'{time.time() - t0:.0f}s', flush=True)


if __name__ == '__main__':
    main()
