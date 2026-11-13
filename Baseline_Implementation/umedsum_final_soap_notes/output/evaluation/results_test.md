# RQ1 results - test split (88 cases)

A/P is not part of any score; S/O only.

## Similarity to the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| subj_rouge1_f | 0.4414 | 0.428 | 0.4313 |
| subj_rouge2_f | 0.235 | 0.2038 | 0.2036 |
| subj_rougeLsum_f | 0.3565 | 0.3574 | 0.3604 |
| subj_bertscore_f1 | 0.8765 | 0.8679 | 0.8678 |
| so_rouge1_f | 0.4549 | 0.4175 | 0.4197 |
| so_rouge2_f | 0.2346 | 0.1704 | 0.1705 |
| so_rougeLsum_f | 0.3909 | 0.3607 | 0.3622 |
| so_bertscore_f1 | 0.8732 | 0.8523 | 0.8525 |

## Fact coverage vs the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| atomic_fact_recall | 0.5031 | 0.4995 | 0.5169 |
| critical_fact_recall | 0.6326 | 0.647 | 0.6351 |
| recall_of_recoverable_facts | 0.5868 | 0.5621 | 0.5786 |

## Grounding in the conversation

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| supported_rate | 0.8747 | 0.6962 | 0.7049 |
| unsupported_claim_rate | 0.0839 | 0.2746 | 0.2669 |
| contradiction_rate | 0.0473 | 0.0976 | 0.0957 |
| mean_entailment | 0.9202 | 0.7514 | 0.7579 |
| num_claims | 846 | 2090 | 2162 |

## Stage 3 / Ask / integrity metrics

| metric | value |
|---|---|
| valid_claim_retention_proxy | 0.86 |
| gap_detection_recall | 0.0319 |
| gap_detection_precision | 0.2174 |
| fact_recovery_rate | 0.0719 |
| unsupported_addition_rate | 0.1522 |
| duplicate_addition_rate | 0.4783 |
| num_genuine_omissions | 501 |
| num_added | 46 |
| question_redundancy_rate | None |
| questions_kept | 0 |
| gap_resolution_rate | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9906 |
| ap_unchanged_rate | 1.0 |

Notes: NLI-based rates are automatic proxies; validate on annotation_claims.csv. Reference S/O used only for reference metrics and fact extraction. gap_resolution_rate needs recorded follow-up answers.
