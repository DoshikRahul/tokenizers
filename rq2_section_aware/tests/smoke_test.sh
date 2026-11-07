#!/usr/bin/env bash
# Offline end-to-end smoke test: stub LLM, stub verifier, stub NLI, stub embedder, toy reference corpus.
# Checks plumbing only; the numbers mean nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d)
export RQ2_DATA_DIR=$TMP/data RQ2_RUNS_DIR=$TMP/runs RQ2_REPORT_DIR=$TMP/reports RQ2_REF_DIR=$TMP/ref
export GEN_BACKEND=stub VERIFIER_BACKEND=stub NLI_MODEL=stub EMBED_MODEL=stub U1_DECOMPOSER=gen N_BOOT=200

python build_dataset.py --splits dev
python plant_errors.py --split dev --limit 4
python plant_errors.py --split dev --merge --accept-all
python mask_ap.py --split dev
mkdir -p $TMP/ref
python - <<'EOF'
import json, os
rows = [dict(pid=f"p{i}", title=t, section="Summary", url="", also_called=[], text=x, index_text=f"{t}. {x}")
        for i, (t, x) in enumerate([("Hypertension", "High blood pressure is treated with lifestyle change and medicines such as lisinopril."),
                                    ("Type 2 diabetes", "Metformin is a first medicine; hemoglobin A1C tests track control."),
                                    ("Back pain", "Most low back pain gets better with rest, physical therapy and pain relievers.")])]
open(os.environ["RQ2_REF_DIR"] + "/chunks.jsonl", "w").write("\n".join(json.dumps(r) for r in rows))
EOF
for c in U1 U2 U3 U4; do python run_rq2.py --condition $c --split dev --limit 4; done
python run_rq2.py --condition U2 --split dev --limit 4 --evidence topk --k 3
python evaluate_rq2.py --split dev --tune
python evaluate_rq2.py --split dev
python annotate_steps.py export --split dev --run U4_preap_ref3_link-llm_stub --n 10
echo "SMOKE TEST OK ($TMP)"
