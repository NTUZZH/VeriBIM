# Shared settings and helpers of the two-seed preference-stage chain (sourced, never run on its own).
# Callers set LOG (absolute) before sourcing. Every kill in this file is by process group read from /proc,
# never by a command-line pattern. Every path is absolute.

P="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
D=$P/analysis/revision/dpo_seeds
L2=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
L2TRAIN=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2train/bin/python
SERVER=http://127.0.0.1:8000
export PYTHONNOUSERSITE=1 PYTHONPATH=$P/code

O=$P/runs_local/stage_a_v10                     # val-100 v3b tasks, subset and gold cache
B=$P/runs_local/bench_v4                        # benchmark tasks, eval_bench_v4.sh, finish_read.sh
VH=$P/runs_local/stage_b_v10/val_hard           # hard validation set (only with SELECT=valhard)
REFCKPT=$P/checkpoints/stage_b/dpo_v10          # the reported run (comparator)
PAIRS=$P/runs_local/stage_b_v10/v10_filtered/dpo_pairs.jsonl
SFT_ADAPTER=$P/checkpoints/stage_a/sft_v10/adapter
PAIRS_MD5=fb53da53a74ecb2677509e320de2a599      # md5 of PAIRS on 2026-10-07 (file mtime 2026-09-29 13:25, before dpo_v10 trained)

# Cores: trainer 8-9,16-19; server 16-19; reads 8-9,18-19 with 16 in flight and 2 score workers.
TRAIN_CORES=${TRAIN_CORES:-8-9,16-19}; TRAIN_THREADS=${TRAIN_THREADS:-6}
SERVER_CORES=${SERVER_CORES:-16-19}; UTIL=${UTIL:-0.46}
READ_CORES=${READ_CORES:-8-9,18-19}; CONC=${CONC:-16}; SW=${SW:-2}

# Watchdog: a stage is silent when no file under its progress paths changed AND its process group used fewer than
# CPU_MIN_SEC CPU-seconds, both for IDLE_SEC. The CPU clause exists because the scoring phase of a read writes nothing
# for 1.5 to 3.5 hours while it burns CPU (dpo_v10_c6 full read: 98 min of log silence after the rollouts).
IDLE_SEC=${IDLE_SEC:-3600}; CPU_MIN_SEC=${CPU_MIN_SEC:-60}; POLL_SEC=${POLL_SEC:-60}
TICKS=$(getconf CLK_TCK)

# The GPU window ends at DEADLINE; nothing of this chain runs past DEADLINE minus MARGIN_MIN.
DEADLINE=${DEADLINE:-2026-10-08 09:00}; MARGIN_MIN=${MARGIN_MIN:-5}
HARD_STOP=$(( $(date -d "$DEADLINE" +%s) - MARGIN_MIN * 60 ))

# Planning estimates in minutes; a stage starts only if now + estimate <= HARD_STOP.
EST_TRAIN_MIN=${EST_TRAIN_MIN:-35}      # dry run, diff, training, final save (dpo_v10: 0.5 + 25 min)
EST_V100_MIN=${EST_V100_MIN:-7}         # one val-100 read (dpo_v10: 3.4 min on 10 cores, 4 workers)
EST_VH_MIN=${EST_VH_MIN:-35}            # one val-hard read (dpo_v10: 21 min on 10 cores, 4 workers)
EST_324_MIN=${EST_324_MIN:-55}          # one 324-task read (dpo_v10_c6: 31 min on 4 cores, 4 workers)
EST_FULL_MIN=${EST_FULL_MIN:-290}       # one 2,100-task read (dpo_v10_c6: 170 min on 10 cores, 4 workers)
FULL_MIN_GB=${FULL_MIN_GB:-55}          # free disk before a 2,100 read (about 43 GB of edited copies until packed)
SMALL_MIN_GB=${SMALL_MIN_GB:-15}        # free disk before a val-100, val-hard or 324 read

# Anchored command-line patterns, used only to DETECT (refuse), never to kill.
SRV_RX='^[^ ]*/envs/l2vllm/bin/python [^ ]*/envs/l2vllm/bin/vllm serve '
TRAINER_ANY_RX='^[^ ]*/envs/l2train/bin/python (-u )?-m stage_(a\.cli train|b\.train_dpo|c\.train_grpo) '
READ_ANY_RX='^[^ ]*/envs/l2/bin/python -u -m (stage_a\.run_gate|stage_b\.cli sample|stage_b\.run_branch) '

