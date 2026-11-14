# Run the pipeline on this PC. Llama-3, DeBERTa NLI and MiniLM run on the GPU server (via SSH tunnel to
# localhost:8000); GPT-2 and scoring run locally, and all outputs are saved under this folder.
#
#   .\run_local.ps1 setup            # one time: venv (Python 3.12) + dependencies
#   .\run_local.ps1 check            # test the LLM server (reachable? context large enough?)
#   .\run_local.ps1 prepare
#   .\run_local.ps1 stage1  [extra args, e.g. --split dev --limit 3]
#   .\run_local.ps1 stage23 [extra args]
#   .\run_local.ps1 eval    [extra args, e.g. --split dev]
#
# The API key is never stored: set $env:API_KEY first, or you will be asked for it.
param(
    [Parameter(Mandatory = $true)][ValidateSet("setup", "check", "prepare", "stage1", "stage23", "eval")][string]$Step,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

if ($Step -eq "setup") {
    if (-not (Test-Path $Py)) { py -3.12 -m venv $Venv }
    & $Py -m pip install --upgrade pip
    & $Py -m pip install -r (Join-Path $Root "requirements.txt")
    Write-Host "Setup done. Note: PyTorch here is CPU-only unless you install a CUDA build."
    return
}

if (-not (Test-Path $Py)) { throw "Run '.\run_local.ps1 setup' first." }

# ---- server: all three models on ONE server, reached through an SSH tunnel to localhost:8000 ----
# In a separate terminal, keep this open while running:
#   ssh -N -L 8000:localhost:8000 -J jyothika.goparaju@ada-gw1.iiit.ac.in jyothika.goparaju@gnode087
# One Bearer API key for all endpoints (never stored in a file): set $env:API_KEY first, or you will be asked.
if (-not $env:API_KEY) {
    $secure = Read-Host "API key" -AsSecureString
    $env:API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}
$env:LLM_BASE_URL   = "http://localhost:8000/v1"
$env:LLM_MODEL      = "llama3"
$env:LLM_API_KEY    = $env:API_KEY
$env:NLI_BASE_URL   = "http://localhost:8000"
$env:NLI_API_KEY    = $env:API_KEY
$env:EMBED_BASE_URL = "http://localhost:8000"
$env:EMBED_API_KEY  = $env:API_KEY

# ---- local paths: 207-case dataset, outputs added to the existing folders ----
$S1 = Join-Path $Root "stage1_pipeline\stage1_code"
$RQ = Join-Path $Root "Stage23_pipeline\code"
$env:DATASET_ROOT       = Join-Path (Split-Path $Root -Parent) "soap_notes_207\agentic-pipeline-output\soap_notes"
$env:STAGE1_OUTPUT_DIR  = Join-Path $Root "stage1_pipeline\stage1_output"
$env:STAGE1_OUTPUT_JSON = Join-Path $env:STAGE1_OUTPUT_DIR "stage1_output.json"
$env:RQ1_OUTPUT_DIR     = Join-Path $Root "Stage23_pipeline\output"

switch ($Step) {
    "check"   { Push-Location $RQ; & $Py check_llm.py; Pop-Location }
    "prepare" { Push-Location $S1; & $Py prepare_dataset.py; Pop-Location }
    "stage1"  { Push-Location $S1; & $Py run_stage1.py @Rest; if ($LASTEXITCODE -eq 0) { & $Py evaluate_stage1.py }; Pop-Location }
    "stage23" { Push-Location $RQ; & $Py run_stage23.py @Rest; Pop-Location }
    "eval"    { Push-Location $RQ; & $Py evaluate.py @Rest; Pop-Location }
}
