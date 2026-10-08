#!/bin/bash
# run_seed.sh SEED RUNID: one seed replicate of the preference stage dpo_v10, end to end.
#   a. guards (no vLLM server, no trainer, no read; pairs file present with dpo_v10's checksum; no weights in
#      checkpoints/stage_b/RUNID unless this chain already finished training it; GPU free)
#   b. trainer dry run, comparator diff against checkpoints/stage_b/dpo_v10/resolved_config.json (only run_id, seed,
#      output path, timestamp may differ), training with launch_dpo_v10.sh's COMMON arguments except --run-id and
#      --seed, the same diff again on the training run's own config (checked while it runs, and again at the end)
#   c. vLLM server with scripts_serve.sh conventions (NAME=RUNID, ADAPTER=final adapter, CORES 16-19, UTIL 0.46)
#   d. snapshot choice: SELECT=val100 (default: every snapshot and the final adapter on val-100 v3b, highest
#      completion, earliest on a tie), SELECT=valhard (the rule that chose dpo_v10_c6: val-hard, completion, then mean,
#      then latest step), or SELECT=fixed:N (no selection reads; checkpoint-N)
#   e. benchmark read of the chosen snapshot as RUNID_cN: BENCH=full (eval_bench_v4.sh PART=all into
#      runs_local/bench_v4/results/full_all, then finish_read.sh), BENCH=324 (the dedicated 324-task read settings of
#      run_local_subset324.sh, into dpo_seeds/bench324), BENCH=none; the server is stopped right after the rollouts'
#      read returns, then the by-version table is rewritten and the edited copies are packed (verified tar.gz)
#   f. server stopped by its process group; DONE_RUNID (BENCH=full or none) or PHASE1_DONE_RUNID (BENCH=324)
# Resumable: TRAIN_DONE and CHOSEN in dpo_seeds/state/RUNID/ skip stages b and d; a complete per-task file skips its read.
# Every stage runs under the watchdog of common.sh (silent IDLE_SEC -> group killed, STALLED_<stage>) and the window end.
# DRYRUN=1 evaluates the guards without refusing and prints every command; it starts nothing and writes no state.
set -u
SEED=${1:?usage: run_seed.sh SEED RUNID}; RUNID=${2:?usage: run_seed.sh SEED RUNID}
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p $D/logs $D/state $D/gates
if [ "${DRYRUN:-0}" = 1 ]; then LOG=$D/logs/run_seed_$RUNID.dryrun.log; else LOG=$D/logs/run_seed_$RUNID.log; fi
source $D/common.sh
unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE VERIBIM_API_KEY VERIBIM_REQUEST_STYLE
SELECT=${SELECT:-val100}; BENCH=${BENCH:-full}; GPU_WAIT_MIN=${GPU_WAIT_MIN:-30}
ST=$D/state/$RUNID; [ "$DRYRUN" = 1 ] || mkdir -p $ST
CKPT=$P/checkpoints/stage_b/$RUNID
OWN_SERVER=0

fail(){ say "FAILED: $*"; [ "$DRYRUN" = 1 ] || touch $D/FAILED_$RUNID; exit 1; }
mark(){ [ "$DRYRUN" = 1 ] || touch "$1"; }   # markers are never written by a dry run
cleanup(){
  local rc=$? st pid pg rest
  if [ -s $D/state/current_stage ]; then
    read -r st pid pg rest < $D/state/current_stage
    alive "$pid" && kill_pg "$pg" "$st, still running when run_seed $RUNID exits"
    rm -f $D/state/current_stage
  fi
  [ "$OWN_SERVER" = 1 ] && server_stop
  say "=== run_seed $RUNID exits rc=$rc"
}
trap cleanup EXIT
trap 'say "run_seed $RUNID: signal received"; exit 143' TERM INT HUP

