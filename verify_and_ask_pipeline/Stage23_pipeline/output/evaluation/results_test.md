# RQ1 results - test split (88 cases)

A/P is not part of any score; S/O only.

## Similarity to the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| subj_rouge1_f | 0.4844 | 0.4845 | 0.5136 |
| subj_rouge2_f | 0.2494 | 0.2498 | 0.2531 |
| subj_rougeLsum_f | 0.4093 | 0.41 | 0.4273 |
| subj_bertscore_f1 | 0.8836 | 0.8834 | 0.881 |
| so_rouge1_f | 0.4533 | 0.4545 | 0.5044 |
| so_rouge2_f | 0.2124 | 0.2132 | 0.2327 |
| so_rougeLsum_f | 0.398 | 0.3996 | 0.4377 |
| so_bertscore_f1 | 0.8767 | 0.8766 | 0.8783 |

## Fact coverage vs the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| atomic_fact_recall | 0.6334 | 0.6302 | 0.7342 |
| critical_fact_recall | 0.6426 | 0.638 | 0.7235 |
| recall_of_recoverable_facts | 0.7101 | 0.7073 | 0.8199 |

## Grounding in the conversation

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| supported_rate | 0.959 | 0.9862 | 0.9877 |
| unsupported_claim_rate | 0.0334 | 0.0031 | 0.0051 |
| contradiction_rate | 0.0273 | 0.0 | 0.002 |
| mean_entailment | 0.9665 | 0.9891 | 0.9908 |
| num_claims | 659 | 654 | 976 |

## Stage 3 / Ask / integrity metrics

| metric | value |
|---|---|
| valid_claim_retention_proxy | 0.9899 |
| gap_detection_recall | 0.3247 |
| gap_detection_precision | 0.1389 |
| fact_recovery_rate | 0.4282 |
| unsupported_addition_rate | 0.0 |
| duplicate_addition_rate | 0.0741 |
| num_genuine_omissions | 348 |
| num_added | 324 |
| question_redundancy_rate | 0.3623 |
| questions_kept | 88 |
| gap_resolution_rate | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9852 |
| ap_unchanged_rate | 1.0 |

Notes: NLI-based rates are automatic proxies; validate on annotation_claims.csv. Reference S/O used only for reference metrics and fact extraction. gap_resolution_rate needs recorded follow-up answers.