DRYRUN=${DRYRUN:-0}
MARK_DIR=${MARK_DIR:-$D}; STATE_DIR=${STATE_DIR:-$D/state}   # overridden only by test_watchdog.sh

say(){ echo "$(date '+%F %T') $*" >> "$LOG"; }

# ------------------------------------------------------------------ /proc helpers
proc_stat(){ # pid -> "state pgrp utime+stime+cutime+cstime" (comm may contain spaces, so split after the last ')')
  local line rest
  read -r line 2>/dev/null < /proc/$1/stat || return 1
  rest=${line##*) }
  set -- $rest
  echo "$1 $3 $(( ${12} + ${13} + ${14} + ${15} ))"
}
alive(){ local s; s=$(proc_stat "$1") || return 1; [ "${s%% *}" != Z ]; }
pgid_of(){ local s; s=$(proc_stat "$1") || return 1; set -- $s; echo "$2"; }
pg_members(){ # pgid -> live (non-zombie) pids of that group
  local pg=$1 f line rest p
  for f in /proc/[0-9]*/stat; do
    read -r line 2>/dev/null < "$f" || continue
    rest=${line##*) }; set -- $rest
    [ "$3" = "$pg" ] && [ "$1" != Z ] && { p=${f#/proc/}; echo "${p%/stat}"; }
  done
}
pg_cpu_ticks(){ # pgid -> summed CPU ticks of the group (children reaped into cutime/cstime included)
  local pg=$1 f line rest t=0
  for f in /proc/[0-9]*/stat; do
    read -r line 2>/dev/null < "$f" || continue
    rest=${line##*) }; set -- $rest
    [ "$3" = "$pg" ] && t=$(( t + ${12} + ${13} + ${14} + ${15} ))
  done
  echo $t
}
kill_pg(){ # pgid label: TERM the group, KILL after 60 s; never our own group, never 0 or 1
  local pg=$1 label=$2 me i
  me=$(pgid_of $$)
  if [ -z "$pg" ] || [ "$pg" -le 1 ] || [ "$pg" = "$me" ]; then say "refusing to signal process group '$pg' ($label; own group $me)"; return 1; fi
  say "TERM process group $pg ($label): $(pg_members $pg | tr '\n' ' ')"
  kill -TERM -- -"$pg" 2>/dev/null
  for i in $(seq 1 30); do [ -z "$(pg_members $pg)" ] && return 0; sleep 2; done
  say "KILL process group $pg ($label): $(pg_members $pg | tr '\n' ' ')"
  kill -KILL -- -"$pg" 2>/dev/null; sleep 2
  [ -z "$(pg_members $pg)" ]
}

# ------------------------------------------------------------------ time, disk, GPU
fits(){ # minutes -> true when the stage would end before HARD_STOP
  [ $(( $(date +%s) + $1 * 60 )) -le "$HARD_STOP" ]
}
disk_free_gb(){ df -BG --output=avail "$P" | tail -1 | tr -dc 0-9; }
gpu_used_mib(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -dc 0-9; }
gpu_apps(){ nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | tr '\n' ';'; }
wait_gpu_free(){ # minutes: wait until no compute process holds the card
  local i
  for i in $(seq 1 $(( $1 * 6 ))); do
    [ -z "$(gpu_apps)" ] && [ "$(gpu_used_mib)" -lt 2000 ] && return 0
    [ $i = 1 ] && say "waiting up to $1 min for the GPU: apps [$(gpu_apps)] used $(gpu_used_mib) MiB"
    sleep 10
  done
  say "GPU not free after $1 min: apps [$(gpu_apps)] used $(gpu_used_mib) MiB"; return 1
}

# ------------------------------------------------------------------ watched stage runner (the watchdog)
# watched STAGE STAGE_LOG HOOK -- command ...
#   Runs the command in its own process group (setsid), records "stage pid pgid start" in $STATE_DIR/current_stage,
#   and polls every POLL_SEC. Progress = a file under WATCH_PATHS (array, set by the caller) or the stage log changed,
#   or the group used >= CPU_MIN_SEC CPU-seconds (only when CPU_CHECK=1). Silent for IDLE_SEC: the group is killed,
#   $MARK_DIR/STALLED_<STAGE> written, return 124. At HARD_STOP: killed, $MARK_DIR/DEADLINE_<STAGE> written, return 125.
#   HOOK (a function name or "-") runs every poll with "pid pgid"; nonzero kills the group, return 126.
WATCH_PATHS=(); CPU_CHECK=1
watched(){
  local stage=$1 slog=$2 hook=$3; shift 3; [ "${1:-}" = "--" ] && shift
  if [ "$DRYRUN" = 1 ]; then say "[dry run] stage $stage would run: $*"; echo "[dry run] $stage: $*"; return 0; fi
  local start pid pg now last cpu cpu_ref progress rc stamp k
  start=$(date +%s); stamp=$STATE_DIR/.progress_$stage; touch "$stamp"
  setsid "$@" > "$slog" 2>&1 < /dev/null &
  pid=$!
  sleep 2
  pg=$(pgid_of $pid)
  if [ -z "$pg" ]; then wait $pid; rc=$?; say "stage $stage exited within 2 s rc=$rc"; return $rc; fi
  if [ "$pg" != "$pid" ]; then say "stage $stage: pid $pid is in group $pg, not its own; killing pid $pid only"; kill -TERM $pid; wait $pid; return 127; fi
  echo "$stage $pid $pg $start" > $STATE_DIR/current_stage
  say "stage $stage started: pid $pid, process group $pg, log $slog"
  last=$start; cpu_ref=$(pg_cpu_ticks $pg)
  while alive $pid; do
    for k in $(seq 1 $(( POLL_SEC / 5 > 0 ? POLL_SEC / 5 : 1 ))); do alive $pid || break; sleep 5; done
    alive $pid || break
    now=$(date +%s)
    if [ "$now" -ge "$HARD_STOP" ]; then
      echo "$(date '+%F %T') stage $stage pid $pid group $pg stopped at the window end ($DEADLINE minus $MARGIN_MIN min)" >> $MARK_DIR/DEADLINE_$stage
      say "DEADLINE: stopping stage $stage"; kill_pg $pg "$stage at the deadline"; wait $pid; rm -f $STATE_DIR/current_stage; return 125
    fi
    if [ "$hook" != "-" ] && ! $hook $pid $pg; then
      say "hook $hook rejected stage $stage"; kill_pg $pg "$stage rejected by $hook"; wait $pid; rm -f $STATE_DIR/current_stage; return 126
    fi
    progress=0
    [ -n "$(find "$slog" "${WATCH_PATHS[@]}" -newer "$stamp" -print -quit 2>/dev/null)" ] && progress=1
    cpu=$(pg_cpu_ticks $pg); [ "$cpu" -lt "$cpu_ref" ] && cpu_ref=$cpu
    [ "$CPU_CHECK" = 1 ] && [ $(( cpu - cpu_ref )) -ge $(( CPU_MIN_SEC * TICKS )) ] && progress=1
    if [ $progress = 1 ]; then last=$now; cpu_ref=$cpu; touch "$stamp"; fi
    if [ $(( now - last )) -ge "$IDLE_SEC" ]; then
      echo "$(date '+%F %T') stage $stage pid $pid group $pg: no progress file written and < $CPU_MIN_SEC CPU-s for $(( (now - last) / 60 )) min" >> $MARK_DIR/STALLED_$stage
      say "STALL: stage $stage silent for $(( (now - last) / 60 )) min"; kill_pg $pg "$stage stalled"; wait $pid; rm -f $STATE_DIR/current_stage; return 124
    fi
  done
  wait $pid; rc=$?
  local left; left=$(pg_members $pg | tr '\n' ' ')
  [ -n "$left" ] && { say "stage $stage: processes left in group $pg after the leader exited: $left"; kill_pg $pg "$stage leftovers"; }
  rm -f $STATE_DIR/current_stage
  say "stage $stage ended rc=$rc after $(( ($(date +%s) - start) / 60 )) min"
  return $rc
}

# ------------------------------------------------------------------ vLLM server (scripts_serve.sh conventions)
server_pid_any(){ pgrep -f "$SRV_RX" | head -1; }
server_answers(){ curl -s --max-time 5 $SERVER/v1/models >/dev/null 2>&1; }
server_start(){ # name adapter_dir log: NAME/ADAPTER/CORES/UTIL/LOG as scripts_serve.sh reads them
  local name=$1 adapter=$2 slog=$3 pid i
  if [ "$DRYRUN" = 1 ]; then say "[dry run] server: NAME=$name ADAPTER=$adapter CORES=$SERVER_CORES UTIL=$UTIL LOG=$slog bash $P/code/stage_c/scripts_serve.sh"; echo "[dry run] server $name $adapter"; return 0; fi
  if [ -n "$(server_pid_any)" ] || pgrep -f 'vllm serv[e]' >/dev/null || server_answers; then say "a vLLM server is already running or port 8000 answers; not starting another"; return 1; fi
  PYTHONNOUSERSITE=1 NAME=$name ADAPTER=$adapter CORES=$SERVER_CORES UTIL=$UTIL LOG=$slog \
    setsid nohup bash $P/code/stage_c/scripts_serve.sh > /dev/null 2>&1 < /dev/null &
  pid=$!; sleep 2
  if [ "$(pgid_of $pid)" != "$pid" ]; then say "server pid $pid is not its own group leader; killing pid $pid"; kill -TERM $pid; return 1; fi
  echo "$pid" > $STATE_DIR/server.pid
  for i in $(seq 1 90); do
    curl -s --max-time 5 $SERVER/v1/models 2>/dev/null | grep -q "\"$name\"" && break
    alive $pid || { say "server pid $pid died during start (log $slog)"; rm -f $STATE_DIR/server.pid; return 1; }
    sleep 10
  done
  if ! curl -s --max-time 5 $SERVER/v1/models | grep -q "\"$name\""; then say "server did not serve $name within 15 min"; server_stop; return 1; fi
  say "server up: pid $pid (own process group), $name, UTIL $UTIL, cores $SERVER_CORES, GPU $(gpu_used_mib) MiB"
}
server_stop(){ # stop only the server this chain started, by its process group read from /proc
  local pid pg used i
  [ "$DRYRUN" = 1 ] && { say "[dry run] server stop"; return 0; }
  [ -s $STATE_DIR/server.pid ] || return 0
  pid=$(cat $STATE_DIR/server.pid)
  if ! alive "$pid"; then rm -f $STATE_DIR/server.pid; return 0; fi
  pg=$(pgid_of $pid)
  [ "$pg" = "$pid" ] || { say "recorded server pid $pid is not a group leader (group $pg); not signalling the group"; return 1; }
  say "stopping the vLLM server pid $pid (process group $pg)"
  kill_pg "$pg" "vLLM server" || return 1
  rm -f $STATE_DIR/server.pid
  for i in $(seq 1 30); do used=$(gpu_used_mib); [ "$used" -lt 2000 ] && break; sleep 10; done
  say "GPU memory after the server stop: ${used} MiB"
}
load_adapter(){ # name path: the load/unload curl calls of post_dpo_v10.sh
  [ "$DRYRUN" = 1 ] && { say "[dry run] load $1 from $2"; return 0; }
  curl -s -o /dev/null -X POST $SERVER/v1/unload_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\"}" || true
  curl -s -X POST $SERVER/v1/load_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\", \"lora_path\": \"$2\"}" >> "$LOG" 2>&1; echo >> "$LOG"
  curl -s $SERVER/v1/models | $L2 -c "import sys,json; ids=[m['id'] for m in json.load(sys.stdin)['data']]; assert '$1' in ids, ids" \
    || { say "LOAD FAILED $1"; return 1; }
}

# ------------------------------------------------------------------ results
rows(){ [ -s "$1" ] && wc -l < "$1" || echo 0; }
completion_line(){ # per_task.jsonl -> "completion C mean M n N"
  $L2 - "$1" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
ok = sum(1 for r in rows if all((r.get('score') or {}).get(k) is not None and float((r.get('score') or {})[k]) >= 0.9
                                for k in ('geometry', 'semantics', 'topology')))
mean = sum(float(r.get('final') or 0) for r in rows) / max(1, len(rows))
print(f"completion {ok / max(1, len(rows)):.4f} mean {mean:.4f} n {len(rows)}")
PY
}
pack_edited(){ # run_dir/name stage_name: replace the edited copies by a verified tar.gz (per-task rows and transcripts stay)
  local d=$1 st=$2
  [ -d "$d/edited" ] || return 0
  WATCH_PATHS=("$d"); CPU_CHECK=1
  watched "$st" $D/logs/$st.log - -- taskset -c $READ_CORES bash -c "cd '$d' && tar czf edited.tar.gz edited && $L2 -c \"import tarfile; tarfile.open('edited.tar.gz').getmembers()\" && $L2 -c \"import shutil; shutil.rmtree('edited')\"" \
    && say "packed $d/edited (disk $(disk_free_gb) GB free)" || say "packing FAILED for $d (edited copies kept)"
}