[[ "$RUNID" =~ ^dpo_v10_s[0-9]+$ ]] || fail "run id $RUNID is not of the form dpo_v10_s<n>"
[[ "$SEED" =~ ^[0-9]+$ ]] && [ "$SEED" != 20260929 ] || fail "seed $SEED is not a new integer seed"
case "$SELECT" in val100|valhard|fixed:[0-9]*) ;; *) fail "SELECT=$SELECT unknown";; esac
case "$BENCH" in full|324|none) ;; *) fail "BENCH=$BENCH unknown";; esac
say "=== run_seed $RUNID seed $SEED: SELECT=$SELECT BENCH=$BENCH; cores train $TRAIN_CORES ($TRAIN_THREADS threads), server $SERVER_CORES, reads $READ_CORES (conc $CONC, score workers $SW); window end $DEADLINE (stop at $(date -d @$HARD_STOP '+%F %T')); watchdog ${IDLE_SEC}s silent; disk $(disk_free_gb) GB free"

# ---------------------------------------------------------------- a. guards
refuse(){ if [ "$DRYRUN" = 1 ]; then say "[dry run] guard would refuse: $*"; echo "[dry run] guard would refuse: $*"; else touch $D/REFUSED_$RUNID; fail "refused: $*"; fi; }
if [ -n "$(server_pid_any)" ] || pgrep -f 'vllm serv[e]' >/dev/null; then refuse "a vLLM server is running (pid $(server_pid_any))"; fi
server_answers && refuse "port 8000 answers"
if pgrep -f 'stage_b\.train_dp[o]' >/dev/null || pgrep -f "$TRAINER_ANY_RX" >/dev/null; then refuse "a trainer is running"; fi
pgrep -f "$READ_ANY_RX" >/dev/null && refuse "a read is running: $(pgrep -f "$READ_ANY_RX" | tr '\n' ' ')"
[ -s "$PAIRS" ] || refuse "no pairs file $PAIRS"
[ "$(md5sum < "$PAIRS" | cut -d' ' -f1)" = "$PAIRS_MD5" ] || refuse "pairs file checksum differs from the one recorded on 2026-10-07"
[ -s "$SFT_ADAPTER/adapter_model.safetensors" ] || refuse "no sft_v10 adapter"
[ -s "$REFCKPT/resolved_config.json" ] || refuse "no comparator config $REFCKPT/resolved_config.json"
if [ ! -e $ST/TRAIN_DONE ]; then
  if [ -s "$CKPT/adapter/adapter_model.safetensors" ] || ls -d "$CKPT"/checkpoint-* >/dev/null 2>&1; then
    refuse "checkpoint dir $CKPT holds trained weights"; fi
fi
say "guards passed: pairs $(wc -l < "$PAIRS") lines md5 $PAIRS_MD5"

# ---------------------------------------------------------------- b. training
NOTES="Stage B v10: DPO on sft_v10 with on-policy pairs from sft_v10 (6,000-task pool 2,400/1,800/1,800 by version, family reading; trajectory + branch-repair pairs; pairs of clearance-flagged, corrected-opposite and eight-gram-overlap tasks excluded); recipe (beta 0.1, LR 5e-6, eff. batch 32) over four epochs so that 133 pairs give 17 optimizer steps as dpo_v9 had; early-stopped on val-100 v3b snapshots every 3 steps"
COMMON=(--run-id "$RUNID" --pairs "$PAIRS" --adapter "$SFT_ADAPTER"
        --compare-config $P/checkpoints/stage_a/sft_v10/resolved_config.json
        --max-seq 8192 --save-steps 3 --epochs 4 --seed "$SEED"
        --notes "$NOTES")
TRAIN_CMD=(env PYTHONPATH=$P/code OMP_NUM_THREADS=$TRAIN_THREADS MKL_NUM_THREADS=$TRAIN_THREADS PYTHONNOUSERSITE=1
           taskset -c $TRAIN_CORES $L2TRAIN -m stage_b.train_dpo "${COMMON[@]}")
TRAIN_T0=0; CONFIG_CHECKED=0
train_hook(){ # pid pgid: once the training run has dumped its config, the strict comparator diff must pass
  [ "$CONFIG_CHECKED" = 1 ] && return 0
  [ -s $CKPT/resolved_config.json ] && [ "$(stat -c %Y $CKPT/resolved_config.json)" -ge "$TRAIN_T0" ] || return 0
  if $L2 $D/config_diff.py $CKPT/resolved_config.json $REFCKPT/resolved_config.json --run-id $RUNID --seed $SEED \
       --out $D/${RUNID}_config_diff.txt > /dev/null; then
    CONFIG_CHECKED=1; say "training config of $RUNID checked against dpo_v10: $(tail -1 $D/${RUNID}_config_diff.txt)"; return 0
  fi
  touch $D/CONFIG_MISMATCH_$RUNID; say "training config of $RUNID differs from dpo_v10: $(tail -1 $D/${RUNID}_config_diff.txt)"; return 1
}
if [ -e $ST/TRAIN_DONE ]; then
  say "training of $RUNID done earlier; skipped"
