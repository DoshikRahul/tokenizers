"""
Stage 1: Initial Summary Generation for uMedSum.

Dedicated to the Paper SOTA (Nagar et al., ACL 2025):
Element-Aware Summarization + In-Context Learning (Wang et al., 2023).

Model: LLaMA 3 (8B) via local Ollama.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any

from ollama_client import OllamaClient
from prompts import (
    ELEMENT_AWARE_SYSTEM_PROMPT,
    ELEMENT_AWARE_STEP1_PROMPT,
    ELEMENT_AWARE_STEP2_PROMPT,
    format_icl_demonstrations
)

DEFAULT_DATASET = Path(__file__).resolve().parent.parent.parent / "aci_dataset_rq1_baseline" / "test_only" / "test.json"
DEFAULT_ICL = Path(__file__).resolve().parent.parent.parent / "aci_dataset_rq1_baseline" / "icl_examples.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "stage1_output.json"


def run_stage1_element_aware(
    client: OllamaClient,
    sample: Dict[str, Any],
    icl_prefix: str = ""
) -> Dict[str, Any]:
    """Execute Element-Aware Summarization (Step 1: Element Extraction, Step 2: Synthesis)."""
    dialogue = sample.get("src", "").strip()
    result = dict(sample)

    # Step 1: Element Extraction
    step1_prompt = ELEMENT_AWARE_STEP1_PROMPT.format(dialogue=dialogue)
    extracted_elements = client.generate(
        prompt=step1_prompt,
        system="You are a precise clinical assistant. Extract only factual clinical elements directly mentioned in the dialogue.",
        temperature=0.0
    )

    # Step 2: Synthesis into Assessment and Plan
    step2_content = ELEMENT_AWARE_STEP2_PROMPT.format(
        dialogue=dialogue,
        elements=extracted_elements
    )
    if icl_prefix:
        step2_prompt = icl_prefix + step2_content
    else:
        step2_prompt = step2_content

    summary = client.generate(
        prompt=step2_prompt,
        system=ELEMENT_AWARE_SYSTEM_PROMPT,
        temperature=0.0
    )

    # Clean leading headers if repeated by model
    if summary.startswith("ASSESSMENT AND PLAN:"):
        summary = summary[len("ASSESSMENT AND PLAN:"):].strip()
    elif summary.startswith("ASSESSMENT AND PLAN"):
        summary = summary[len("ASSESSMENT AND PLAN"):].strip()

    result["stage1_elements"] = extracted_elements
    result["stage1_summary"] = summary
    result["stage1_method"] = "element_aware+icl" if icl_prefix else "element_aware"
    result["stage1_model"] = client.model
    return result


def main():
    parser = argparse.ArgumentParser(description="uMedSum Stage 1: Element-Aware Summarizer (Paper SOTA)")
    parser.add_argument("--input-json", type=str, default=str(DEFAULT_DATASET), help="Input evaluation dataset JSON")
    parser.add_argument("--output-json", type=str, default=str(DEFAULT_OUTPUT), help="Output JSON for Stage 1 results")
    parser.add_argument("--icl-json", type=str, default=str(DEFAULT_ICL), help="Path to held-out ICL examples JSON")
    parser.add_argument("--n-shots", type=int, default=1, help="Number of ICL demonstrations to prepend (default: 1)")
    parser.add_argument("--no-icl", dest="use_icl", action="store_false", help="Disable ICL (run zero-shot element-aware)")
    parser.set_defaults(use_icl=True)
    parser.add_argument("--model", type=str, default="llama3:8b", help="Ollama model name (default: llama3:8b)")
    parser.add_argument("--ollama-url", type=str, default="http://localhost:11434", help="Ollama API base URL")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N samples (for testing)")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from existing output JSON if present")
    args = parser.parse_args()

    input_path = Path(args.input_json)
    output_path = Path(args.output_json)
    icl_path = Path(args.icl_json)

    if not input_path.exists():
        sys.exit(f"Error: Input dataset not found: {input_path}")

    # Initialize client & check Ollama status
    client = OllamaClient(base_url=args.ollama_url, model=args.model)
    print(f"Connecting to Ollama at {args.ollama_url}...")
    if not client.check_connection():
        print(f"\n[ERROR] Could not connect to Ollama at {args.ollama_url}.")
        print("Please ensure Ollama is installed and running (`ollama serve` or open Ollama).")
        print(f"To pull the model: ollama pull {args.model}\n")
        sys.exit(1)

    installed_models = client.list_models()
    print(f"Connected! Available models in Ollama: {installed_models}")
    model_found = any(args.model in m for m in installed_models)
    if not model_found:
        print(f"[WARNING] Model '{args.model}' not found in installed models. Run: ollama pull {args.model}")

    # Load dataset
    with open(input_path, "r", encoding="utf-8") as f:
        samples = json.load(f).get("data", [])

    if args.limit:
        samples = samples[:args.limit]

    # Load ICL demonstrations
    icl_prefix = ""
    if args.use_icl:
        if icl_path.exists():
            with open(icl_path, "r", encoding="utf-8") as f:
                icl_data = json.load(f).get("data", [])
            icl_prefix = format_icl_demonstrations(icl_data, n_shots=args.n_shots)
            print(f"Loaded {args.n_shots}-shot ICL demonstration from {icl_path.name}")
        else:
            print(f"[WARNING] ICL file not found at {icl_path}. Proceeding zero-shot.")

    # Resume handling
    processed_files = set()
    output_records = []
    if args.resume and output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                output_records = json.load(f).get("data", [])
            processed_files = {r["file"] for r in output_records if "stage1_summary" in r}
            print(f"Resuming: found {len(processed_files)} previously completed samples in {output_path.name}")
        except Exception:
            output_records = []

    total_samples = len(samples)
    print(f"\nRunning Paper SOTA (Element-Aware {'+ ICL' if icl_prefix else ''}) on {total_samples} samples...")
    print(f"  Model  : {args.model}")
    print(f"  Input  : {input_path}")
    print(f"  Output : {output_path}\n")

    start_time = time.time()
    for idx, sample in enumerate(samples, 1):
        file_id = sample.get("file", f"sample_{idx}")
        if file_id in processed_files:
            continue

        print(f"[{idx}/{total_samples}] Processing {file_id} ...", end="", flush=True)
        sample_start = time.time()
        try:
            processed = run_stage1_element_aware(
                client=client,
                sample=sample,
                icl_prefix=icl_prefix
            )
            output_records.append(processed)
            processed_files.add(file_id)

            # Incremental save
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"data": output_records}, f, indent=2, ensure_ascii=False)

            elapsed = round(time.time() - sample_start, 1)
            print(f" done ({elapsed}s)")
        except Exception as e:
            print(f" FAILED: {e}")

    total_time = round(time.time() - start_time, 1)
    print(f"\nStage 1 complete! Successfully generated {len(output_records)} summaries in {total_time}s.")
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
