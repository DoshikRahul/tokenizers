# RQ1 pipeline: Stage 2-3 controller + evaluation (inference only)

Input: `stage1_pipeline/.../stage1/stage1_output.json` (needs `stage1_so`, `stage1_ap`, `split`).
No model is trained. LLaMA3-8B (Ollama), DeBERTa-v3 NLI, MiniLM and GPT-2 are used as-is.

```
conversation + Stage 1 S/O
  -> verification.py   atomic claims -> NLI vs conversation -> keep / flag / correct / remove  (+ audit log)
  -> omission.py       candidates -> coverage (MiniLM) -> validation (rewrite + NLI + duplicate check)
                       -> insertion (GPT-2 placement)
  -> ask.py            unresolved gaps -> targeted questions (status "unresolved"; nothing invented)
  -> controller.py     finalizer: stage1_so / stage2_so / stage3_so, A/P unchanged, all audit logs
evaluate.py            separate: systems A (Stage 1), B (+verification), C (+omission/ask)
```

The ground-truth note is never passed to a generator, verifier, detector or question module.
`run_stage23.py` copies `reference_so` into each output record only so `evaluate.py` can find it.

## Run (Colab or local, Ollama running with llama3:8b)

```bash
pip install -r requirements.txt
export STAGE1_OUTPUT_JSON=/path/to/stage1_output.json   # default: ../stage1_pipeline/.../stage1_output.json
python run_stage23.py --limit 3 --no-ask --no-gpt2       # smoke test
python run_stage23.py --split dev                        # tune thresholds on dev
python evaluate.py --split dev
python run_stage23.py --split test                       # freeze thresholds first
python evaluate.py --split test
```

Checkpoints are written per case to `output/cases/`; re-running resumes.

## Thresholds to tune on dev, then freeze (`config.py`, or env vars)
`TE`, `TA`, `TCONTRA` (Stage 2), `COV_MIN` (0.4 is a starting heuristic), `ADD_ENTAIL_MIN`,
`DUP_ENTAIL_MIN`.

Unsupported claims are taken out of the note but saved per case in `output/unsupported_claims/<case>.json`
(Stage 2 removed claims, Stage 2 flagged-but-kept claims, Stage 3 rejected candidates).

## Evaluation outputs (`output/evaluation/`)
- `results_<split>.json`: per-system ROUGE-1/2/L/Lsum, BERTScore, claim-level supported / uncertain /
  unsupported / contradiction rates, mean entailment, atomic and critical fact recall; task metrics
  (valid-claim retention proxy, gap-detection precision/recall, fact recovery, unsupported/duplicate
  additions, question redundancy, gap resolution).
- `annotation_claims.csv`, `annotation_questions_and_additions.csv`: samples for human labels.
- `reference_facts.json`: LLM-extracted facts from the reference S/O (evaluation only; spot-check by hand).

## Limitations to state in the write-up
- NLI rates are proxies. Use `--eval-nli-model` with a different NLI model than the verifier, and check
  agreement with the human-labelled sample.
- Fact recall depends on the LLM fact extraction and the NLI "represented" threshold.
- Gap resolution is only measurable with recorded follow-up answers (`--answers`); otherwise report
  question quality and unresolved gaps.
- SummaC is optional (`--summac`, needs `pip install summac`). QuestEval is not wired in here; reuse the
  baseline `evaluate_metrics.py` if you need it.
- Not yet run against real models; only the verification decision logic was tested with stubs.
