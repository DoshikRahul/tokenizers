# Baseline: uMedSum

## The idea in one paragraph

A doctor talks with a patient, and a computer writes the visit note (a **SOAP note**: **S**ubjective = what
the patient says, **O**bjective = what is measured or examined, **A**ssessment = the diagnosis,
**P**lan = what to do next). Computers sometimes write things into the note that were never said. **uMedSum**
(Nagar et al., ACL 2025) is a published method that cleans a finished note: it checks every sentence against
the conversation, deletes sentences the conversation does not support, and adds back important things the
note missed. This folder holds our re-implementation of uMedSum. It is the **baseline**: the existing method
that our own approach (Verify-and-Ask, in `verify_and_ask_pipeline/`) is compared against.

## What the baseline does, step by step

1. **Write** a full SOAP note from the conversation (LLaMA-3-8B, with one worked example shown to it).
2. **Check and delete** (uMedSum calls this RTB-TS): each sentence is tested with an NLI model
   (DeBERTa-v3-large), which answers "does the conversation say this?". Clearly supported sentences stay,
   clearly unsupported ones are removed, and unclear ones are split into small facts that are tested one by one.
3. **Add back** missing information: important conversation sentences that the note does not cover are found
   (MiniLM similarity, MMR, KeyBERT) and inserted where they read most naturally (GPT-2).

All four parts (S, O, A and P) go through steps 2 and 3, as in the original paper.

## Which data

- **201 simulated doctor–patient conversations**, produced by our multi-agent intake
  (`agentic-pipeline-output/soap_notes/<case>/consultation.md`). These are exactly the same 201 conversations
  that Verify-and-Ask uses. ACI-Bench has 207 encounters; 6 were skipped when the dataset was prepared
  (D2N030, D2N051, D2N086, D2N101, D2N108, D2N110).
- **Scored on 200 cases**: `D2N002` is left out of all scores because it is the worked example shown to the
  note writer in step 1.
- The reference note for each case (used only for scoring, never as an input) is the intake's own SOAP note.

## Headline results (200 cases, full SOAP note)

| What it measures (plain words) | After step 1 (write) | After step 3 (final) |
|---|---|---|
| Subjective: word overlap with the reference (ROUGE-1) | 0.437 | 0.429 |
| Assessment/Plan: word overlap with the reference (ROUGE-1) | 0.328 | 0.288 |
| Share of reference facts found in the note (atomic fact recall) | 0.508 | 0.514 |
| Share of note sentences the conversation supports (supported rate) | 0.568 | 0.633 |
| Share of note sentences the conversation contradicts (contradiction rate) | 0.039 | 0.119 |

Full tables: `umedsum_final_soap_notes/output/evaluation/results_all.md`.

The Assessment/Plan overlap drops after checking: uMedSum deletes diagnoses and plans because nobody says
them word for word in the conversation. This is the problem our RQ2 (section-aware verification) addresses.

## Comparing with Verify-and-Ask: two cautions

- **Different scope.** This baseline is scored on the full note (S, O, A and P); Verify-and-Ask's own results
  are scored on S and O only. Grounding rates and fact recall are therefore not directly comparable. Subjective
  ROUGE/BERTScore are measured the same way in both and can be compared.
- **Different dev/test split.** Both used seed 42, but this run split 40 dev / 160 test, Verify-and-Ask
  42 dev / 159 test (30 cases differ). Compare on the same cases, e.g. all 200.

## Folder guide

```
Baseline_Implementation/
├── README.md                          this file
├── umedsum_baseline_full_soap.ipynb   Colab notebook that ran the main baseline (201 cases, full SOAP) and scored it
├── aci_init_umedsum_baseline.ipynb    earlier Colab notebook: first uMedSum run on ACI-Bench dialogues
│
├── umedsum_final_soap_notes/          ★ THE MAIN BASELINE (the one compared with Verify-and-Ask)
│   ├── run_umedsum_soap.py            runs steps 1–3 on the 201 conversations
│   │                                  (--scope soap = all of S, O, A, P; --scope so = S and O only)
│   ├── evaluate_full_soap.py          scores the full note; reuses the project scorer
│   │                                  (verify_and_ask_pipeline/Stage23_pipeline/code/evaluate.py) without changing it
│   └── output/
│       ├── data/prepared_dataset.json      the 201 conversations + reference notes used as input
│       ├── final_notes/<case>.md           the final note for each case, readable
│       ├── cases/<case>.json               everything about one case: note after each step, what was deleted and why, what was added
│       ├── umedsum_output.json             all 201 cases in one file
│       ├── umedsum_output_scoring.json     the same, without D2N002 (the 200 scored cases)
│       └── evaluation/
│           ├── results_all.md / .json      the score tables
│           ├── umedsum_scores_full_soap.csv       the same scores as a spreadsheet
│           ├── umedsum_task_metrics_full_soap.csv extra counts (facts added, claims kept, …)
│           ├── reference_facts.json        list of facts taken from each reference note (the answer key for fact recall)
│           ├── annotation_claims.csv       sample of checked sentences for a person to label by hand
│           ├── annotation_questions_and_additions.csv  sample of added sentences for hand labelling
│           └── *_cache_*.json              saved model scores, so re-scoring is fast
│
├── umedsum_pipeline_baseline/         the core uMedSum code, one folder per step, plus the first
│   │                                  reproduction on original ACI-Bench dialogues (140 encounters, mid-point report)
│   ├── stage_1/                       step 1: element extraction + note writing (prompts.py, stage1_generator.py)
│   ├── stage_2/                       step 2: NLI checking and deleting (nli_scorer.py, atomic_decomposer.py, confabulation_remover.py)
│   ├── stage_3/                       step 3: finding and inserting missing information (key_extractor.py, missing_detector.py, perplexity_merger.py)
│   ├── run_all_stages.py              runs steps 1 → 2 → 3 → scoring on ACI-Bench
│   ├── evaluate_metrics.py            ROUGE, BERTScore, SummaC, QuestEval for that run
│   ├── results/                       outputs and scores of the ACI-Bench reproduction
│   └── summac_conv_vitc_sent_perc_e.bin   small helper file for the SummaC score
│
└── aci_dataset_rq1_baseline/          ACI-Bench data prepared for the ACI-Bench reproduction
    ├── prepare_datasets.py            builds the files below
    ├── icl_examples.json              the fixed worked examples shown to the note writer
    ├── test_only/test.json            ACI-Bench test1–3 (120 encounters)
    └── test+val/                      test + validation (140 encounters)
```

## Models

| Role | Model |
|---|---|
| Note writing, splitting sentences into facts | LLaMA-3-8B-Instruct (Q8, via Ollama) |
| "Does the conversation say this?" | DeBERTa-v3-large NLI (MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli) |
| Similarity for finding missing information | all-MiniLM-L6-v2 |
| Choosing where to insert added sentences | GPT-2 |

Thresholds from the paper: keep if entailment > 0.9, delete if neutral + contradiction > 0.8, otherwise split
into facts and keep facts with entailment > 0.5.

## How to re-run

Open `umedsum_baseline_full_soap.ipynb` in Google Colab (GPU runtime) with the repository on Google Drive and
run the cells in order. Runs are saved per case, so an interrupted run continues where it stopped.
