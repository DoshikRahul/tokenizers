#!/usr/bin/env bash
# RQ2 end-to-end, one stage at a time:   bash run_all_rq2.sh <stage>
# Stages stop wherever a person must review a sheet. Every stage is resumable (rerun = continue).
#
#   setup      venv + requirements + check the generator server
#   prep       build data, plant candidates (dev auto-accepted; test1 -> REVIEW), MedlinePlus corpus
#   merge      merge reviewed test1 planted errors, mask doctor A/P in dev + test1 (-> REVIEW mask audit)
#   traindata  verifier training pairs from ACI train (train split only)
#   train      QLoRA verifier (GPU)
#   dev        all RQ2 conditions on dev                     (GPU verifier + generator server)
#   tune       dev thresholds + dev table (pick K_REF, K_TURN, then set them in rq2.env)
#   test       conditions on test1 with the chosen k
#   eval       test1 report + per-step annotation sheet (-> REVIEW steps sheet)
#   steps      score the filled per-step sheet
#   smoke      offline plumbing test with stub models
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[[ -f rq2.env ]] && source rq2.env
PY=${PY:-.venv/bin/python}
K_REF=${K_REF:-3}
K_TURN=${K_TURN:-5}
V=${VERIFIER_NAME:-hf}

pause() { echo; echo ">>> REVIEW NEEDED: $*"; echo ">>> then run: bash run_all_rq2.sh $NEXT"; exit 0; }

conds_dev() {
  for S in preap full; do
    $PY run_rq2.py --condition U1 --split dev --setting $S
    $PY run_rq2.py --condition U2 --split dev --setting $S
    $PY run_rq2.py --condition U3 --split dev --setting $S
  done
  for k in 1 3 5; do
    $PY run_rq2.py --condition U2 --split dev --evidence topk --k $k
    $PY run_rq2.py --condition U4 --split dev --k $k
  done
  $PY run_rq2.py --condition U4 --split dev --setting full --k $K_REF
  LINKER=retrieval $PY run_rq2.py --condition U3 --split dev
  LINKER=retrieval $PY run_rq2.py --condition U4 --split dev --k $K_REF
}

conds_test() {
  for S in preap full; do
    $PY run_rq2.py --condition U1 --split test1 --setting $S
    $PY run_rq2.py --condition U2 --split test1 --setting $S
    $PY run_rq2.py --condition U3 --split test1 --setting $S
    $PY run_rq2.py --condition U4 --split test1 --setting $S --k $K_REF
  done
  $PY run_rq2.py --condition U2 --split test1 --evidence topk --k $K_TURN
  LINKER=retrieval $PY run_rq2.py --condition U3 --split test1
  LINKER=retrieval $PY run_rq2.py --condition U4 --split test1 --k $K_REF
}

case "${1:-}" in
  setup)
    [[ -x .venv/bin/python ]] || python3 -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.txt
    curl -sf "${GEN_BASE_URL%/v1}/health" && echo || { echo "generator server not reachable at $GEN_BASE_URL"; exit 1; }
    echo "setup ok" ;;
  prep)
    NEXT=merge
    $PY build_dataset.py --splits train dev test1
    $PY plant_errors.py --split dev && $PY plant_errors.py --split dev --merge --accept-all
    $PY plant_errors.py --split test1
    $PY medlineplus.py
    pause "data_out/planted_candidates_test1.csv (approved=1/0, two people) and data_out/audit_valid_test1.csv (valid_ok, section_ok)" ;;
  merge)
    NEXT=traindata
    $PY plant_errors.py --split test1 --merge
    $PY mask_ap.py --split dev
    $PY mask_ap.py --split test1
    pause "data_out/mask_audit_test1.csv: spot-check ~10 encounters (rerun mask_ap.py --split X --redo if many are wrong)" ;;
  traindata)
    $PY plant_errors.py --split train && $PY plant_errors.py --split train --merge --accept-all
    $PY mask_ap.py --split train
    FEATURE_GROUNDING=off $PY make_chain_training_data.py ;;
  train)
    $PY train_verifier.py --data data_out/chain_train.jsonl --out models/verifier_qlora ${TRAIN_FLAGS:-} ;;
  dev)   conds_dev ;;
  tune)
    $PY evaluate_rq2.py --split dev --tune
    $PY evaluate_rq2.py --split dev --setting full
    echo ">>> pick K_REF (U4 k) and K_TURN (U2 top-k) from reports/dev/metrics.md, set them in rq2.env" ;;
  test)  conds_test ;;
  eval)
    NEXT=steps
    $PY evaluate_rq2.py --split test1 --setting preap
    $PY evaluate_rq2.py --split test1 --setting full
    $PY annotate_steps.py export --split test1 --run U4_preap_ref${K_REF}_link-llm_${V} --n 60
    pause "data_out/steps_test1_U4_preap_ref${K_REF}_link-llm_${V}.csv: fill the 'gold' column" ;;
  steps)
    $PY annotate_steps.py score --split test1 --run U4_preap_ref${K_REF}_link-llm_${V} \
        --turn-run U2_preap_top${K_TURN}_${V} ;;
  smoke) bash tests/smoke_test.sh ;;
  *) sed -n 2,17p "$0"; exit 1 ;;
esac
