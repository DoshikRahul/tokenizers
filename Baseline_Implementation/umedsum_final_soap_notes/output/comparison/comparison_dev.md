# uMedSum vs Verify-and-Ask - dev split
uMedSum cases: 22 | Verify-and-Ask cases: 22 | eval NLI: MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli / MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli
S/O only; A/P is passed through unchanged in both systems and is not scored.

| metric | uMedSum S1 (gen) | uMedSum S2 (RTB-TS) | uMedSum S3 final | Ours A (Stage 1) | Ours B (verified) | Ours C final | better |
|---|---|---|---|---|---|---|---|
| so_rouge1_f | 0.4263 | 0.4172 | 0.422 | 0.4257 | 0.4237 | 0.489 | ours |
| so_rouge2_f | 0.2147 | 0.1615 | 0.1641 | 0.1821 | 0.1796 | 0.2095 | ours |
| so_rougeL_f | 0.2763 | 0.2324 | 0.2345 | 0.2781 | 0.2749 | 0.2624 | ours |
| so_rougeLsum_f | 0.3593 | 0.3502 | 0.3531 | 0.373 | 0.3703 | 0.4155 | ours |
| so_bertscore_f1 | 0.8667 | 0.8516 | 0.8523 | 0.8728 | 0.8722 | 0.8749 | ours |
| subj_rouge1_f | 0.4297 | 0.4201 | 0.4265 | 0.4453 | 0.4421 | 0.4922 | ours |
| subj_rouge2_f | 0.2213 | 0.1839 | 0.1866 | 0.2058 | 0.2019 | 0.2198 | ours |
| subj_rougeL_f | 0.2772 | 0.2455 | 0.2493 | 0.2957 | 0.2914 | 0.2687 | ours |
| subj_rougeLsum_f | 0.3433 | 0.3431 | 0.3468 | 0.3731 | 0.3693 | 0.4005 | ours |
| subj_bertscore_f1 | 0.8726 | 0.8649 | 0.8651 | 0.8779 | 0.8771 | 0.8763 | ours |
| num_claims | 221 | 509 | 529 | 149 | 146 | 242 |  |
| supported_rate | 0.8462 | 0.6699 | 0.6767 | 0.9799 | 1.0 | 1.0 | ours |
| uncertain_rate | 0.0498 | 0.0255 | 0.0246 | 0.0 | 0.0 | 0.0 | ours |
| unsupported_claim_rate | 0.1041 | 0.3045 | 0.2987 | 0.0201 | 0.0 | 0.0 | ours |
| contradiction_rate | 0.0633 | 0.169 | 0.1664 | 0.0 | 0.0 | 0.0 | ours |
| mean_entailment | 0.9022 | 0.7385 | 0.7439 | 0.9773 | 0.9972 | 0.9976 | ours |
| atomic_fact_recall | 0.4089 | 0.4851 | 0.5052 | 0.563 | 0.5608 | 0.6288 | ours |
| critical_fact_recall | 0.5357 | 0.6306 | 0.605 | 0.6577 | 0.6577 | 0.6582 | ours |
| recall_of_recoverable_facts | 0.5003 | 0.5765 | 0.6072 | 0.6776 | 0.6776 | 0.7486 | ours |

## Task / integrity metrics (final systems)

| metric | uMedSum | Ours |
|---|---|---|
| valid_claim_retention_proxy | 0.9338 | 1.0 |
| gap_detection_recall | 0.0097 | 0.3034 |
| gap_detection_precision | 0.0909 | 0.1173 |
| fact_recovery_rate | 0.0874 | 0.3933 |
| unsupported_addition_rate | 0.0 | 0.0 |
| duplicate_addition_rate | 0.4545 | 0.0625 |
| num_genuine_omissions | 103 | 89 |
| num_added | 11 | 96 |
| question_redundancy_rate | None | 0.2857 |
| questions_kept | 0 | 25 |
| gap_resolution_rate | n/a (no follow-up answers recorded) | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9886 | 0.9832 |
| ap_unchanged_rate | 1.0 | 1.0 |

No shared successful cases in 'dev' between the two output files, so no paired tests. (The repo's Verify-and-Ask stage23_output.json holds the 88 test cases only.)
