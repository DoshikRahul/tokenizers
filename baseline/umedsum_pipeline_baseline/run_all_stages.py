"""
uMedSum Master Pipeline Runner (Stages 1 -> 2 -> 3 -> Evaluation -> Results Archival).

Orchestrates each self-contained stage:
  Stage 1: stage_1/stage1_generator.py -> stage_1/stage1_output.json
  Stage 2: stage_2/stage2_runner.py    -> stage_2/stage2_output.json
  Stage 3: stage_3/stage3_runner.py    -> stage_3/stage3_output.json
  Evaluation: evaluate_metrics.py      -> Benchmark comparison table & results/evaluation_results.json

Copies all stage outputs and the final evaluation JSON into the `results/` folder upon completion.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

STAGE1_SCRIPT = BASE_DIR / "stage_1" / "stage1_generator.py"
STAGE1_OUTPUT = BASE_DIR / "stage_1" / "stage1_output.json"

STAGE2_SCRIPT = BASE_DIR / "stage_2" / "stage2_runner.py"
STAGE2_OUTPUT = BASE_DIR / "stage_2" / "stage2_output.json"

STAGE3_SCRIPT = BASE_DIR / "stage_3" / "stage3_runner.py"
STAGE3_OUTPUT = BASE_DIR / "stage_3" / "stage3_output.json"

RESULTS_DIR = BASE_DIR / "results"
EVAL_SCRIPT = BASE_DIR / "evaluate_metrics.py"
DEFAULT_DATASET = BASE_DIR.parent / "aci_dataset_rq1_baseline" / "test_only" / "test.json"


def run_stage(cmd: list, stage_name: str):
    print(f"\n=======================================================")
    print(f"  EXECUTING {stage_name.upper()}")
    print(f"=======================================================")
    print("Command:", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"\n[ERROR] {stage_name} exited with error code {result.returncode}")


def main():
    parser = argparse.ArgumentParser(description="uMedSum End-to-End Pipeline & Evaluation Runner")
    parser.add_argument("--input-json", type=str, default=str(DEFAULT_DATASET), help="Input evaluation dataset JSON")
    parser.add_argument("--limit", type=int, default=None, help="Process first N samples only")
    parser.add_argument("--skip-stage1", action="store_true", help="Skip Stage 1 (use existing stage_1/stage1_output.json)")
    parser.add_argument("--skip-stage2", action="store_true", help="Skip Stage 2 (use existing stage_2/stage2_output.json)")
    parser.add_argument("--evaluate", action="store_true", default=True, help="Automatically run evaluation after all stages complete (default: True)")
    parser.add_argument("--no-evaluate", dest="evaluate", action="store_false", help="Do not run evaluation at the end")
    parser.add_argument("--skip-bertscore", action="store_true", help="Run fast ROUGE evaluation without BERTScore")
    parser.add_argument("--bertscore-model", type=str, default="roberta-large", help="BERTScore model checkpoint")
    args = parser.parse_args()

    python_exe = sys.executable

    # 1. Run Stage 1
    if not args.skip_stage1:
        cmd1 = [
            python_exe, str(STAGE1_SCRIPT),
            "--input-json", args.input_json,
            "--output-json", str(STAGE1_OUTPUT),
            "--n-shots", "1"
        ]
        if args.limit:
            cmd1.extend(["--limit", str(args.limit)])
        run_stage(cmd1, "Stage 1 (Initial Generation - Paper SOTA)")
    else:
        print("\nSkipping Stage 1 (using existing output).")

    # 2. Run Stage 2
    if not args.skip_stage2:
        cmd2 = [
            python_exe, str(STAGE2_SCRIPT),
            "--input-json", str(STAGE1_OUTPUT),
            "--output-json", str(STAGE2_OUTPUT)
        ]
        if args.limit:
            cmd2.extend(["--limit", str(args.limit)])
        run_stage(cmd2, "Stage 2 (Confabulation Removal - RTB-TS)")
    else:
        print("\nSkipping Stage 2 (using existing output).")

    # 3. Run Stage 3
    if STAGE3_SCRIPT.exists():
        cmd3 = [
            python_exe, str(STAGE3_SCRIPT),
            "--input-json", str(STAGE2_OUTPUT),
            "--output-json", str(STAGE3_OUTPUT)
        ]
        if args.limit:
            cmd3.extend(["--limit", str(args.limit)])
        run_stage(cmd3, "Stage 3 (Missing Information Addition)")

    # 4. Copy outputs to results folder
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if STAGE1_OUTPUT.exists():
        shutil.copy(STAGE1_OUTPUT, RESULTS_DIR / "stage1_output.json")
    if STAGE2_OUTPUT.exists():
        shutil.copy(STAGE2_OUTPUT, RESULTS_DIR / "stage2_output.json")
    if STAGE3_OUTPUT.exists():
        shutil.copy(STAGE3_OUTPUT, RESULTS_DIR / "stage3_output.json")

    print("\n=======================================================")
    print("  uMedSum Generation Stages Finished Successfully!")
    print(f"  Stage 1 Output: {STAGE1_OUTPUT}")
    print(f"  Stage 2 Output: {STAGE2_OUTPUT}")
    print(f"  Stage 3 Output: {STAGE3_OUTPUT}")
    print(f"  Archived in:    {RESULTS_DIR}")
    print("=======================================================")

    # 5. Run Benchmark Evaluation
    if args.evaluate and EVAL_SCRIPT.exists() and STAGE3_OUTPUT.exists():
        eval_out = RESULTS_DIR / "evaluation_results.json"
        eval_cmd = [
            python_exe, str(EVAL_SCRIPT),
            "--input-json", str(STAGE3_OUTPUT),
            "--output-json", str(eval_out)
        ]
        if args.skip_bertscore:
            eval_cmd.append("--skip-bertscore")
        else:
            eval_cmd.extend(["--bertscore-model", args.bertscore_model])
        run_stage(eval_cmd, "Benchmark Evaluation (All Stages & All Metrics)")


if __name__ == "__main__":
    main()
