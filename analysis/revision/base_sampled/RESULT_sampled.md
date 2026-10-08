# Untrained Qwen3.5-9B alone, model-card sampling, thinking off (T 0.7, top-p 0.8, top-k 20, presence 1.5), 108 subset
per-task file: runs_local/bench_v4/results/local108_alone_sampled_all/per_task_Qwen3.5-9B.jsonl
n = 108; under-specified 11; fully specified 97

completion all 0.028; fully specified 0.031 (3/97); under-specified 0/11; strict 0.98 all 0.028, fully specified 0.031
mean rounds 18.70; stops {'budget_exhausted': 58, 'context_overflow': 38, 'completed': 10, 'sandbox_crash': 2}; committed 24; errors 40; wrong commits (committed, not done) 21; mean tokens in/out 168580/9558; mean seconds 470.0
by version: IFC2X3 0/36, IFC4 0/36, IFC4X3 3/36

vs Claude Sonnet 5.5 with library: all tasks 0.852 -> diff -0.824 [-0.889,-0.750] task, [-0.917,-0.717] building; fully specified 0.948 -> diff -0.918 [-0.969,-0.856] task, [-0.966,-0.861] building; discordant this-only 0 / other-only 89
vs Claude Sonnet 5.5 alone: all tasks 0.731 -> diff -0.704 [-0.787,-0.620] task, [-0.802,-0.600] building; fully specified 0.814 -> diff -0.784 [-0.866,-0.701] task, [-0.845,-0.718] building; discordant this-only 0 / other-only 76
vs Final model with library: all tasks 0.972 -> diff -0.944 [-0.981,-0.898] task, [-0.982,-0.898] building; fully specified 0.969 -> diff -0.938 [-0.979,-0.887] task, [-0.980,-0.887] building; discordant this-only 0 / other-only 91
vs Untrained base alone (greedy): all tasks 0.019 -> diff +0.009 [-0.028,+0.046] task, [-0.030,+0.053] building; fully specified 0.021 -> diff +0.010 [-0.031,+0.052] task, [-0.033,+0.060] building; discordant this-only 3 / other-only 2

under-specified tasks:
  DOR-DEL-SPA-B24-005: failed; committed; reply: 'The door (3DUKEWsu38HesKG7jwWXEq - PORTE-002) has been successfully deleted along with its 2 associated relationships. The model now has 18 '
  DOR-UPD-TOP-B11m4-003: failed; committed; reply: ''
  SLB-UPD-TOP-B27m4-015: failed; committed; reply: "The task has been completed successfully. I have:\n\n1. Located the storey named 'Tak' in the IFC model\n2. Identified all slabs that were assi"
  WAL-CRE-DIR-B11-003: failed; no commit; reply: ''
  WAL-UPD-DIR-B24m4X3-008: failed; committed; reply: 'Let me check the available API functions:'
  WAL-UPD-DIR-B39m4X3-009: failed; no commit; reply: 'Let me check the schema structure first:'
  WAL-UPD-TOP-B27-004: failed; committed; reply: ''
  WIN-UPD-DIR-B27m4-002: failed; committed; reply: 'I have successfully changed the overall height of all 24 windows in the IFC model from their various original heights (ranging from 590mm to'
  WIN-UPD-SPA-B45-009: failed; committed; reply: "All 16 windows have been successfully assigned to the type object named 'X0-120 3mm'. The changes have been committed to the IFC model."
  WIN-UPD-TOP-B45-007: failed; no commit; reply: 'Let me check the available functions in element_util and use a different approach to access property sets.'
  WIN-UPD-TOP-B45m4X3-007: failed; no commit; reply: 'Now I can see that the window has a `GlobalId` attribute. Let me also check how to properly set the material for a window.'
