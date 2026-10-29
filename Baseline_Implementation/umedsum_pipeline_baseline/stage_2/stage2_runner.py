"""
CLI Runner for uMedSum Stage 2: Confabulation Removal.

Processes Stage 1 generated summaries, removes discrete confabulated facts using
DeBERTa-v3-large NLI + recursive atomic decomposition, and produces refined summaries.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from nli_scorer import DebertaNLIScorer, DEFAULT_NLI_MODEL
from atomic_decomposer import AtomicDecomposer
from confabulation_remover import ConfabulationRemover, DEFAULT_TE, DEFAULT_TC, DEFAULT_TA

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "stage_1" / "stage1_output.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "stage2_output.json"

def main():
    parser = argparse.ArgumentParser(description="uMedSum Stage 2: Confabulation Removal (Paper SOTA)")
    parser.add_argument("--input-json", type=str, default=str(DEFAULT_INPUT), help="Input JSON from Stage 1")
    parser.add_argument("--output-json", type=str, default=str(DEFAULT_OUTPUT), help="Output JSON for Stage 2 results")
    parser.add_argument("--nli-model", type=str, default=DEFAULT_NLI_MODEL, help="Hugging Face NLI model checkpoint")
    parser.add_argument("--te", type=float, default=DEFAULT_TE, help="Entailment threshold (default: 0.9)")
    parser.add_argument("--tc", type=float, default=DEFAULT_TC, help="Confabulation threshold (default: 0.8)")
    parser.add_argument("--ta", type=float, default=DEFAULT_TA, help="Atomic fact threshold (default: 0.5)")
    parser.add_argument("--ollama-url", type=str, default="http://localhost:11434", help="Ollama API base URL")
    parser.add_argument("--model", type=str, default="llama3:8b", help="LLM for atomic decomposition")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N samples")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from existing output JSON if present")
    args = parser.parse_args()

    input_path = Path(args.input_json)
    output_path = Path(args.output_json)

    if not input_path.exists():
        sys.exit(f"Error: Input JSON from Stage 1 not found: {input_path}")

    # Load input samples
    with open(input_path, "r", encoding="utf-8") as f:
        samples = json.load(f).get("data", [])

    if args.limit:
        samples = samples[:args.limit]

    # Initialize NLI Scorer & Decomposer
    print("\n--- Initializing Stage 2 Modules ---")
    nli_scorer = DebertaNLIScorer(model_name=args.nli_model)
    decomposer = AtomicDecomposer(ollama_url=args.ollama_url, model=args.model)
    remover = ConfabulationRemover(
        nli_scorer=nli_scorer,
        decomposer=decomposer,
        te=args.te,
        tc=args.tc,
        ta=args.ta
    )

    # Resume handling
    processed_files = set()
    output_records = []
    if args.resume and output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                output_records = json.load(f).get("data", [])
            processed_files = {r["file"] for r in output_records if "stage2_summary" in r}
            print(f"Resuming: found {len(processed_files)} previously completed samples in {output_path.name}")
        except Exception:
            output_records = []

    total_samples = len(samples)
    print(f"\nStarting Stage 2 confabulation removal on {total_samples} samples...")
    print(f"  NLI Model: {args.nli_model}")
    print(f"  Thresholds: Te={args.te}, Tc={args.tc}, Ta={args.ta}")
    print(f"  Input: {input_path}")
    print(f"  Output: {output_path}\n")

    start_time = time.time()
    for idx, sample in enumerate(samples, 1):
        file_id = sample.get("file", f"sample_{idx}")
        if file_id in processed_files:
            continue

        dialogue = sample.get("src", "")
        stage1_summary = sample.get("stage1_summary", "")

        if not stage1_summary:
            print(f"[{idx}/{total_samples}] {file_id}: No stage1_summary found, skipping.")
            continue

        print(f"[{idx}/{total_samples}] Processing {file_id} ...", end="", flush=True)
        sample_start = time.time()
        try:
            stage2_res = remover.process_summary(dialogue, stage1_summary)

            record = dict(sample)
            record["stage2_summary"] = stage2_res["stage2_summary"]
            record["stage2_faithful_units"] = stage2_res["faithful_units"]
            record["stage2_confabulated_units"] = stage2_res["confabulated_units"]
            record["stage2_uncertain_units"] = stage2_res["uncertain_units"]
            record["stage2_details"] = stage2_res["details"]
            record["stage2_section_breakdown"] = stage2_res.get("section_breakdown", {})

            output_records.append(record)
            processed_files.add(file_id)

            # Incremental save
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"data": output_records}, f, indent=2, ensure_ascii=False)

            n_confab = len(stage2_res["confabulated_units"])
            n_faith = len(stage2_res["faithful_units"])
            elapsed = round(time.time() - sample_start, 1)
            print(f" done ({elapsed}s | faithful: {n_faith}, removed confabs: {n_confab})")
        except Exception as e:
            print(f" FAILED: {e}")

    total_time = round(time.time() - start_time, 1)
    print(f"\nStage 2 complete! Refined {len(output_records)} summaries in {total_time}s.")
    print(f"Results saved to: {output_path}")

if __name__ == "__main__":
    main()
