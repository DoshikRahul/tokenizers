# Stage 1 SOAP pipeline for Google Colab

Files:
- `config.py`: paths and Ollama configuration.
- `prepare_dataset.py`: reads `consultation.md` and extracts reference S/O from `soap_note.md`.
- `run_stage1.py`: generates a full SOAP note from the consultation using Ollama.
- `evaluate_stage1.py`: evaluates generated Subjective and Objective separately against reference S/O.
- `requirements.txt`: Python dependencies.

Expected case layout:
`DATASET_ROOT/D2N001/consultation.md` and `DATASET_ROOT/D2N001/soap_note.md`.
Recursive search also supports an intermediate folder such as `soap_notes/D2N001/`.

Colab: mount Google Drive, clone the repository, then place this project folder in Drive.
Set `DATASET_ROOT` and `STAGE1_OUTPUT_DIR` environment variables before running scripts.
The generation prompt receives only the consultation text. Reference S/O is evaluator-only.

Run:
1. `python prepare_dataset.py`
2. `python run_stage1.py`
3. `python evaluate_stage1.py`

This version uses Ollama's local API. Ollama must be installed, running, and have the selected model pulled. On free Colab, RAM/VRAM constraints may make local inference slow or infeasible.
