"""Resume a saved batch without replacing successful notes or its original inputs."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path

from .dataset import load_encounters


@contextmanager
def generation_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    # Lock the directory itself; no extra lock files appear among the outputs.
    descriptor = os.open(root, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another generation process is using this output folder. Stop it before resuming.") from exc
        yield
    finally:
        os.close(descriptor)


def resume_run(args):
    if args.resume == "latest":
        manifests = sorted(args.output_dir.glob("*/run_manifest.json"))
        if not manifests:
            raise ValueError("No saved run found to resume.")
        run = manifests[-1].parent
    else:
        run = Path(args.resume).expanduser()
        if not run.is_dir():
            run = args.output_dir / args.resume
    run = run.resolve()
    allowed_roots = {args.output_dir.resolve(), (args.output_dir.parent / "agentic-pipeline-output-backups").resolve()}
    if run.parent not in allowed_roots:
        raise ValueError("Resume directory must be directly inside the output or backup folder.")
    manifest = json.loads((run / "run_manifest.json").read_text())
    config = manifest["config"]
    if config["model"] != args.model or config["max_turns"] != args.max_turns:
        raise ValueError("Resume with the original --model and --max-turns settings.")
    prompts = Path(__file__).resolve().parent.parent / "prompts"
    hashes = {str(p.relative_to(prompts)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in prompts.rglob("*") if p.is_file()}
    if hashes != manifest["prompt_sha256"]:
        raise ValueError("Prompts changed since this run. Start a fresh run to use different prompts.")
    available = {(e.split, e.encounter_id): e for e in load_encounters(args.dataset_dir, "all", None, 0)}
    encounters = []
    for record in manifest["encounters"]:
        key = (record["split"], record["encounter_id"])
        encounter = available.get(key)
        if encounter is None or hashlib.sha256(encounter.dialogue.encode()).hexdigest() != record["dialogue_sha256"]:
            raise ValueError(f"Source conversation changed or is missing: {key}.")
        encounters.append(encounter)
    return run, encounters


def finished_case(directory: Path) -> bool:
    status = directory / "details/status.json"
    if not status.exists():
        return False
    if json.loads(status.read_text()).get("status") != "completed":
        return False
    # A status alone is insufficient: both final artifacts must have been saved.
    note = directory / "soap_note.json"
    if not note.exists() or not (directory / "soap_note.md").exists():
        return False
    return bool(json.loads(note.read_text()).get("soap"))
