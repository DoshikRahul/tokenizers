# uMedSum Stage 2: Confabulation Removal (Paper SOTA)

Implements **Stage 2: Confabulation Removal (Faithfulness)** from *uMedSum (Nagar et al., ACL 2025, Section 3.2 & Appendix A.7)*.

---

## Methodology: Recursive Threshold-Based Text Segmentation (RTB-TS)

1. **Sentence Boundary Segmentation:** Decomposes the Stage 1 summary into Decomposed Summary Units (DSUs) $D_k$ using **PySBD** (`pysbd`).
2. **Pairwise NLI Scoring:** Evaluates each DSU against the full dialogue using the paper's best performing model:
   - **Model:** `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`
   - Handles long dialogues by chunked max-entailment pooling.
3. **Threshold-Based Classification:**
   - **Faithful:** $E(D_k) > T_e \ (0.9)$ $\rightarrow$ Retained.
   - **Confabulated:** $N(D_k) + C(D_k) > T_c \ (0.8)$ $\rightarrow$ Dropped.
   - **Uncertain:** Otherwise $\rightarrow$ Sent to Recursive Decomposition.
4. **Recursive Atomic Decomposition:**
   - Decomposes uncertain sentences into atomic standalone facts using the Stage 1 model (LLaMA 3 via Ollama).
   - Re-evaluates each atomic fact with DeBERTa NLI using atomic threshold $T_a = 0.5$.
   - Retains atomic facts with $E(D_{k,a}) > 0.5$.
5. **Aggregation:** Concatenates all faithful units into `stage2_summary`.

---

## Files in `stage_2/`

- `nli_scorer.py`: DeBERTa-v3-large inference with dialogue premise chunking and max-entailment pooling.
- `atomic_decomposer.py`: Clinical atomic fact decomposition using LLaMA 3 via Ollama (with clause-splitting fallback).
- `confabulation_remover.py`: Core RTB-TS algorithm and threshold classification.
- `stage2_runner.py`: CLI runner that reads `stage1_output.json` and outputs `stage2_output.json`.

---

## How to Run Stage 2

### Quick Test (1 sample verification)
```powershell
python stage_2/stage2_runner.py --limit 1
```

### Full Stage 2 Run
```powershell
python stage_2/stage2_runner.py `
  --input-json stage_1/stage1_output.json `
  --output-json stage_2/stage2_output.json
```

---

## Output Fields in `stage2_output.json`

- `stage2_summary`: Cleaned summary free of confabulated facts.
- `stage2_faithful_units`: List of validated sentences/facts retained.
- `stage2_confabulated_units`: List of identified confabulations removed.
- `stage2_uncertain_units`: List of units decomposed into atomic facts.
- `stage2_details`: Complete per-sentence probabilities ($E, N, C$) for auditable verification.
