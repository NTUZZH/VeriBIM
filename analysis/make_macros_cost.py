#!/usr/bin/env python3
"""Timing and cost macros of the proposed model, from the two timed runs on the 108-task subset.

  usage: make_macros_cost.py --solo PER_TASK.jsonl --sixteen PER_TASK.jsonl --log CHAIN.log
                             --markers DIR --out-tex OUT.tex --out-json OUT.json

Inputs: the per-task files of the run with one task at a time and of the run with 16 tasks in flight, the chain
log (it states for each timed run how many contention snapshots were taken and that all were clean), and the folder
in which the chain writes LATENCY_V14_CONTENDED_<tag> when a snapshot was contended. A contended run stops the script:
its seconds are not a timing. Constants (board power, tariff, exchange rate, workstation cost per year, list-price
fees of three Claude Sonnet 5.5 arms) are read from analysis/cost_constants.tex, each by name.

Electricity per completed edit = board power x mean seconds per task (one task at a time) / 3600 x tariff
/ completion of that run, the rule of the earlier cost macros (RevSgElecCents). Break-even edits per year =
workstation cost per year / (fee per completed edit - electricity per completed edit), rounded to thousands.
"""
import argparse, json, os, re, statistics as st, sys

ROOT = ''
FILES = ['analysis/cost_constants.tex']   # the seven constants, as the manuscript's macro files define them
DEF = re.compile(r'\\(?:re)?newcommand\{\\([A-Za-z]+)\}\{([^}]*)\}')


def die(msg):
    sys.exit('make_macros_cost.py: ' + msg)


def constants():
    M = {}
    for f in FILES:                      # later files redefine earlier ones, as in the manuscript
        for line in open(ROOT + f, encoding='utf-8'):
            m = DEF.match(line.strip())
            if m:
                M[m.group(1)] = m.group(2)
    def num(name):
        if name not in M:
            die(f'macro {name} not found')
        return float(M[name].replace(',', ''))
    return {k: num(k) for k in ('RevCardWatts', 'RevSgTariff', 'RevSgRate', 'RevSgAnnual', 'RevSgFeeSonnetList',
                                'RevSgFeeInfList', 'RevSgFeeAskSonnet')}


def rows_of(path, n=108):
    rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
    if len(rows) != n or len({r['task_id'] for r in rows}) != n:
        die(f'{path}: {len(rows)} rows, wanted {n} distinct tasks')
    if any(r.get('score') is None for r in rows):
        die(f'{path}: unscored rows')
    if any(r.get('duration_seconds') is None for r in rows):
        die(f'{path}: rows without duration_seconds')
    return rows


def done(r):
    sc = r['score']
    return all(sc.get(k) is not None and float(sc[k]) >= 0.9 for k in ('geometry', 'semantics', 'topology'))


def snapshots(log, phrase):
    hits = [l for l in open(log, encoding='utf-8') if phrase in l and 'snapshots during the read' in l]
    if len(hits) != 1:
        die(f'log: {len(hits)} snapshot lines for "{phrase}"')
    m = re.search(r': (\d+) snapshots during the read, all clean', hits[0])
    if not m:
        die(f'log: the run "{phrase}" was not clean: {hits[0].strip()}')
    return int(m.group(1))


def thousands(x):
    return f'{int(round(x / 1000.0)) * 1000:,}'


ap = argparse.ArgumentParser()
for a in ('--solo', '--sixteen', '--log', '--markers', '--out-tex', '--out-json'):
    ap.add_argument(a, required=True)
a = ap.parse_args()
for tag in ('solo', 'c16'):
    if os.path.exists(os.path.join(a.markers, f'LATENCY_V14_CONTENDED_{tag}')):
        die(f'marker LATENCY_V14_CONTENDED_{tag} exists: that run is not a timing')
C = constants()
solo, six = rows_of(a.solo), rows_of(a.sixteen)
if sorted(r['task_id'] for r in solo) != sorted(r['task_id'] for r in six):
    die('the two runs hold different tasks')
snap_solo = snapshots(a.log, 'one task at a time')
snap_six = snapshots(a.log, '16 in flight')
d_solo = [float(r['duration_seconds']) for r in solo]
d_six = [float(r['duration_seconds']) for r in six]
n = len(solo); done_solo = sum(map(done, solo)); comp = done_solo / n
secs = st.mean(d_solo)
wh = C['RevCardWatts'] * secs / 3600.0
sg_cents = wh / 1000.0 * C['RevSgTariff'] / comp          # Singapore cents per completed edit
us_cents = sg_cents / C['RevSgRate']
annual_cents = C['RevSgAnnual'] * 100.0
V = {
    'solo': {'n': n, 'completed': done_solo, 'completion': comp, 'seconds_mean': secs, 'seconds_median': st.median(d_solo),
             'seconds_max': max(d_solo), 'tool_rounds_mean': st.mean(float(r['tool_rounds']) for r in solo),
             'snapshots_clean': snap_solo},
    'sixteen': {'n': len(six), 'completed': sum(map(done, six)), 'seconds_mean': st.mean(d_six),
                'seconds_median': st.median(d_six), 'seconds_max': max(d_six), 'snapshots_clean': snap_six},
    'constants': C, 'energy_wh_per_task': wh, 'sg_cents_per_completed_edit': sg_cents,
    'us_cents_per_completed_edit': us_cents,
    'break_even_edits_per_year': {'note': annual_cents / (C['RevSgFeeSonnetList'] - sg_cents),
                                  'documented': annual_cents / (C['RevSgFeeInfList'] - sg_cents),
                                  'ask': annual_cents / (C['RevSgFeeAskSonnet'] - sg_cents)},
}
json.dump(V, open(a.out_json, 'w', encoding='utf-8'), indent=1)
L = ['% Generated by analysis/make_macros_cost.py from the two timed runs of the proposed model on the 108-task subset.']
def put(name, text):
    L.append(f'\\newcommand{{\\{name}}}{{{text}}}')
put('PmSoloN', n); put('PmSoloDone', done_solo); put('PmSoloComp', f'{comp:.3f}')
put('PmSoloSecs', f'{secs:.1f}'); put('PmSoloSecsMedian', f"{V['solo']['seconds_median']:.1f}")
put('PmSoloSecsMax', f"{V['solo']['seconds_max']:.0f}"); put('PmSoloRounds', f"{V['solo']['tool_rounds_mean']:.2f}")
put('PmSoloSnapshots', snap_solo)
put('PmSixteenInFlight', 16); put('PmSixteenSecs', f"{V['sixteen']['seconds_mean']:.1f}")
put('PmSixteenSecsMedian', f"{V['sixteen']['seconds_median']:.1f}"); put('PmSixteenSnapshots', snap_six)
put('PmEnergyWh', f'{wh:.1f}'); put('PmSgElecCents', f'{sg_cents:.2f}'); put('PmUsElecCents', f'{us_cents:.2f}')
put('PmSgBreakEvenNote', thousands(V['break_even_edits_per_year']['note']))
put('PmSgBreakEvenDoc', thousands(V['break_even_edits_per_year']['documented']))
put('PmSgBreakEvenAsk', thousands(V['break_even_edits_per_year']['ask']))
open(a.out_tex, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
print('\n'.join(L[1:]))
print(f'unrounded: seconds {secs:.3f}, Wh {wh:.4f}, Singapore cents {sg_cents:.5f}, US cents {us_cents:.5f}, '
      f"break-even {V['break_even_edits_per_year']}")