else
  fits $EST_TRAIN_MIN || { mark $D/SKIPPED_DEADLINE_train_$RUNID; fail "less than $EST_TRAIN_MIN min left before the window end; not training"; }
  [ "$DRYRUN" = 1 ] || wait_gpu_free $GPU_WAIT_MIN || refuse "the GPU is not free"
  cd $P/code
  WATCH_PATHS=(); CPU_CHECK=0
  watched dryrun_$RUNID $D/logs/train_dryrun_$RUNID.log - -- "${TRAIN_CMD[@]}" --dry-run || fail "trainer dry run rc=$?"
  if [ "$DRYRUN" = 1 ]; then
    say "[dry run] comparator: $L2 $D/config_diff.py $CKPT/resolved_config.json $REFCKPT/resolved_config.json --run-id $RUNID --seed $SEED --out $D/${RUNID}_config_diff_dryrun.txt --dry-run"
  else
    $L2 $D/config_diff.py $CKPT/resolved_config.json $REFCKPT/resolved_config.json --run-id $RUNID --seed $SEED \
      --out $D/${RUNID}_config_diff_dryrun.txt --dry-run > /dev/null \
      || { touch $D/CONFIG_MISMATCH_$RUNID; fail "dry-run config differs from dpo_v10 beyond run id/seed/output/timestamp: $(tail -1 $D/${RUNID}_config_diff_dryrun.txt)"; }
    say "dry-run config of $RUNID against dpo_v10: $(tail -1 $D/${RUNID}_config_diff_dryrun.txt); adapter parameters $($L2 -c "import json;print(json.load(open('$CKPT/resolved_config.json'))['adapter_trainable_params'])") (expected 43278336, asserted by the trainer)"
  fi
  TRAIN_T0=$(date +%s)
  WATCH_PATHS=($CKPT); CPU_CHECK=0          # progress: the tqdm line every optimizer step (~70 s) and a snapshot every 3 steps
  watched train_$RUNID $D/logs/train_$RUNID.log train_hook -- "${TRAIN_CMD[@]}"; rc=$?
  cd $P
  [ "$DRYRUN" = 1 ] || {
    [ $rc -eq 0 ] || fail "training rc=$rc"
    [ -s $CKPT/adapter/adapter_model.safetensors ] || fail "no final adapter after training"
    for s in 3 6 9 12 15 18 20; do [ -s $CKPT/checkpoint-$s/adapter_model.safetensors ] || fail "snapshot checkpoint-$s missing"; done
    $L2 $D/config_diff.py $CKPT/resolved_config.json $REFCKPT/resolved_config.json --run-id $RUNID --seed $SEED \
      --out $D/${RUNID}_config_diff.txt > /dev/null || { touch $D/CONFIG_MISMATCH_$RUNID; fail "training config differs from dpo_v10"; }
    say "trained $RUNID: $($L2 -c "import json;m=json.load(open('$CKPT/outcome.json'))['metrics'];print('runtime %.0f s, train loss %.4f, epoch %s' % (m['train_runtime'], m['train_loss'], m['epoch']))")"
    touch $ST/TRAIN_DONE
  }
fi
cd $P

# ---------------------------------------------------------------- c. server
CH=""; [ -s $ST/CHOSEN ] && CH=$(cat $ST/CHOSEN)
need_server=0
{ [ -z "$CH" ] && [ "${SELECT%%:*}" != fixed ]; } && need_server=1
[ "$BENCH" != none ] && need_server=1
if [ $need_server = 1 ]; then
  [ "$DRYRUN" = 1 ] || wait_gpu_free 10 || fail "the GPU is not free for the server"
  server_start $RUNID $CKPT/adapter $D/logs/serve_$RUNID.log || fail "server start"
  OWN_SERVER=1
fi

