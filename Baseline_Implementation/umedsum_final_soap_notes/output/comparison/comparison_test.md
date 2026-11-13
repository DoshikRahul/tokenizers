# uMedSum vs Verify-and-Ask - test split
uMedSum cases: 88 | Verify-and-Ask cases: 88 | eval NLI: MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli / MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli
S/O only; A/P is passed through unchanged in both systems and is not scored.

| metric | uMedSum S1 (gen) | uMedSum S2 (RTB-TS) | uMedSum S3 final | Ours A (Stage 1) | Ours B (verified) | Ours C final | better |
|---|---|---|---|---|---|---|---|
| so_rouge1_f | 0.4549 | 0.4175 | 0.4197 | 0.4533 | 0.4545 | 0.5044 | ours |
| so_rouge2_f | 0.2346 | 0.1704 | 0.1705 | 0.2124 | 0.2132 | 0.2327 | ours |
| so_rougeL_f | 0.2941 | 0.2387 | 0.2371 | 0.2928 | 0.2927 | 0.2773 | ours |
| so_rougeLsum_f | 0.3909 | 0.3607 | 0.3622 | 0.398 | 0.3996 | 0.4377 | ours |
| so_bertscore_f1 | 0.8732 | 0.8523 | 0.8525 | 0.8767 | 0.8766 | 0.8783 | ours |
| subj_rouge1_f | 0.4414 | 0.428 | 0.4313 | 0.4844 | 0.4845 | 0.5136 | ours |
| subj_rouge2_f | 0.235 | 0.2038 | 0.2036 | 0.2494 | 0.2498 | 0.2531 | ours |
| subj_rougeL_f | 0.2851 | 0.2596 | 0.2586 | 0.3189 | 0.3187 | 0.2909 | ours |
| subj_rougeLsum_f | 0.3565 | 0.3574 | 0.3604 | 0.4093 | 0.41 | 0.4273 | ours |
| subj_bertscore_f1 | 0.8765 | 0.8679 | 0.8678 | 0.8836 | 0.8834 | 0.881 | ours |
| num_claims | 846 | 2090 | 2162 | 659 | 654 | 976 |  |
| supported_rate | 0.8747 | 0.6962 | 0.7049 | 0.959 | 0.9862 | 0.9877 | ours |
| uncertain_rate | 0.0414 | 0.0292 | 0.0282 | 0.0076 | 0.0107 | 0.0072 | ours |
| unsupported_claim_rate | 0.0839 | 0.2746 | 0.2669 | 0.0334 | 0.0031 | 0.0051 | ours |
| contradiction_rate | 0.0473 | 0.0976 | 0.0957 | 0.0273 | 0.0 | 0.002 | ours |
| mean_entailment | 0.9202 | 0.7514 | 0.7579 | 0.9665 | 0.9891 | 0.9908 | ours |
| atomic_fact_recall | 0.5031 | 0.4995 | 0.5169 | 0.6334 | 0.6302 | 0.7342 | ours |
| critical_fact_recall | 0.6326 | 0.647 | 0.6351 | 0.6426 | 0.638 | 0.7235 | ours |
| recall_of_recoverable_facts | 0.5868 | 0.5621 | 0.5786 | 0.7101 | 0.7073 | 0.8199 | ours |

## Task / integrity metrics (final systems)

| metric | uMedSum | Ours |
|---|---|---|
| valid_claim_retention_proxy | 0.86 | 0.9899 |
| gap_detection_recall | 0.0319 | 0.3247 |
| gap_detection_precision | 0.2174 | 0.1389 |
| fact_recovery_rate | 0.0719 | 0.4282 |
| unsupported_addition_rate | 0.1522 | 0.0 |
| duplicate_addition_rate | 0.4783 | 0.0741 |
| num_genuine_omissions | 501 | 348 |
| num_added | 46 | 324 |
| question_redundancy_rate | None | 0.3623 |
| questions_kept | 0 | 88 |
| gap_resolution_rate | n/a (no follow-up answers recorded) | n/a (no follow-up answers recorded) |
| claim_retention_rate_stage2 | 0.9906 | 0.9852 |
| ap_unchanged_rate | 1.0 | 1.0 |

## Paired comparison of final notes (88 shared cases)

| metric | uMedSum | ours | diff (ours-uMedSum) | 95% CI | Wilcoxon p | ours/tie/uMedSum wins |
|---|---|---|---|---|---|---|
| subj_rouge1_f | 0.4313 | 0.5136 | +0.0823 | [+0.063, +0.101] | 7.9e-11 | 73/0/15 |
| subj_rouge2_f | 0.2036 | 0.2531 | +0.0495 | [+0.0363, +0.0628] | 7.1e-09 | 67/0/21 |
| subj_rougeLsum_f | 0.3604 | 0.4273 | +0.0669 | [+0.0524, +0.081] | 2.3e-11 | 74/0/14 |
| so_rouge1_f | 0.4148 | 0.4994 | +0.0846 | [+0.0691, +0.1001] | 3.5e-13 | 77/0/11 |
| so_rouge2_f | 0.1711 | 0.2348 | +0.0637 | [+0.0519, +0.0754] | 3.7e-13 | 77/0/11 |
| so_rougeLsum_f | 0.3568 | 0.4321 | +0.0753 | [+0.0635, +0.0874] | 2e-14 | 82/0/6 |
| supported_rate | 0.8123 | 0.9893 | +0.177 | [+0.1312, +0.2247] | 2.1e-10 | 57/29/2 |
| unsupported_claim_rate | 0.1664 | 0.0047 | -0.1617 | [-0.2053, -0.1207] | 2.8e-10 | 55/32/1 |
| atomic_fact_recall | 0.5169 | 0.7342 | +0.2174 | [+0.16, +0.2763] | 3.9e-08 | 54/7/8 |
| critical_fact_recall | 0.6351 | 0.7235 | +0.0884 | [+0.0013, +0.176] | 0.04 | 26/20/14 |
| recall_of_recoverable_facts | 0.5786 | 0.8199 | +0.2413 | [+0.1872, +0.2966] | 1.4e-09 | 56/7/6 |

Grounding and fact-recall per-case values come from each system's own evaluate.py caches. For a strictly matched comparison, both systems should be scored in the same environment (see the optional re-scoring cell in the notebook).
