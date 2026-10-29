# uMedSum Stage 3: Missing Information Addition (Paper SOTA)

Implements **Stage 3: Missing Information Addition (Informativeness)** from *uMedSum (Nagar et al., ACL 2025, Section 3.3 & Appendix A.2-A.3, A.6-A.7)*.

---

## Methodology

1. **Step 3A (Key Information Extraction):**
   - **From Source Dialogue:** Uses Sentence-BERT (`all-MiniLM-L6-v2`) with Maximal Marginal Relevance (MMR) to extract the top $M$ key sentences.
     $$\mathbf{top}M = \mathbf{2} \quad \text{(Paper Appendix A.7, Eq. 6)}$$
   - **From Stage 2 Summary:** Uses **KeyBERT** to extract top $N$ key n-gram phrases ($K_{\text{summ}}$).
2. **Step 3B (Missing Key Information Detection):**
   - Computes embedding similarities between document key sentences and summary key phrases.
   - Coverage score: $\text{cov}_i^{\text{score}} = \max_j \{ \text{sim}(k_i^{\text{doc}}, k_j^{\text{summ}}) \}$.
   - **Threshold:**
     $$\mathbf{cov}_{\text{min}} = \mathbf{0.4} \quad \text{(Paper Appendix A.7, Eq. 7)}$$
   - Any key sentence with $\text{cov}_i^{\text{score}} \le 0.4$ is marked as missing.
3. **Step 3C (Perplexity-Guided Merging):**
   - Uses **GPT-2** to calculate text perplexity for candidate insertion positions across the summary:
     $$l^* = \arg\min_{l \in \text{locs}} \text{PPL}_{\text{GPT-2}}(k_{\text{missing}}, \text{summary}, l)$$
   - Inserts at position $l^*$ with minimum perplexity to ensure fluent, coherent clinical text.

---

## Files in `stage_3/`

- `key_extractor.py`: Sentence-BERT MMR ranking for dialogue sentences + KeyBERT keyphrase extraction.
- `missing_detector.py`: Embedding similarity matrix computation and coverage thresholding ($\text{cov}_{\text{min}}=0.4$).
- `perplexity_merger.py`: GPT-2 fluency scorer and optimal insertion position finder.
- `stage3_runner.py`: CLI runner that reads `stage_2/stage2_output.json` and outputs final `stage_3/stage3_output.json`.

---

## How to Run Stage 3

### Quick Test (1 sample verification)
```powershell
python stage_3/stage3_runner.py --limit 1
```

### Full Stage 3 Run
```powershell
python stage_3/stage3_runner.py `
  --input-json stage_2/stage2_output.json `
  --output-json stage_3/stage3_output.json
```

---

## Output Fields in `stage3_output.json`

- `stage3_summary`: The final, complete, faithful and informative clinical summary.
- `stage3_key_sentences_extracted`: Key sentences identified from dialogue.
- `stage3_missing_sentences_added`: Sentences identified as missing and safely merged.
- `stage3_coverage_scores`: Diagnostic similarity scores for auditing.
- `stage3_insertions`: Detailed PPL insertion locations.
