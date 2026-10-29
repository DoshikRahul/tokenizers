# uMedSum Stage 1: Initial Summary Generation (Paper SOTA)

Implements the **top-performing configuration** from *uMedSum (Nagar et al., ACL 2025)*:
- **Strategy:** Element-Aware Summarization (Wang et al., 2023)
  - **Step 1 (Element Extraction):** Extracts factual clinical elements (complaints, history/medications, exam/labs, assessments, treatment plan & follow-up).
  - **Step 2 (Synthesis):** Generates the Assessment and Plan conditioned on the dialogue and extracted elements.
- **Task Adaptation:** In-Context Learning (ICL) demonstrations prepended from `aci_dataset_rq1_baseline/icl_examples.json`.
- **Model:** LLaMA 3 (8B) executed locally via **Ollama**.

---

## Environment Setup (Virtual Environment)

A unified virtual environment for all pipeline stages is set up in `tokenizers_rq1/venv`.

### 1. Activating the Environment
In PowerShell from `tokenizers_rq1`:
```powershell
.\venv\Scripts\Activate.ps1
```

### 2. Requirements for All Pipeline Stages (`requirements.txt`)
The root `requirements.txt` covers all three stages and evaluation:

- **Core Deep Learning & NLP Framework:**
  - `torch`: Deep learning backend for NLI models, embeddings, and language modeling.
  - `transformers`: Hugging Face library for DeBERTa, GPT-2, and tokenizers.
  - `accelerate`: Efficient model loading and device allocation.
  - `sentencepiece`, `protobuf`: Tokenizer dependencies.

- **Stage 2 (Confabulation Removal & Sentence Segmentation):**
  - `pysbd`: Pragmatic Sentence Boundary Disambiguation (used in paper Appendix A.6 to segment summaries into units).
  - `scipy`, `numpy`: Scientific computing and probability threshold computations.

- **Stage 3 (Missing Key Information Addition):**
  - `sentence-transformers`: Sentence-BERT (`all-MiniLM-L6-v2`) for key sentence embeddings.
  - `keybert`: Keyphrase extraction using MMR ranking (paper Section 3.3 & Appendix A.2).

- **Evaluation & Benchmarking:**
  - `rouge-score`: ROUGE-Lsum metric computation.
  - `bert-score`: BERTScore semantic similarity metric.
  - `evaluate`: Hugging Face evaluation library.

- **General Utilities:**
  - `tqdm`: Progress bars.
  - `requests`: HTTP utility for Ollama connection management.

To install or update all requirements:
```powershell
pip install -r requirements.txt
```

---

## Local LLM Setup (Ollama)

1. **Install Ollama** (if not installed):
   Download and install from [ollama.com](https://ollama.com/download/windows) or run:
   ```powershell
   winget install Ollama.Ollama
   ```
2. **Pull LLaMA 3 8B**:
   ```powershell
   ollama pull llama3:8b
   ```

---

## Files in `stage_1/`

- `prompts.py`: Element-Aware prompts (Step 1 & Step 2) and ICL demonstration formatter.
- `ollama_client.py`: Local REST API client for Ollama.
- `stage1_generator.py`: CLI runner with incremental auto-saving and auto-resume.

---

## How to Run Stage 1

### 1. Quick Verification Run (1 Sample)
```powershell
python stage_1/stage1_generator.py --limit 1
```

### 2. Full Paper SOTA Run (on `test_only`)
```powershell
python stage_1/stage1_generator.py `
  --input-json ../aci_dataset_rq1_baseline/test_only/test.json `
  --output-json stage_1/stage1_output.json `
  --n-shots 1 `
  --model llama3:8b
```

### Output
The output file (`stage1_output.json`) contains:
- `stage1_elements`: Extracted clinical elements from Step 1.
- `stage1_summary`: Synthesized Assessment & Plan from Step 2.
- `stage1_method`: `element_aware+icl`.
- `stage1_model`: `llama3:8b`.
