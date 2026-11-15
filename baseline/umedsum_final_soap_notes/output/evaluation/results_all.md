# RQ1 results - all split (200 cases)

Full SOAP: Subjective, Objective and Assessment/Plan are all scored.

## Similarity to the ground-truth SOAP note (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| subj_rouge1_f | 0.4369 | 0.4269 | 0.4294 |
| subj_rouge2_f | 0.2363 | 0.2057 | 0.2054 |
| subj_rougeLsum_f | 0.3531 | 0.3569 | 0.3585 |
| subj_bertscore_f1 | 0.8763 | 0.8677 | 0.8676 |
| soap_rouge1_f | 0.418 | 0.3832 | 0.3856 |
| soap_rouge2_f | 0.1804 | 0.1256 | 0.1267 |
| soap_rougeLsum_f | 0.3654 | 0.3403 | 0.3425 |
| soap_bertscore_f1 | 0.8592 | 0.8394 | 0.8399 |
| ap_rouge1_f | 0.3278 | 0.2864 | 0.2876 |
| ap_rouge2_f | 0.1009 | 0.0596 | 0.06 |
| ap_rougeLsum_f | 0.2506 | 0.2313 | 0.2323 |
| ap_bertscore_f1 | 0.8352 | 0.802 | 0.8023 |

## Fact coverage vs the ground-truth SOAP note (higher is better)

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| atomic_fact_recall | 0.5081 | 0.5061 | 0.5142 |
| critical_fact_recall | 0.4943 | 0.4938 | 0.4975 |
| recall_of_recoverable_facts | 0.6862 | 0.6581 | 0.6711 |

## Grounding in the conversation

| metric | A_stage1 | B_verified | C_final |
|---|---|---|---|
| supported_rate | 0.5679 | 0.6293 | 0.6329 |
| unsupported_claim_rate | 0.3671 | 0.339 | 0.3357 |
| contradiction_rate | 0.0386 | 0.1195 | 0.1187 |
| mean_entailment | 0.6563 | 0.6898 | 0.6927 |
| num_claims | 5679 | 12969 | 13112 |

## Stage 3 / Ask / integrity metrics

| metric | value |
|---|---|
| valid_claim_retention_proxy | 0.8198 |
| gap_detection_recall | 0.0188 |
| gap_detection_precision | 0.1395 |
| fact_recovery_rate | 0.0794 |
| unsupported_addition_rate | 0.1744 |
| duplicate_addition_rate | 0.4419 |
| num_genuine_omissions | 693 |
| num_added | 86 |
| question_redundancy_rate | None |
| questions_kept | 0 |
| gap_resolution_rate | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9819 |
| ap_unchanged_rate | not recorded (re-run to record) |

Notes: NLI-based rates are automatic proxies; validate on annotation_claims.csv. Reference SOAP note (S, O, A/P) used only for reference metrics and fact extraction. gap_resolution_rate needs recorded follow-up answers.
