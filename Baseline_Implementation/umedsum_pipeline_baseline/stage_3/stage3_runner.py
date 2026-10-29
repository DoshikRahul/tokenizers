"""
CLI Runner for uMedSum Stage 3: Missing Information Addition.

Takes refined summaries from Stage 2 (stage2_output.json), extracts missing clinical facts
from the source dialogue using Sentence-BERT + MMR, and merges them using GPT-2 perplexity.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from key_extractor import KeyExtractor, DEFAULT_EMBEDDER_MODEL, DEFAULT_TOP_M
from missing_detector import MissingInformationDetector, DEFAULT_COV_MIN
from perplexity_merger import PerplexityMerger, DEFAULT_PPL_MODEL

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "stage_2" / "stage2_output.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "stage3_output.json"

def main():
    parser = argparse.ArgumentParser(description="uMedSum Stage 3: Missing Information Addition (Paper SOTA)")
    parser.add_argument("--input-json", type=str, default=str(DEFAULT_INPUT), help="Input JSON from Stage 2")
    parser.add_argument("--output-json", type=str, default=str(DEFAULT_OUTPUT), help="Output JSON for Stage 3 results")
    parser.add_argument("--top-m", type=int, default=DEFAULT_TOP_M, help="Number of key sentences to extract from dialogue (default: 2)")
    parser.add_argument("--cov-min", type=float, default=DEFAULT_COV_MIN, help="Minimum coverage score threshold (default: 0.4)")
    parser.add_argument("--embedder-model", type=str, default=DEFAULT_EMBEDDER_MODEL, help="Sentence-BERT model name")
    parser.add_argument("--ppl-model", type=str, default=DEFAULT_PPL_MODEL, help="Perplexity LM model name (default: gpt2)")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N samples")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from existing output JSON if present")
    args = parser.parse_args()

    input_path = Path(args.input_json)
    output_path = Path(args.output_json)

    if not input_path.exists():
        sys.exit(f"Error: Input JSON from Stage 2 not found: {input_path}")

    # Load input samples
    with open(input_path, "r", encoding="utf-8") as f:
        samples = json.load(f).get("data", [])

    if args.limit:
        samples = samples[:args.limit]

    # Initialize Stage 3 Modules
    print("\n--- Initializing Stage 3 Modules ---")
    extractor = KeyExtractor(model_name=args.embedder_model)
    detector = MissingInformationDetector(embedder=extractor.embedder, cov_min=args.cov_min)
    merger = PerplexityMerger(model_name=args.ppl_model)

    # Resume handling
    processed_files = set()
    output_records = []
    if args.resume and output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                output_records = json.load(f).get("data", [])
            processed_files = {r["file"] for r in output_records if "stage3_summary" in r}
            print(f"Resuming: found {len(processed_files)} previously completed samples in {output_path.name}")
        except Exception:
            output_records = []

    total_samples = len(samples)
    print(f"\nStarting Stage 3 missing information addition on {total_samples} samples...")
    print(f"  topM: {args.top_m} (key sentences from dialogue)")
    print(f"  cov_min: {args.cov_min} (coverage threshold)")
    print(f"  Input: {input_path}")
    print(f"  Output: {output_path}\n")

    start_time = time.time()
    for idx, sample in enumerate(samples, 1):
        file_id = sample.get("file", f"sample_{idx}")
        if file_id in processed_files:
            continue

        dialogue = sample.get("src", "")
        stage2_summary = sample.get("stage2_summary", "")

        print(f"[{idx}/{total_samples}] Processing {file_id} ...", end="", flush=True)
        sample_start = time.time()
        try:
            # Step 3A: Extract key information
            key_sentences = extractor.extract_document_key_sentences(dialogue, top_m=args.top_m)
            summary_key_phrases = extractor.extract_summary_key_phrases(stage2_summary, top_n=10)

            # Step 3B: Detect missing sentences
            detection = detector.detect_missing_sentences(key_sentences, summary_key_phrases)
            missing_sentences = detection["missing_sentences"]

            # Step 3C: Perplexity-guided merge
            final_summary, insertion_log = merger.merge_missing_sentences(stage2_summary, missing_sentences)

            record = dict(sample)
            record["stage3_summary"] = final_summary
            record["stage3_key_sentences_extracted"] = key_sentences
            record["stage3_summary_key_phrases"] = summary_key_phrases
            record["stage3_missing_sentences_added"] = missing_sentences
            record["stage3_coverage_scores"] = detection["coverage_scores"]
            record["stage3_insertions"] = insertion_log

            output_records.append(record)
            processed_files.add(file_id)

            # Incremental save
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"data": output_records}, f, indent=2, ensure_ascii=False)

            n_added = len(missing_sentences)
            elapsed = round(time.time() - sample_start, 1)
            print(f" done ({elapsed}s | added {n_added} missing sentences)")
        except Exception as e:
            print(f" FAILED: {e}")

    total_time = round(time.time() - start_time, 1)
    print(f"\nStage 3 complete! Generated {len(output_records)} final summaries in {total_time}s.")
    print(f"Final pipeline results saved to: {output_path}")

if __name__ == "__main__":
    main()
