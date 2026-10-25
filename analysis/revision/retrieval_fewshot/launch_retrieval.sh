#!/bin/bash
# Retrieval few-shot arm on the 108-task subset: the untrained base model, with the three nearest imitation-training
# trajectories (TF-IDF over the masked instruction, retrieve.py) as worked examples in its user turn, one note per task.
# Same harness, subset, gold cache, sandbox guard, family reading and protocol values as the documented arm
# (results/local108_informed_all); only the note differs.
#   ARM=retrieval      bash launch_retrieval.sh [served name]  # documented library note + retrieved examples -> results/local108_retrieval_all
#   ARM=retrievalshort bash launch_retrieval.sh [served name]  # short library note + retrieved examples      -> results/local108_retrievalshort_all
#   LIMIT=n ...                                                 # bounded check in a *_smoke<n>_all directory, never a reported one
# Needs the base model (no adapter) served at 127.0.0.1:8000 under the name Qwen3.5-9B with a 65,536-token context.
set -u; cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
NAME="${1:-Qwen3.5-9B}"; ARM="${ARM:?ARM=retrieval or ARM=retrievalshort}"
HERE=analysis/revision/retrieval_fewshot
B=runs_local/bench_v4; OUT=$B/results; L=$HERE/launch_retrieval.log
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python; BASE_URL=http://127.0.0.1:8000/v1
export PYTHONPATH=code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
# a local greedy read: no hosted request style, no sampling knobs, the helper library bound
unset VERIBIM_NO_GEOM VERIBIM_REQUEST_STYLE VERIBIM_API_KEY VERIBIM_REASONING_EFFORT VERIBIM_CHAT_TEMPLATE_KWARGS \
      VERIBIM_LOCAL_TEMPERATURE VERIBIM_LOCAL_TOP_P VERIBIM_LOCAL_TOP_K VERIBIM_LOCAL_PRESENCE_PENALTY VERIBIM_LOCAL_SEED
say(){ echo "$(date '+%F %T') $*" >> $L; }
case "$ARM" in
  retrieval)      NOTES=$HERE/notes;       TAG=local108_retrieval ;;
  retrievalshort) NOTES=$HERE/notes_short; TAG=local108_retrievalshort ;;
  *) say "unknown ARM=$ARM"; exit 2 ;;
esac
export VERIBIM_USER_NOTE_FILE=$NOTES   # a directory: run_gate_pertask.py reads <directory>/<task_id>.md
SUB=$B/subset_108_hosted.v4c.json; TASKS=$B/tasks.v4c.jsonl
[ "${LIMIT:-0}" = 0 ] || TAG="${TAG}_smoke${LIMIT}"
RUN=$OUT/${TAG}_all
# the notes are the ones the dry run checked
( cd $NOTES && sha256sum --quiet -c $HERE/results/manifest_$(basename $NOTES).sha256 ) || { say "notes differ from the manifest"; exit 2; }
[ "$(ls $NOTES/*.md | wc -l)" = 108 ] || { say "expected 108 notes in $NOTES"; exit 2; }
# the server holds the base model with the protocol context length
curl -s $BASE_URL/models | $PY -c "
import sys, json
d = {m['id']: m for m in json.load(sys.stdin)['data']}
assert '$NAME' in d, list(d)
assert int(d['$NAME'].get('max_model_len') or 0) >= 65536, d['$NAME'].get('max_model_len')
" || { say "not served, or context below 65,536: $NAME"; exit 2; }
mkdir -p $RUN
test ! -e "$RUN/per_task_${NAME}.jsonl" || { say "$RUN/per_task_${NAME}.jsonl exists; refusing"; exit 2; }
say "START $TAG $NAME (base $BASE_URL, notes $NOTES, manifest sha256 $(sha256sum $HERE/results/manifest_$(basename $NOTES).sha256 | cut -c1-16), subset md5 $(md5sum $SUB | cut -c1-32), guard $VERIBIM_SANDBOX_GUARD, landlock $VERIBIM_SANDBOX_LANDLOCK, cores ${GATE_CORES:-16-23})"
taskset -c ${GATE_CORES:-16-23} $PY -u $HERE/run_gate_pertask.py --adapters "$NAME" --limit ${LIMIT:-0} --base-url $BASE_URL \
   --subset $SUB --tasks-file $TASKS --run-dir $RUN --gold-cache $B/_gold_cache --concurrency ${CONC:-16} --score-workers ${SW:-4} \
   --scorer-reading family --label "VeriBIM-Bench v4b 108-task subset, $ARM arm, local $NAME, sandbox guard" > "$RUN/$NAME.log" 2>&1
RC=$?; say "END $TAG $NAME rc=$RC"
[ $RC = 0 ] || exit $RC
$PY - "$RUN/per_task_${NAME}.jsonl" "$TASKS" > "$RUN/by_version_${NAME}.txt" <<'PY'
import json, sys, collections
P={json.loads(l)['task_id']:json.loads(l) for l in open(sys.argv[1])}
T={json.loads(l)['task_id']:json.loads(l) for l in open(sys.argv[2])}
agg=collections.defaultdict(lambda:[0,0,0.0,0.0])
def completed(r):
    sc=r.get('score') or {}; ax=[sc.get(k) for k in ('geometry','semantics','topology')]
    return all(a is not None and a>=0.9 for a in ax)
for tid,r in P.items():
    t=T.get(tid)
    if t is None: continue
    for key in (t['ifc_version'], (t['ifc_version'], t['operation']), (t['ifc_version'], t['origin']), 'ALL'):
        a=agg[key]; a[0]+=1; a[1]+=completed(r); a[2]+=float(r.get('final') or 0); a[3]+=float(r.get('tool_rounds') or 0)
for k in sorted(agg, key=str):
    n,c,s,tr=agg[k]; print(k, n, 'completion %.3f' % (c/n), 'mean %.3f' % (s/n), 'rounds %.2f' % (tr/n))
PY
$PY $HERE/audit_fs_access.py "$RUN/$NAME/transcripts" >> $L 2>&1
say "$(grep '^ALL' $RUN/by_version_${NAME}.txt)"
say "=== RETRIEVAL_${TAG}_${NAME}_DONE"; touch "$RUN/DONE_${NAME}"
