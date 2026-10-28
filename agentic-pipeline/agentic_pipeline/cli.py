import argparse
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys

from .client import ModelClient, ModelError
from .consultation import Consultation
from .dataset import load_encounters, SPLITS
from .outputs import CaseOutput, create_run, now, write_json
from .resume import finished_case, generation_lock, resume_run

ROOT = Path(__file__).resolve().parent.parent


def parser():
    result = argparse.ArgumentParser(description="Generate SOAP notes using Aegle's patient-agent consultation workflow.")
    result.add_argument("--base-url", default=os.getenv("QWEN_BASE_URL", "http://127.0.0.1:8001/v1"))
    result.add_argument("--model", default=os.getenv("QWEN_MODEL", "Qwen3-14B"))
    result.add_argument("--dataset-dir", type=Path, default=ROOT.parent / "aci-bench-corpus")
    result.add_argument("--output-dir", type=Path, default=ROOT.parent / "agentic-pipeline-output")
    result.add_argument("--split", choices=[*SPLITS, "all"], default="train")
    result.add_argument("--encounter-id", default=None)
    result.add_argument("--limit", type=int, default=1, help="Maximum encounters across selected splits; 0 means all.")
    result.add_argument("--max-turns", type=int, default=15)
    result.add_argument("--timeout", type=float, default=900, help="Seconds allowed for each model request.")
    result.add_argument("--check", action="store_true", help="Check the model endpoint and exit without generation.")
    result.add_argument("--resume", nargs="?", const="latest", default=None, metavar="RUN_DIRECTORY",
                        help="Continue the latest saved run, or specify its directory. Reuse its original encounter selection.")
    return result


async def execute(args) -> int:
    if args.max_turns < 1 or args.limit < 0 or args.timeout <= 0:
        raise ValueError("Use --max-turns >= 1, --limit >= 0 and --timeout > 0.")
    with nullcontext() if args.check else generation_lock(args.output_dir):
        return await execute_locked(args)


async def execute_locked(args) -> int:
    resume_directory = None
    if args.resume and not args.check:
        resume_directory, encounters = resume_run(args)
    else:
        encounters = [] if args.check else load_encounters(args.dataset_dir, args.split, args.encounter_id, args.limit)
    if not args.check and not encounters:
        raise ValueError("No encounters selected.")
    client = ModelClient(args.base_url, args.model, os.getenv("QWEN_API_KEY", "local-unused"), timeout=args.timeout)
    run = None
    try:
        info = await client.check()
        print(f"Endpoint ready: {args.model} at {args.base_url}", flush=True)
        if args.check:
            print(json.dumps(info, indent=2))
            return 0
        config = {"base_url": args.base_url, "model": args.model, "max_turns": args.max_turns,
                  "split": args.split, "limit": args.limit, "timeout_seconds": args.timeout,
                  "model_request_concurrency": 1, "endpoint": info,
                  "dataset_dir": str(args.dataset_dir.resolve()), "reference_note_used": False,
                  "reference_repo": "https://github.com/HovChen/Aegle", "reference_commit": "75297da",
                  "reference_paper": "https://arxiv.org/abs/2604.08927v3"}
        if resume_directory is None:
            run = create_run(args.output_dir, config, encounters)
        else:
            run = resume_directory
            manifest = json.loads((run / "run_manifest.json").read_text())
            attempts = manifest.get("resume_attempts", []) + [{"resumed_at": now(), "base_url": args.base_url,
                                                             "timeout_seconds": args.timeout}]
            write_json(run / "run_manifest.json", {**manifest, "status": "running", "resume_attempts": attempts})
        print(f"Processing {len(encounters)} encounter(s). Outputs: {run}", flush=True)
        failed = []
        skipped = 0
        for encounter in encounters:
            try:
                directory = run / encounter.split / encounter.encounter_id
                if resume_directory and finished_case(directory):
                    skipped += 1
                    print(f"Skipping completed: {encounter.encounter_id}", flush=True)
                    continue
                resuming_case = resume_directory is not None and directory.exists()
                output = CaseOutput(run, encounter.split, encounter.encounter_id, resume=resuming_case)
                await Consultation(client, output).run(encounter, max_turns=args.max_turns, resume=resuming_case)
                print(f"Saved: {output.directory / 'soap_note.md'}", flush=True)
            except Exception as exc:
                failed.append(encounter.encounter_id)
                print(f"FAILED {encounter.encounter_id}: {exc}", file=sys.stderr, flush=True)
        manifest = json.loads((run / "run_manifest.json").read_text())
        write_json(run / "run_manifest.json", {**manifest, "finished_at": now(),
                   "status": "completed" if not failed else "completed_with_failures", "failed_encounters": failed})
        print(f"Finished: {len(encounters) - len(failed)} succeeded ({skipped} already complete), {len(failed)} failed. Outputs: {run}")
        return 1 if failed else 0
    except BaseException as exc:
        if run is not None:
            manifest = json.loads((run / "run_manifest.json").read_text())
            write_json(run / "run_manifest.json", {**manifest, "finished_at": now(), "status": "interrupted", "error": str(exc)})
        raise
    finally:
        await client.close()


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except KeyboardInterrupt:
        print("Interrupted. Partial consultation and status are saved in the run directory.", file=sys.stderr)
        return 130
    except (ModelError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
