# RQ1 results - dev split (22 cases)

A/P is not part of any score; S/O only.

## Similarity to the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| subj_rouge1_f | 0.4297 | 0.4201 | 0.4265 |
| subj_rouge2_f | 0.2213 | 0.1839 | 0.1866 |
| subj_rougeLsum_f | 0.3433 | 0.3431 | 0.3468 |
| subj_bertscore_f1 | 0.8726 | 0.8649 | 0.8651 |
| so_rouge1_f | 0.4263 | 0.4172 | 0.422 |
| so_rouge2_f | 0.2147 | 0.1615 | 0.1641 |
| so_rougeLsum_f | 0.3593 | 0.3502 | 0.3531 |
| so_bertscore_f1 | 0.8667 | 0.8516 | 0.8523 |

## Fact coverage vs the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| atomic_fact_recall | 0.4089 | 0.4851 | 0.5052 |
| critical_fact_recall | 0.5357 | 0.6306 | 0.605 |
| recall_of_recoverable_facts | 0.5003 | 0.5765 | 0.6072 |

## Grounding in the conversation

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| supported_rate | 0.8462 | 0.6699 | 0.6767 |
| unsupported_claim_rate | 0.1041 | 0.3045 | 0.2987 |
| contradiction_rate | 0.0633 | 0.169 | 0.1664 |
| mean_entailment | 0.9022 | 0.7385 | 0.7439 |
| num_claims | 221 | 509 | 529 |

## Stage 3 / Ask / integrity metrics

| metric | value |
|---|---|
| valid_claim_retention_proxy | 0.9338 |
| gap_detection_recall | 0.0097 |
| gap_detection_precision | 0.0909 |
| fact_recovery_rate | 0.0874 |
| unsupported_addition_rate | 0.0 |
| duplicate_addition_rate | 0.4545 |
| num_genuine_omissions | 103 |
| num_added | 11 |
| question_redundancy_rate | None |
| questions_kept | 0 |
| gap_resolution_rate | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9886 |
| ap_unchanged_rate | 1.0 |

Notes: NLI-based rates are automatic proxies; validate on annotation_claims.csv. Reference S/O used only for reference metrics and fact extraction. gap_resolution_rate needs recorded follow-up answers.