# ---------------------------------------------------------------- d. snapshot choice
adapter_path(){ # served name -> adapter directory
  if [ "$1" = "$RUNID" ]; then echo $CKPT/adapter; else echo $CKPT/checkpoint-${1#${RUNID}_c}; fi
}
read_gate(){ # name adapter_path set(v100|valhard)
  local name=$1 apath=$2 vset=$3 dir n tasks subset gold est label attempt rc
  case $vset in
    v100)    dir=$D/gates/v100b; n=100; tasks=$O/val_tasks_100_v3b.jsonl; subset=$O/val_subset_100_v3b.json; gold=$O/gates/_gold_v3; est=$EST_V100_MIN
             label="val-100 v3b (a third per IFC version; repaired), $name, family reading, sandbox guard on";;
    valhard) dir=$D/gates/valhard; n=300; tasks=$VH/val_hard_tasks.jsonl; subset=$VH/val_hard_ids.json; gold=$VH/_gold; est=$EST_VH_MIN
             label="val-hard, $name, greedy, family reading, sandbox guard on";;
  esac
  mkdir -p $dir
  [ "$(rows $dir/per_task_$name.jsonl)" -eq $n ] && { say "$name already read on $vset"; return 0; }
  [ -e $dir/per_task_$name.jsonl ] && mv $dir/per_task_$name.jsonl $dir/per_task_$name.jsonl.partial_$(date +%s)
  fits $est || { mark $D/SKIPPED_DEADLINE_${vset}_$name; say "no time left for the $vset read of $name"; return 1; }
  [ "$(disk_free_gb)" -ge "$SMALL_MIN_GB" ] || { say "disk $(disk_free_gb) GB < $SMALL_MIN_GB GB before the $vset read of $name"; return 1; }
  load_adapter $name $apath || return 1
  for attempt in 1 2; do
    WATCH_PATHS=($dir/$name); CPU_CHECK=1
    watched ${vset}_$name $dir/$name.log - -- env -u VERIBIM_NO_GEOM -u VERIBIM_USER_NOTE_FILE \
      VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONPATH=$P/code \
      taskset -c $READ_CORES $L2 -u -m stage_a.run_gate --adapters $name --base-url $SERVER/v1 --subset $subset --tasks-file $tasks \
      --run-dir $dir --gold-cache $gold --concurrency $CONC --score-workers $SW --scorer-reading family --label "$label"
    rc=$?
    [ "$DRYRUN" = 1 ] && return 0
    [ "$(rows $dir/per_task_$name.jsonl)" -eq $n ] && break
    [ $rc -ge 124 ] && [ $rc -le 126 ] && break       # stalled, deadline or rejected: no second attempt
    say "$vset read of $name attempt $attempt rc=$rc with $(rows $dir/per_task_$name.jsonl) rows"
  done
  [ "$(rows $dir/per_task_$name.jsonl)" -eq $n ] || { say "$name: per-task file missing or not $n rows on $vset"; return 1; }
  pack_edited $dir/$name pack_${vset}_$name
  say "$name on $vset: $(completion_line $dir/per_task_$name.jsonl)"
}
if [ -n "$CH" ]; then
  say "chosen snapshot of $RUNID from an earlier pass: $CH"
