"""List-price cost of the commercial-model runs reported in the paper, from the released per-task results.

The reported runs are the four commercial models on the 108-task subset, alone and with the library,
Claude Sonnet 5.5 on the 216 further tasks of the 324-task subset, alone and with the library, the documented
setting of five commercial models on the 108-task subset, and the documented setting of Claude Sonnet 5.5 on the
216 further tasks, 2,052 task runs in all. Each row is priced with the token counts it records and the list prices
of code/tables/hosted_cost.py, with cache writes at 1.25 times the input price and cache reads at the fraction of
the input price that CACHE_READ gives (0.1 unless listed). Writes spend_reported.json next to this script.

    python analysis/revision/spend/spend_reported.py
"""
import ast
import json
import os
import re

ROOT = os.environ.get('VERIBIM_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
RES = f'{ROOT}/results/benchmark'
MODELS = ('claude-sonnet-5-5', 'deepseek-v4-pro', 'gemini-3.8-flash', 'gpt-5.6-luna')
RUNS = [f'hosted108_{arm}_all/per_task_{m}.jsonl' for arm in ('alone', 'lib') for m in MODELS]
RUNS += [f'hosted216_{arm}_all/per_task_claude-sonnet-5-5.jsonl' for arm in ('alone', 'lib')]
RUNS += [f'hosted108_informed_all/per_task_{m}.jsonl' for m in MODELS + ('claude-opus-5-5',)]
RUNS += ['hosted324rest_informed_all/per_task_claude-sonnet-5-5.jsonl']

src = open(f'{ROOT}/code/tables/hosted_cost.py').read()
PRICE = ast.literal_eval(re.search(r'PRICE = (\{.*?\n\})', src, re.S).group(1))   # model -> (input, output) US$ per 1M
CACHE_READ = ast.literal_eval(re.search(r'CACHE_READ = (\{.*?\})', src).group(1))      # model -> cache-read fraction


def cost(row, p_in, p_out, c_frac):
    t_in, t_out = int(row.get('input_tokens') or 0), int(row.get('output_tokens') or 0)
    c_read, c_write = int(row.get('cache_read_tokens') or 0), int(row.get('cache_creation_tokens') or 0)
    return ((t_in - c_read - c_write) * p_in + c_read * p_in * c_frac + c_write * p_in * 1.25 + t_out * p_out) / 1e6


per_run, total, n = [], 0.0, 0
for rel in RUNS:
    model = os.path.basename(rel)[len('per_task_'):-len('.jsonl')]
    rows = [json.loads(l) for l in open(f'{RES}/{rel}') if l.strip()]
    usd = sum(cost(r, *PRICE[model], CACHE_READ.get(model, 0.1)) for r in rows)
    per_run.append({'file': f'results/benchmark/{rel}', 'model': model, 'task_runs': len(rows), 'usd': round(usd, 2)})
    total += usd
    n += len(rows)

out = {'task_runs': n, 'usd': round(total, 2), 'runs': per_run}
assert n == 2052, n
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spend_reported.json'), 'w'), indent=1)
print(f'{n:,} task runs, US$ {total:.2f}')
