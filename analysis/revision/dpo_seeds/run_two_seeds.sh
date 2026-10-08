#!/bin/bash
# run_two_seeds.sh: the two further seeds of the preference stage, unattended, in the GPU window.
#   MODE=full (default): run_seed.sh 20261007 dpo_v10_s2, then run_seed.sh 20261008 dpo_v10_s3, each end to end
#                        (training, snapshot choice, 2,100-task read).
#   MODE=cut           : phase 1 runs both seeds with BENCH=324 (training, snapshot choice, the 324-task subset);
#                        phase 2 runs the 2,100-task read of each seed in turn while the window allows
#                        (run_seed.sh skips a read whose estimate does not fit before the window end).
#   SELECT=val100 (default) | valhard | fixed:N is passed to run_seed.sh (see run_seed.sh).
#   START_AT="2026-10-07 23:00" (optional) waits until then before the first guard.
# Watchdog: every stage that run_seed.sh starts runs under common.sh's watched(): a stage whose progress files stay
# unchanged and whose process group uses < CPU_MIN_SEC CPU-seconds for IDLE_SEC (60 min here) is killed by its
# process group (read from /proc), STALLED_<stage> is written, and the chain continues with the next stage that can
# run (the next snapshot, the server stop, the next seed). Nothing runs past DEADLINE minus MARGIN_MIN.
# Launch (detached, from the repository root):
#   setsid nohup bash analysis/revision/dpo_seeds/run_two_seeds.sh \
#     > analysis/revision/dpo_seeds/logs/run_two_seeds.out 2>&1 < /dev/null &
set -u
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p $D/logs $D/state
if [ "${DRYRUN:-0}" = 1 ]; then LOG=$D/logs/run_two_seeds.dryrun.log; else LOG=$D/logs/run_two_seeds.log; fi
export IDLE_SEC=${IDLE_SEC:-3600}
source $D/common.sh
unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE VERIBIM_API_KEY VERIBIM_REQUEST_STYLE
MODE=${MODE:-full}; export SELECT=${SELECT:-val100}
SEED_LIST=${SEED_LIST:-"20261007:dpo_v10_s2 20261008:dpo_v10_s3"}
case "$MODE" in full|cut) ;; *) say "MODE=$MODE unknown"; exit 2;; esac
[ "$DRYRUN" = 1 ] || echo $$ > $D/state/driver.pid
SUF=""; [ "$DRYRUN" = 1 ] && SUF=.dryrun

say "=== run_two_seeds armed: MODE=$MODE SELECT=$SELECT seeds [$SEED_LIST]; window end $DEADLINE; watchdog ${IDLE_SEC}s; cores train $TRAIN_CORES server $SERVER_CORES reads $READ_CORES (conc $CONC, score workers $SW); disk $(disk_free_gb) GB free; driver pid $$ group $(pgid_of $$)"
if [ -n "${START_AT:-}" ]; then
  say "waiting until $START_AT"
  until [ "$(date +%s)" -ge "$(date -d "$START_AT" +%s)" ]; do sleep 30; done
fi

one(){ # seed runid bench
  say "--- run_seed $2 (seed $1, BENCH=$3) start"
  BENCH=$3 bash $D/run_seed.sh $1 $2 >> $D/logs/run_seed_$2$SUF.out 2>&1
  local rc=$?
  say "--- run_seed $2 (BENCH=$3) rc=$rc; markers: $(cd $D && ls DONE_$2 PHASE1_DONE_$2 FAILED_$2 REFUSED_$2 CONFIG_MISMATCH_$2 STALLED_*$2* SKIPPED_*$2* DEADLINE_*$2* 2>/dev/null | tr '\n' ' ')"
  return $rc
}

if [ "$MODE" = full ]; then
  for sr in $SEED_LIST; do one ${sr%%:*} ${sr#*:} full; done
else
  for sr in $SEED_LIST; do one ${sr%%:*} ${sr#*:} 324; done
  for sr in $SEED_LIST; do
    r=${sr#*:}
    [ -e $D/state/$r/CHOSEN ] || [ "$DRYRUN" = 1 ] || { say "phase 2: $r has no chosen snapshot; skipped"; continue; }
    one ${sr%%:*} $r full
  done
fi

# across-seed table: the reported run (seed 20260929) and the new seeds, completion on the same task sets
$L2 - $D "$SEED_LIST" > $D/SUMMARY_two_seeds$SUF.txt 2>&1 <<'PY'
import json, os, sys
D, seeds = sys.argv[1], [s.split(':') for s in sys.argv[2].split()]
B = 'runs_local/bench_v4/results'
AX = ('geometry', 'semantics', 'topology')
def stats(p):
    if not os.path.isfile(p): return None
    rows = [json.loads(l) for l in open(p) if l.strip()]
    ok = sum(1 for r in rows if all((r.get('score') or {}).get(k) is not None and float(r['score'][k]) >= 0.9 for k in AX))
    return ok / max(1, len(rows)), sum(float(r.get('final') or 0) for r in rows) / max(1, len(rows)), len(rows)
def line(label, p):
    s = stats(p); return f"{label:34s} " + ("not available" if s is None else f"completion {s[0]:.4f}  mean {s[1]:.4f}  n {s[2]}")
print("Seed replicates of the preference stage (completion = every checker axis >= 0.9)")
print("2,100-task benchmark v4c (results/full_all):")
for lab, n in (("sft_v10 (start of the stage)", "sft_v10"), ("dpo_v10_c6 (seed 20260929, reported)", "dpo_v10_c6"), ("dpo_v10_c3 (seed 20260929, val-100 rule)", "dpo_v10_c3")):
    print("  " + line(lab, f"{B}/full_all/per_task_{n}.jsonl"))
for seed, run in seeds:
    ch = open(f"{D}/state/{run}/CHOSEN").read().strip() if os.path.isfile(f"{D}/state/{run}/CHOSEN") else None
    print("  " + line(f"{ch or run} (seed {seed})", f"{B}/full_all/per_task_{ch}.jsonl" if ch else "/nonexistent"))
print("324-task subset (dedicated reads, lib arm):")
for lab, n in (("sft_v10", "sft_v10"), ("dpo_v10_c6 (seed 20260929, reported)", "dpo_v10_c6")):
    print("  " + line(lab, f"{B}/local324_lib_all/per_task_{n}.jsonl"))
for seed, run in seeds:
    ch = open(f"{D}/state/{run}/CHOSEN").read().strip() if os.path.isfile(f"{D}/state/{run}/CHOSEN") else None
    print("  " + line(f"{ch or run} (seed {seed})", f"{D}/bench324/per_task_{ch}.jsonl" if ch else "/nonexistent"))
PY
cat $D/SUMMARY_two_seeds$SUF.txt >> $LOG
[ "$DRYRUN" = 1 ] || { rm -f $D/state/driver.pid; touch $D/RUN_TWO_SEEDS_DONE; }
say "=== run_two_seeds done (MODE=$MODE); summary $D/SUMMARY_two_seeds$SUF.txt"
