# RQ1 results - dev split (42 cases)

A/P is not part of any score; S/O only.

## Similarity to the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| subj_rouge1_f | 0.4602 | 0.4599 | 0.498 |
| subj_rouge2_f | 0.2219 | 0.2196 | 0.231 |
| subj_rougeLsum_f | 0.3845 | 0.383 | 0.4074 |
| subj_bertscore_f1 | 0.881 | 0.8806 | 0.8789 |
| so_rouge1_f | 0.4387 | 0.4387 | 0.4897 |
| so_rouge2_f | 0.1972 | 0.1957 | 0.2183 |
| so_rougeLsum_f | 0.3817 | 0.3809 | 0.4191 |
| so_bertscore_f1 | 0.8768 | 0.8765 | 0.8779 |

## Fact coverage vs the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| atomic_fact_recall | 0.6634 | 0.6644 | 0.7119 |
| critical_fact_recall | 0.7139 | 0.7191 | 0.7255 |
| recall_of_recoverable_facts | 0.7409 | 0.7464 | 0.788 |

## Grounding in the conversation

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| supported_rate | 0.9744 | 1.0 | 1.0 |
| unsupported_claim_rate | 0.0256 | 0.0 | 0.0 |
| contradiction_rate | 0.016 | 0.0 | 0.0 |
| mean_entailment | 0.9752 | 0.9969 | 0.9974 |
| num_claims | 313 | 308 | 456 |

## Stage 3 / Ask / integrity metrics

| metric | value |
|---|---|
| valid_claim_retention_proxy | 0.9973 |
| gap_detection_recall | 0.3206 |
| gap_detection_precision | 0.1103 |
| fact_recovery_rate | 0.3893 |
| unsupported_addition_rate | 0.0 |
| duplicate_addition_rate | 0.0604 |
| num_genuine_omissions | 131 |
| num_added | 149 |
| question_redundancy_rate | 0.2857 |
| questions_kept | 25 |
| gap_resolution_rate | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9851 |
| ap_unchanged_rate | 1.0 |

Notes: NLI-based rates are automatic proxies; validate on annotation_claims.csv. Reference S/O used only for reference metrics and fact extraction. gap_resolution_rate needs recorded follow-up answers.
