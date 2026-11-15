# RQ1 results - test split (159 cases)

A/P is not part of any score; S/O only.

## Similarity to the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| subj_rouge1_f | 0.4826 | 0.4823 | 0.5127 |
| subj_rouge2_f | 0.2505 | 0.2506 | 0.2538 |
| subj_rougeLsum_f | 0.4062 | 0.4057 | 0.4245 |
| subj_bertscore_f1 | 0.8845 | 0.8843 | 0.8813 |
| so_rouge1_f | 0.4535 | 0.454 | 0.5053 |
| so_rouge2_f | 0.2169 | 0.2173 | 0.2359 |
| so_rougeLsum_f | 0.3969 | 0.3972 | 0.4369 |
| so_bertscore_f1 | 0.8784 | 0.8783 | 0.8794 |

## Fact coverage vs the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| atomic_fact_recall | 0.6573 | 0.6552 | 0.7438 |
| critical_fact_recall | 0.6974 | 0.6941 | 0.7608 |
| recall_of_recoverable_facts | 0.726 | 0.7235 | 0.818 |

## Grounding in the conversation

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| supported_rate | 0.9668 | 0.9886 | 0.9908 |
| unsupported_claim_rate | 0.0253 | 0.0018 | 0.0029 |
| contradiction_rate | 0.0192 | 0.0 | 0.0011 |
| mean_entailment | 0.9744 | 0.9916 | 0.9933 |
| num_claims | 1146 | 1136 | 1746 |

## Stage 3 / Ask / integrity metrics

| metric | value |
|---|---|
| valid_claim_retention_proxy | 0.9927 |
| gap_detection_recall | 0.3225 |
| gap_detection_precision | 0.1122 |
| fact_recovery_rate | 0.436 |
| unsupported_addition_rate | 0.0 |
| duplicate_addition_rate | 0.0647 |
| num_genuine_omissions | 555 |
| num_added | 618 |
| question_redundancy_rate | 0.3374 |
| questions_kept | 108 |
| gap_resolution_rate | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9888 |
| ap_unchanged_rate | 1.0 |

Notes: NLI-based rates are automatic proxies; validate on annotation_claims.csv. Reference S/O used only for reference metrics and fact extraction. gap_resolution_rate needs recorded follow-up answers.