else
  case "$SELECT" in
    fixed:*)
      CH=${RUNID}_c${SELECT#fixed:}
      [ "$DRYRUN" = 1 ] || [ -s $(adapter_path $CH)/adapter_model.safetensors ] || fail "no snapshot for $CH"
      say "snapshot fixed by SELECT=$SELECT: $CH (no selection reads)";;
    val100|valhard)
      if [ "$SELECT" = val100 ]; then vset=v100; n=100; base=$O/gates/v100b/per_task_sft_v10.jsonl; curve=$D/${RUNID}_val100_curve.txt
      else vset=valhard; n=300; base=$VH/gates/per_task_sft_v10.jsonl; curve=$D/${RUNID}_valhard_curve.txt; fi
      names=(); for s in $( (ls -d $CKPT/checkpoint-* 2>/dev/null || true) | sed 's/.*checkpoint-//' | sort -n); do names+=(${RUNID}_c$s); done
      [ "$DRYRUN" = 1 ] && [ ${#names[@]} -eq 0 ] && names=(${RUNID}_c3 ${RUNID}_c6 ${RUNID}_c9 ${RUNID}_c12 ${RUNID}_c15 ${RUNID}_c18 ${RUNID}_c20)
      [ $vset = v100 ] && names+=($RUNID)          # val100 also reads the final adapter (post_dpo_v10.sh); val-hard reads snapshots only
      for nm in "${names[@]}"; do read_gate $nm $(adapter_path $nm) $vset || say "$vset read of $nm not available; it is left out of the choice"; done
      if [ "$DRYRUN" = 1 ]; then
        say "[dry run] choice: $L2 $D/select_snapshot.py --rule $SELECT --dir $D/gates/$([ $vset = v100 ] && echo v100b || echo valhard) --run-id $RUNID --n $n --baseline $base --out $curve"
        CH=${RUNID}_c6
      else
        $L2 $D/select_snapshot.py --rule $SELECT --dir $D/gates/$([ $vset = v100 ] && echo v100b || echo valhard) --run-id $RUNID \
          --n $n --baseline $base --out $curve >> $LOG 2>&1 || fail "no snapshot could be chosen (curve $curve)"
        CH=$(grep '^CHOSEN' $curve | cut -f2)
        say "chosen by $SELECT: $CH"
      fi;;
  esac
  [ "$DRYRUN" = 1 ] || echo "$CH" > $ST/CHOSEN
fi
CHP=$(adapter_path $CH)

# ---------------------------------------------------------------- e. benchmark read
bench_ok=0
case "$BENCH" in
  full)
    RUN=$B/results/full_all; NB=$(grep -c . $B/tasks.v4c.jsonl)
    if [ "$(rows $RUN/per_task_$CH.jsonl)" -eq "$NB" ]; then say "$CH already read on the $NB-task benchmark"; bench_ok=1
    elif [ -e $RUN/per_task_$CH.jsonl ]; then say "$RUN/per_task_$CH.jsonl exists with $(rows $RUN/per_task_$CH.jsonl) rows; left in place"
    elif ! fits $EST_FULL_MIN; then mark $D/SKIPPED_DEADLINE_full_$CH; say "less than $EST_FULL_MIN min left; the $NB-task read of $CH is skipped"
    elif [ "$(disk_free_gb)" -lt "$FULL_MIN_GB" ]; then mark $D/SKIPPED_DISK_full_$CH; say "disk $(disk_free_gb) GB < $FULL_MIN_GB GB; the $NB-task read of $CH is skipped"
    else
      load_adapter $CH $CHP || fail "load $CH"
      WATCH_PATHS=($RUN/$CH $RUN/$CH.log); CPU_CHECK=1
      watched full_$CH $D/logs/full_$CH.out - -- env -u VERIBIM_NO_GEOM -u VERIBIM_USER_NOTE_FILE \
        GATE_CORES=$READ_CORES CONC=$CONC SW=$SW PART=all VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1 PYTHONNOUSERSITE=1 \
        bash $B/eval_bench_v4.sh $CH
      rc=$?
      if [ "$DRYRUN" = 1 ]; then say "[dry run] then: server stop; bash $B/finish_read.sh $RUN $CH; pack $RUN/$CH/edited"
      elif [ "$(rows $RUN/per_task_$CH.jsonl)" -eq "$NB" ]; then
        server_stop; OWN_SERVER=0
        bash $B/finish_read.sh $RUN $CH >> $LOG 2>&1
        pack_edited $RUN/$CH pack_full_$CH
        say "$CH on the $NB-task benchmark: $(grep '^ALL' $RUN/by_version_$CH.txt)"
        bench_ok=1; touch $ST/BENCH_FULL_DONE
      else say "the $NB-task read of $CH ended rc=$rc with $(rows $RUN/per_task_$CH.jsonl) rows"; fi
    fi;;
  324)
    RUN=$D/bench324; NB=324; mkdir -p $RUN
    if [ "$(rows $RUN/per_task_$CH.jsonl)" -eq "$NB" ]; then say "$CH already read on the 324-task subset"; bench_ok=1
    elif ! fits $EST_324_MIN; then mark $D/SKIPPED_DEADLINE_324_$CH; say "less than $EST_324_MIN min left; the 324-task read of $CH is skipped"
    elif [ "$(disk_free_gb)" -lt "$SMALL_MIN_GB" ]; then mark $D/SKIPPED_DISK_324_$CH; say "disk $(disk_free_gb) GB < $SMALL_MIN_GB GB; the 324-task read is skipped"
    else
      [ -e $RUN/per_task_$CH.jsonl ] && mv $RUN/per_task_$CH.jsonl $RUN/per_task_$CH.jsonl.partial_$(date +%s)
      load_adapter $CH $CHP || fail "load $CH"
      WATCH_PATHS=($RUN/$CH); CPU_CHECK=1
      watched b324_$CH $RUN/$CH.log - -- env -u VERIBIM_NO_GEOM -u VERIBIM_USER_NOTE_FILE \
        VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONPATH=$P/code \
        taskset -c $READ_CORES $L2 -u -m stage_a.run_gate --adapters $CH --base-url $SERVER/v1 --subset $B/subset_324.v4c.json \
        --tasks-file $B/tasks.v4c.jsonl --run-dir $RUN --gold-cache $B/_gold_cache --concurrency $CONC --score-workers $SW \
        --scorer-reading family --label "VeriBIM-Bench v4b 324-task subset, lib arm, local $CH, sandbox guard"
      rc=$?
      if [ "$DRYRUN" = 1 ]; then say "[dry run] then: server stop; bash $B/finish_read.sh $RUN $CH; pack $RUN/$CH/edited"
      elif [ "$(rows $RUN/per_task_$CH.jsonl)" -eq "$NB" ]; then
        server_stop; OWN_SERVER=0
        bash $B/finish_read.sh $RUN $CH >> $LOG 2>&1
        pack_edited $RUN/$CH pack_324_$CH
        say "$CH on the 324-task subset: $(grep '^ALL' $RUN/by_version_$CH.txt)"
        bench_ok=1; touch $ST/BENCH_324_DONE
      else say "the 324-task read of $CH ended rc=$rc with $(rows $RUN/per_task_$CH.jsonl) rows"; fi
    fi;;
  none) bench_ok=1;;
