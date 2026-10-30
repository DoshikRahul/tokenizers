# RQ1 results - dev split (22 cases)

A/P is not part of any score; S/O only.

## Similarity to the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| subj_rouge1_f | 0.4453 | 0.4421 | 0.4922 |
| subj_rouge2_f | 0.2058 | 0.2019 | 0.2198 |
| subj_rougeLsum_f | 0.3731 | 0.3693 | 0.4005 |
| subj_bertscore_f1 | 0.8779 | 0.8771 | 0.8763 |
| so_rouge1_f | 0.4257 | 0.4237 | 0.489 |
| so_rouge2_f | 0.1821 | 0.1796 | 0.2095 |
| so_rougeLsum_f | 0.373 | 0.3703 | 0.4155 |
| so_bertscore_f1 | 0.8728 | 0.8722 | 0.8749 |

## Fact coverage vs the ground-truth S/O (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| atomic_fact_recall | 0.563 | 0.5608 | 0.6288 |
| critical_fact_recall | 0.6577 | 0.6577 | 0.6582 |
| recall_of_recoverable_facts | 0.6776 | 0.6776 | 0.7486 |

## Grounding in the conversation

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| supported_rate | 0.9799 | 1.0 | 1.0 |
| unsupported_claim_rate | 0.0201 | 0.0 | 0.0 |
| contradiction_rate | 0.0 | 0.0 | 0.0 |
| mean_entailment | 0.9773 | 0.9972 | 0.9976 |
| num_claims | 149 | 146 | 242 |

## Stage 3 / Ask / integrity metrics

| metric | value |
|---|---|
| valid_claim_retention_proxy | 1.0 |
| gap_detection_recall | 0.3034 |
| gap_detection_precision | 0.1173 |
| fact_recovery_rate | 0.3933 |
| unsupported_addition_rate | 0.0 |
| duplicate_addition_rate | 0.0625 |
| num_genuine_omissions | 89 |
| num_added | 96 |
| question_redundancy_rate | 0.2857 |
| questions_kept | 25 |
| gap_resolution_rate | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9832 |
| ap_unchanged_rate | 1.0 |

Notes: NLI-based rates are automatic proxies; validate on annotation_claims.csv. Reference S/O used only for reference metrics and fact extraction. gap_resolution_rate needs recorded follow-up answers.
