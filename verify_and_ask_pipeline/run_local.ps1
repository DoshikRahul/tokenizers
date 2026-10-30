# Run the pipeline on this PC. The LLM runs on the friend's GPU server; everything else (NLI, embeddings,
# GPT-2, scoring) runs locally, and all outputs are saved under this folder.
#
#   .\run_local.ps1 setup            # one time: venv (Python 3.12) + dependencies
#   .\run_local.ps1 check            # test the LLM server (reachable? context large enough?)
#   .\run_local.ps1 prepare
#   .\run_local.ps1 stage1  [extra args, e.g. --split dev --limit 3]
#   .\run_local.ps1 stage23 [extra args]
#   .\run_local.ps1 eval    [extra args, e.g. --split dev]
#
# The API key is never stored: set $env:LLM_API_KEY first, or you will be asked for it.
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

# ---- server settings (edit the URL if it changes) ----
if (-not $env:LLM_BASE_URL) { $env:LLM_BASE_URL = "http://10.2.236.141:8080/v1" }
if (-not $env:LLM_MODEL)    { $env:LLM_MODEL = "llama3" }
if (-not $env:LLM_API_KEY) {
    $secure = Read-Host "LLM API key" -AsSecureString
    $env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

# ---- NLI server (DeBERTa on the friend's GPU); set NLI_BASE_URL to "" to load DeBERTa locally instead ----
if ($null -eq $env:NLI_BASE_URL) { $env:NLI_BASE_URL = "http://10.2.236.141:8081" }
if ($env:NLI_BASE_URL -and -not $env:NLI_API_KEY) {
    $secure = Read-Host "NLI API key" -AsSecureString
    $env:NLI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

# ---- embedding server (MiniLM on the friend's GPU, no key); set EMBED_BASE_URL to "" to load MiniLM locally ----
if ($null -eq $env:EMBED_BASE_URL) { $env:EMBED_BASE_URL = "http://10.2.236.141:8082" }

# ---- local paths: everything stays in this folder ----
$S1 = Join-Path $Root "stage1_pipeline\stage1_colab_project"
$RQ = Join-Path $Root "rq1_pipeline"
$env:DATASET_ROOT       = Join-Path $Root "agentic-pipeline-output\soap_notes"
$env:STAGE1_OUTPUT_DIR  = Join-Path $Root "stage1_pipeline\stage1"
$env:STAGE1_OUTPUT_JSON = Join-Path $env:STAGE1_OUTPUT_DIR "stage1_output.json"
$env:RQ1_OUTPUT_DIR     = Join-Path $RQ "output"

switch ($Step) {
    "check"   { Push-Location $RQ; & $Py check_llm.py; Pop-Location }
    "prepare" { Push-Location $S1; & $Py prepare_dataset.py; Pop-Location }
    "stage1"  { Push-Location $S1; & $Py run_stage1.py @Rest; if ($LASTEXITCODE -eq 0) { & $Py evaluate_stage1.py }; Pop-Location }
    "stage23" { Push-Location $RQ; & $Py run_stage23.py @Rest; Pop-Location }
    "eval"    { Push-Location $RQ; & $Py evaluate.py @Rest; Pop-Location }
}
