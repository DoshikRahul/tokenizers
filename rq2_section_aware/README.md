# RQ2: Section-aware verification of Assessment/Plan statements

Does checking A/P statements through their evidence chain keep more valid clinical reasoning than
uniform entailment, while still rejecting unsupported diagnoses and plans (H2)?

All conditions score the **same frozen statement set**. **Rejection = flag or delete** for every
condition, so evidence-chain verification cannot win by never deleting.

## Conditions

| ID | What it is | Script |
|---|---|---|
| U1 | DeBERTa-v3-large NLI + uMedSum RTB-TS (Te 0.9 / Tc 0.8 / Ta 0.5, baseline's LLaMA-3-8B decomposer) | `run_rq2.py --condition U1` |
| U2 | Same uniform-entailment rule, our verifier (Qwen2.5-3B + QLoRA) | `--condition U2` |
| U3 | Evidence chain: features → grounding → components → links → verifier judges `chain_ok/chain_broken` | `--condition U3` |
| U4 | U3 + MedlinePlus passages (BM25 + dense, RRF, k ∈ {1,3,5} tuned on dev) | `--condition U4 --k 3` |
| S2 | U2 on top-k retrieved turns instead of the whole dialogue | `--condition U2 --evidence topk --k 5` |
| S3 | U3 vs U4 (decision changes listed) | `evaluate_rq2.py` → `s3_decision_changes.csv` |
| S1 | DeBERTa vs QLoRA-3B vs prompted 7B, macro-F1 per error type, s/claim | `s1_verifier_compare.py` |
| Linker control | U3/U4 with retrieval linking instead of the generator LLM | `LINKER=retrieval` |
| Evidence setting | `--setting preap` (primary) vs `--setting full` | all conditions |

P1 (valid-claim retention) and P2 (unsupported rejection P/R) are metrics of the U1–U4 runs, not
separate runs.

### Why `--setting preap` is the primary setting
In ACI-Bench the doctor dictates the assessment and plan aloud, so reference A/P statements are often
literally entailed by the full dialogue. In our system A/P is written after the intake freeze, so the
evidence never contains the doctor's conclusions. `mask_ap.py` removes the doctor's spoken
diagnoses/plans (keeping history, exam findings, results, patient preferences). `--setting full` is
reported as a secondary result; it shows how much of uniform entailment's retention comes from the
doctor saying the plan out loud.

## Data
- Valid set: reference A/P statements of ACI-Bench (dev = `valid`, test = `test1`), paired with the
  **original** dialogue (`build_dataset.py`). Boilerplate ("patient understands and agrees") excluded.
- Unsupported set: planted per encounter by a different LLM (`plant_errors.py`): `unsupported_diagnosis`,
  `plan_without_evidence` (proposal E2 types 5–6) and `contradicted_inference` (hard negative).
- Human checks (CSV sheets in `data_out/`): `audit_valid_*.csv` (is each reference statement really
  supported; is the A/P section right), `planted_candidates_*.csv` (approve planted errors),
  `mask_audit_*.csv` (masking correct), `steps_*.csv` (per-step gold).

## Run order
```bash
pip install -r requirements.txt
export GEN_BASE_URL=http://HOST:PORT/v1 GEN_MODEL=Qwen3-14B GEN_API_KEY=...     # generator (not the verifier)
export VERIFIER_BACKEND=hf VERIFIER_ADAPTER=/path/to/qlora_adapter              # the 3B verifier

python build_dataset.py --splits dev test1
python plant_errors.py --split dev   && python plant_errors.py --split dev --merge --accept-all
python plant_errors.py --split test1 # review 'approved' column, then:
python plant_errors.py --split test1 --merge
python mask_ap.py --split dev && python mask_ap.py --split test1
python medlineplus.py                                   # reference corpus for U4

for s in dev test1; do
  python run_rq2.py --condition U1 --split $s
  python run_rq2.py --condition U2 --split $s
  for k in 1 3 5; do python run_rq2.py --condition U2 --split $s --evidence topk --k $k; done
  python run_rq2.py --condition U3 --split $s
  for k in 1 3 5; do python run_rq2.py --condition U4 --split $s --k $k; done
done
python evaluate_rq2.py --split dev --tune      # thresholds per run; pick k from the dev table; then freeze
python evaluate_rq2.py --split test1           # metrics, curves, paired bootstrap, McNemar+Holm, H2

python annotate_steps.py export --split test1 --run U4_preap_ref3_link-llm_hf --n 60   # fill 'gold'
python annotate_steps.py score  --split test1 --run U4_preap_ref3_link-llm_hf --turn-run U2_preap_top5_hf
```
Runs are resumable (`runs/<split>/<run>.jsonl`). `bash tests/smoke_test.sh` runs everything offline
with stub models to check the plumbing.

## Verifier training data (A/P half)
`make_chain_training_data.py` builds `chain_ok/chain_broken` pairs from ACI-Bench **train** only, in
the exact prompt format used at test time (`prompts.py`). The QLoRA trainer must use the same prompt
builders and label strings (`config.LABELS_*`).

## Outputs (`reports/<split>/`)
`metrics.md/.csv` (retention, rejection P/R/F1, flag rate, AUC, s/claim; all / Assessment / Plan),
`recall_by_error_type.csv`, `tradeoff_curves.csv` (retention vs recall over thresholds),
`s3_decision_changes.csv`, `summary.json` (paired comparisons, Holm-adjusted p, H2 verdict, U4
reference coverage).

## Known limitations
- The generator LLM (features, components, links) is larger than the verifier; the `LINKER=retrieval`
  run checks the gain is not from the generator.
- `p_reject` from the OpenAI backend is only continuous if the server returns logprobs.
- Statement segmentation and A/P typing of ACI notes are heuristic; `audit_valid_*.csv` corrects them.
