# One Encounter, Two Readers

**Team Tokenizers** · LTRC, IIIT Hyderabad

From one doctor–patient conversation we produce a verified SOAP note for the doctor and a faithful
plain-language summary for the patient.

* **RQ1 (verify-and-ask)** checks the Subjective/Objective part of the note against the conversation, adds back
  missed facts and turns remaining gaps into questions.
* **RQ2 (evidence chain)** checks each Assessment/Plan line against the patient facts it rests on, then produces
  the signed note and the patient summary.

## Folder structure

```
tokenizers/
├── data/
│   ├── aci_bench/                ACI-Bench corpus (original data)
│   └── intake_simulation/
│       ├── code/                 multi-agent intake that turns each ACI-Bench case into a consultation
│       │   └── Qwen3-14B_setup/  the Qwen3-14B server the intake and demo use
│       └── output/soap_notes/    207 simulated consultations (input to everything below)
├── baseline/                     uMedSum re-implementation (the comparison system)
│   ├── umedsum_final_soap_notes/ baseline run on our 201 consultations (code + output/)
│   ├── umedsum_pipeline_baseline/ uMedSum stage code (stage_1/2/3) + earlier ACI-Bench run
│   └── aci_dataset_rq1_baseline/ ACI-Bench data prepared for that earlier run
├── rq1_verify_and_ask/
│   ├── run_local.ps1             entry point for every step
│   ├── stage1_pipeline/          note writer: stage1_code/ + stage1_output/
│   └── Stage23_pipeline/         verification, recovery, questions, scoring: code/ + output/
├── rq2_evidence_chain/
│   ├── RQ2_verify_and_ask.ipynb  Colab notebook that ran RQ2 (as run, on commit 04194dc)
│   ├── code/                     all RQ2 code
│   ├── results/                  metrics.json + one CSV per pipeline step (blocks/)
│   ├── outputs/                  doctor notes, signed notes, patient summaries per case
│   └── work/                     intermediate files
├── demo/                         live demo page (frontend/ + backend/ + run_ui.sh)
└── docs/                         poster, proposal, mid-term submission
```

## How to run

### Simulated intake (needs Qwen3-14B on a GPU node)

```bash
cd data/intake_simulation/code/Qwen3-14B_setup
bash run.sh --setup-only        # once: environment + model download
bash run.sh --serve-only        # start the server (inside screen); listens on 127.0.0.1:8000

cd ..                           # data/intake_simulation/code
bash generate_soap.sh --resume latest   # writes to data/intake_simulation/output/soap_notes
bash generate_soap.sh --status          # progress
```

### Baseline (Google Colab, GPU)

Open `baseline/umedsum_baseline_full_soap.ipynb` and run all cells. To run the scripts directly:

```bash
python baseline/umedsum_final_soap_notes/run_umedsum_soap.py --scope soap
python baseline/umedsum_final_soap_notes/evaluate_full_soap.py --eval-code rq1_verify_and_ask/Stage23_pipeline/code
```

### RQ1 (Windows PowerShell; LLaMA-3-8B, DeBERTa and MiniLM servers)

```powershell
cd rq1_verify_and_ask
$env:LLM_API_KEY = "<key>"; $env:NLI_API_KEY = "<key>"
.\run_local.ps1 setup
.\run_local.ps1 prepare
.\run_local.ps1 stage1
.\run_local.ps1 stage23 --split test
.\run_local.ps1 eval --split test
```

Each step resumes if interrupted. Scores are written to `Stage23_pipeline/output/evaluation/`.

### RQ2 (Google Colab, A100 or L4)

Open `rq2_evidence_chain/RQ2_verify_and_ask.ipynb` and run all cells. It is resumable and saves to
`MyDrive/tokenizers/rq2_evidence_chain/`. Quick offline check without a GPU:

```bash
cd rq2_evidence_chain/code && bash tests/smoke_test.sh     # ends with SMOKE TEST OK
```

### Demo

On the GPU node:

```bash
bash /scratch/jyothika.goparaju/temp/setup_qwen_and_deps.sh    # once
screen -S tokenizers-ui
bash demo/run_ui.sh                                             # serves on port 7860
```

From your laptop:

```bash
ssh -N -J jyothika.goparaju@ada-gw1.iiit.ac.in -L 7860:127.0.0.1:7860 jyothika.goparaju@gnode087
```

Then open <http://localhost:7860>. Without a GPU, `LOAD_MODEL=0 bash demo/run_ui.sh` starts it in replay mode
(saved consultations only).