esac

# ---------------------------------------------------------------- f. server stop, markers, summary
[ "$OWN_SERVER" = 1 ] && { server_stop; OWN_SERVER=0; }
[ "$DRYRUN" = 1 ] && { say "=== dry run of $RUNID complete"; exit 0; }
{
  echo "run $RUNID seed $SEED; selection $SELECT; chosen $CH ($CHP)"
  for f in $D/${RUNID}_val100_curve.txt $D/${RUNID}_valhard_curve.txt; do [ -s $f ] && { echo "--- $(basename $f)"; cat $f; }; done
  F=$B/results/full_all
  if [ -s $F/by_version_$CH.txt ] && [ "$(rows $F/per_task_$CH.jsonl)" -eq 2100 ]; then
    echo "--- 2,100-task benchmark (v4c, family reading, guard on)"
    for m in $CH dpo_v10_c6 dpo_v10_c3 sft_v10; do echo "$m: $(grep '^ALL' $F/by_version_$m.txt)"; done
    for m in dpo_v10_c6 sft_v10; do
      echo "--- paired $CH vs $m"
      $L2 $P/runs_local/stage_b_v3/completion_table.py $CH=$F/per_task_$CH.jsonl $m=$F/per_task_$m.jsonl --paired $CH $m 2>&1 | grep -i -E 'paired|ALL' | head -5
    done
  fi
  if [ -s $D/bench324/by_version_$CH.txt ]; then
    echo "--- 324-task subset (dedicated read, lib arm, guard on)"
    echo "$CH: $(grep '^ALL' $D/bench324/by_version_$CH.txt)"
    for m in dpo_v10_c6 sft_v10; do echo "$m (local324_lib_all): $(grep '^ALL' $B/results/local324_lib_all/by_version_$m.txt 2>/dev/null)"; done
  fi
} > $D/${RUNID}_summary.txt 2>&1
if [ $bench_ok = 1 ]; then
  if [ "$BENCH" = 324 ]; then touch $D/PHASE1_DONE_$RUNID; say "=== PHASE1_DONE_$RUNID ($CH)"
  else touch $D/DONE_$RUNID; say "=== DONE_$RUNID ($CH)"; fi
  exit 0
fi
say "=== $RUNID ended without its benchmark read (see SKIPPED_*/STALLED_* markers)"; exit 3
