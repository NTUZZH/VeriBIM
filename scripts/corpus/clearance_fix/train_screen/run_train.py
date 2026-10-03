"""Screen the training filling tasks: python run_train.py LANE (big, s0, s1)."""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import multiprocessing as mp
import run_screen as rs
import clearance_check as cc


def main():
    lane = sys.argv[1]
    out = os.path.join(HERE, f'results_train_{lane}.jsonl')
    done = set()
    if os.path.exists(out):
        done = {json.loads(l)['task_id'] for l in open(out)}
    items = []
    for l in open(os.path.join(HERE, 'inscope_train_todo.jsonl')):
        r = json.loads(l)
        if r['task_id'] not in done and rs.lane_of(cc.ROOT + r['input_ifc']) == lane:
            items.append(('train', r))
    items.sort(key=lambda x: x[1]['input_ifc'])
    print(lane, len(items), 'tasks', flush=True)
    t0 = time.time()
    with mp.get_context('fork').Pool(1, maxtasksperchild=8) as pool, open(out, 'a') as f:
        for k, res in enumerate(pool.imap(rs.work, items, chunksize=1), 1):
            f.write(json.dumps(res, default=str) + '\n'); f.flush()
            if k % 100 == 0:
                print(f'{lane} {k}/{len(items)} {time.time() - t0:.0f}s', flush=True)
    print(lane, 'done', f'{time.time() - t0:.0f}s', flush=True)


if __name__ == '__main__':
    main()
