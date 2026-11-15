# Task: restructure the `tokenizers` repository (the demo must keep working)

You are working in my local clone on Windows. Do the steps in order. **Stop and ask me** if any command fails or
git reports a conflict. Only make the changes listed here. **Do not push.**

Rules:
* Move folders with `git mv`.
* Do not edit any data or result file (`.json`, `.jsonl`, `.csv`, anything under `output/`, `outputs/`,
  `results/` or `work/`) or any notebook (`.ipynb`).

## 1. Back up, protect large files, get the UI folder

1. Copy the whole repository folder to `tokenizers_backup` next to it.
2. Add these lines to the root `.gitignore` (save it as plain UTF-8):
   ```
   __pycache__/
   .venv/
   *.zip
   rq2_evidence_chain/work/models/
   data/intake_simulation/output-backups/
   ```
3. Check that `git check-ignore rq2_evidence_chain/work/models/verifier_qlora/adapter_model.safetensors` prints the path.
   If it prints nothing, stop.
4. Run `git add -A` and `git commit -m "Restore RQ2 code, move docs"`.
5. Run `git pull --no-rebase origin main`. This brings in the `UI/` folder. On any conflict, stop.
6. Run `git checkout -b restructure`.

## 2. Test the demo before changing anything

1. In a virtual environment **outside** the repository, install `fastapi uvicorn httpx pydantic langgraph==1.0.4 langchain-core==1.1.0`.
2. From the repository root, with environment variables `LOAD_MODEL=0`, `HOST=127.0.0.1` and `PORT=7861`, start
   `python UI/backend/server.py` in the background.
3. Write down:
   * the `status` field of `http://127.0.0.1:7861/api/status`
   * the number of items in `/api/samples`
   * the number of `events` in `/api/samples/D2N001`
   * the HTTP status of `/`
4. Stop the server.

## 3. Move the folders

```
git mv aci-bench-corpus data/aci_bench
git mv agentic-pipeline data/intake_simulation/code
git mv agentic-pipeline-output data/intake_simulation/output
git mv Baseline_Implementation baseline
git mv verify_and_ask_pipeline rq1_verify_and_ask
git mv rq2_section_aware rq2_evidence_chain/code
git mv rq2_evidence_chain/work/final rq2_evidence_chain/outputs
git mv UI demo
```

(Create `data/intake_simulation/` first if needed.)

## 4. One README

1. Run `git rm` on every file listed by `git ls-files "*README.md"` **except** the root `README.md`.
   Keep `data/aci_bench/README.txt`.
2. Replace the root `README.md` with the README file I gave you, exactly as it is.

## 5. Fix paths (only these lines)

| File | Change |
|---|---|
| `demo/backend/server.py` | `PROJECT_DIR / "agentic-pipeline"` → `PROJECT_DIR / "data" / "intake_simulation" / "code"` |
| | `PROJECT_DIR / "aci-bench-corpus"` → `PROJECT_DIR / "data" / "aci_bench"` |
| | `PROJECT_DIR / "agentic-pipeline-output" / "soap_notes"` → `PROJECT_DIR / "data" / "intake_simulation" / "output" / "soap_notes"` |
| `demo/run_ui.sh` | comment lines only: `UI/run_ui.sh` → `demo/run_ui.sh` |
| `data/intake_simulation/code/agentic_pipeline/cli.py` | `ROOT.parent / "aci-bench-corpus"` → `ROOT.parent.parent / "aci_bench"` |
| | `ROOT.parent / "agentic-pipeline-output"` → `ROOT.parent / "output"` |
| `data/intake_simulation/code/tests/test_pipeline.py` | every `ROOT.parent / "aci-bench-corpus"` → `ROOT.parent.parent / "aci_bench"` |
| `rq2_evidence_chain/code/config.py` | `REPO = ROOT.parent` → `REPO = ROOT.parent.parent` |
| | `REPO / "aci-bench-corpus" / "challenge_data"` → `REPO / "data" / "aci_bench" / "challenge_data"` |
| | `REPO / "agentic-pipeline-output" / "soap_notes"` → `REPO / "data" / "intake_simulation" / "output" / "soap_notes"` |
| `rq2_evidence_chain/code/run_rq2.py` | `"Baseline_Implementation"` → `"baseline"` |
| `rq2_evidence_chain/code/build_dataset_va.py`, `signoff.py`, `patient_summary.py` | `"verify_and_ask_pipeline"` → `"rq1_verify_and_ask"` |
| `baseline/umedsum_final_soap_notes/run_umedsum_soap.py` | `"Baseline_Implementation"` → `"baseline"` (2 places) and `"verify_and_ask_pipeline"` → `"rq1_verify_and_ask"` |
| `rq1_verify_and_ask/run_local.ps1` | the `DATASET_ROOT` line → `$env:DATASET_ROOT = Join-Path (Split-Path $Root -Parent) "data\intake_simulation\output\soap_notes"` |

Leave every other line in these files unchanged, especially `UI_DIR`, `PROJECT_DIR` and the `sys.path` lines in `server.py`.

## 6. Checklist (report PASS or FAIL for each, with the output)

1. **Demo:** repeat step 2, but start `python demo/backend/server.py`. All four values must match the ones you
   wrote down (expected: `disabled`, `207`, the same events count, `200`).
2. **Demo live wiring:** from `demo/backend`, with `LOAD_MODEL=0`, run
   `python -c "import server; print(server.load_encounters(server.DATASET_DIR,'train','D2N001',1)[0].encounter_id, (server.QWEN_SETUP_DIR/'host.py').exists())"`.
   It must print `D2N001 True`.
3. **RQ2 paths:** from `rq2_evidence_chain/code`, run `python -c "import config as C; print(C.ACI_DIR.exists(), C.AGENTIC_OUT.exists())"`.
   It must print `True True`.
4. **Intake paths:** from `data/intake_simulation/code`, run
   `python -c "from pathlib import Path; from agentic_pipeline.dataset import load_encounters; print(len(load_encounters(Path('../../aci_bench'),'all',None,0)))"`.
   It must print `207`.
5. **Code compiles:** run `python -m compileall -q data baseline rq1_verify_and_ask rq2_evidence_chain/code demo`.
   It must show no errors.
6. **No old names left in code:** search `.py`, `.sh` and `.ps1` files for `aci-bench-corpus`,
   `agentic-pipeline-output`, `Baseline_Implementation`, `verify_and_ask_pipeline` and `rq2_section_aware`, but only
   in **code lines**, not comments. Expected: none.
7. **Only planned changes:** run `git status --short`. Apart from renames (`R`), only `.gitignore`, `README.md`, the
   files in step 5 and the deleted READMEs may appear. No file under `work/models/` may be staged.
8. **Old folders gone, new ones present:** check `data/aci_bench`, `data/intake_simulation/code`,
   `data/intake_simulation/output`, `baseline`, `rq1_verify_and_ask`, `rq2_evidence_chain/code`,
   `rq2_evidence_chain/outputs` and `demo`.
9. Delete any `__pycache__` folders created inside the repository.

When everything passes, commit with the message `Restructure repository and add single README`. Show me the
checklist results and the push command (`git push origin restructure`). **Do not push.**
