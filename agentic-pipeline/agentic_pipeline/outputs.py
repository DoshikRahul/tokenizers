import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def create_run(root: Path, config: dict, encounters: list) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    prompt_root = Path(__file__).resolve().parent.parent / "prompts"
    write_json(directory / "run_manifest.json", {
        "run_id": run_id, "started_at": now(), "status": "running", "config": config,
        "encounters": [{"split": e.split, "encounter_id": e.encounter_id, "dataset": e.dataset,
                        "source_file": e.source_file,
                        "dialogue_sha256": hashlib.sha256(e.dialogue.encode()).hexdigest()} for e in encounters],
        "prompt_sha256": {str(p.relative_to(prompt_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(prompt_root.rglob("*")) if p.is_file()},
    })
    return directory


class CaseOutput:
    def __init__(self, run: Path, split: str, encounter_id: str, *, resume: bool = False):
        if Path(encounter_id).name != encounter_id or encounter_id in {".", ".."}:
            raise ValueError("Unsafe encounter ID for output directory.")
        self.directory = run / split / encounter_id
        self.directory.mkdir(parents=True, exist_ok=resume)
        self.details = self.directory / "details"
        self.details.mkdir(exist_ok=resume)
        self.turn = 0
        self.sequence = 0
        self.trace_sequence = 0
        self.identity = {"run_id": run.name, "split": split, "encounter_id": encounter_id}
        if resume:
            messages = read_jsonl(self.details / "agent_messages.jsonl")
            events = read_jsonl(self.details / "agent_trace.jsonl")
            self.sequence = max((entry["sequence"] for entry in messages), default=0)
            self.trace_sequence = max((int(entry["event_id"].rsplit("-", 1)[1]) for entry in events), default=0)
            self.turn = max((entry.get("turn", 0) for entry in events + messages), default=0)
        if not (self.directory / "consultation.md").exists():
            (self.directory / "consultation.md").write_text(
                f"# Patient–doctor conversation — {encounter_id}\n\n", encoding="utf-8")
        if not (self.directory / "agent_conversation.md").exists():
            (self.directory / "agent_conversation.md").write_text(
                f"# Agent exchanges — {encounter_id}\n\n"
                "Questions, patient answers, routing instructions, specialist proposals, and aggregator updates in order.\n\n",
                encoding="utf-8")

    def message(self, *, sender: str, recipient: str, phase: str, kind: str,
                content: str, data=None, source_event_id: str | None = None) -> None:
        self.sequence += 1
        entry = {**self.identity, "sequence": self.sequence,
                 "message_id": f"message-{self.sequence:05d}", "time": now(), "turn": self.turn,
                 "phase": phase, "sender": sender, "recipient": recipient,
                 "kind": kind, "content": content, "data": data,
                 "source_event_id": source_event_id}
        with (self.details / "agent_messages.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        with (self.directory / "agent_conversation.md").open("a", encoding="utf-8") as handle:
            handle.write(f"## {self.sequence}. Turn {self.turn} — {phase.replace('_', ' ')}\n\n"
                         f"**{sender} → {recipient}** · {kind.replace('_', ' ')}\n\n{content}\n\n")

    def event(self, event: dict) -> None:
        self.trace_sequence += 1
        trace_id = f"event-{self.trace_sequence:05d}"
        with (self.details / "agent_trace.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**self.identity, "event_id": trace_id,
                                    "time": now(), "turn": self.turn, **event}, ensure_ascii=False) + "\n")
        phase = event.get("phase", "diagnosis_and_plan")
        if event["event"] == "validated":
            agent, output = event["agent"], event["output"]
            if agent == "orchestrator":
                recipient = ", ".join(output["active_specialists"]) or "aggregator"
                text = f"Selected specialists: {', '.join(output['active_specialists']) or 'none'}.\n\nInstructions: {output['instructions_to_specialists']}"
                if output.get("suggested_question"):
                    text += f"\n\nSuggested question: {output['suggested_question']}"
                kind = "routing"
            elif agent.startswith("specialist:"):
                recipient, kind = "aggregator", "specialist_proposal"
                text = f"Proposed record changes:\n\n{output['draft_modifications']}\n\nSuggested follow-up: {output['next_question']}"
            elif phase == "historytaking":
                recipient, kind = "shared_record", "evidence_update"
                labels = {"basic_info": "Basic information", "present_illness": "Present illness",
                          "past_history": "Past history", "physical_exam": "Physical examination", "aux_exam": "Investigations"}
                text = "\n\n".join(f"**{label}:** {output['updated_case_features'].get(field) or 'Not yet collected.'}" for field, label in labels.items())
                text += f"\n\n**History complete:** {output['historytaking_complete']}"
                if output["next_question_to_patient"]:
                    text += f"\n\n**Proposed next question:** {output['next_question_to_patient']}"
            else:
                recipient, kind = "soap_note", "diagnosis_and_plan"
                diagnosis = output["diagnosis_and_plan"]
                text = (f"**Preliminary diagnosis:**\n\n{diagnosis['preliminary_diagnosis']}\n\n"
                        f"**Diagnostic discussion:**\n\n{diagnosis['diagnosis_discussion']}\n\n"
                        f"**Proposed plan:**\n\n{diagnosis['treatment_plan']}")
            self.message(sender=agent, recipient=recipient, phase=phase, kind=kind,
                         content=text, data=output, source_event_id=trace_id)
        elif event["event"] == "evidence_frozen":
            self.message(sender="pipeline", recipient="doctor_team", phase="diagnosis_and_plan",
                         kind="evidence_frozen", content=f"Case features frozen. History-taking stop reason: {event['stop_reason']}.",
                         data={key: value for key, value in event.items() if key != "event"}, source_event_id=trace_id)
        elif event["event"] == "diagnosis_routing":
            self.message(sender="orchestrator", recipient=", ".join(event["specialists"]) or "aggregator",
                         phase="diagnosis_and_plan", kind="routing",
                         content="Reuse the specialists activated during history taking. " + event.get("instructions", ""),
                         data={key: value for key, value in event.items() if key != "event"}, source_event_id=trace_id)

    def conversation(self, role: str, content: str, turn: int) -> None:
        self.turn = turn
        with (self.details / "consultation.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**self.identity, "time": now(), "turn": turn, "role": role, "content": content}, ensure_ascii=False) + "\n")
        with (self.directory / "consultation.md").open("a", encoding="utf-8") as handle:
            if role == "doctor":
                handle.write(f"## Turn {turn}\n\n**Doctor:** {content}\n\n")
            else:
                handle.write(f"**Patient agent:** {content}\n\n")
        self.message(sender=role, recipient="patient" if role == "doctor" else "doctor_team",
                     phase="historytaking", kind="question" if role == "doctor" else "answer", content=content)

    def save(self, filename: str, value) -> None:
        write_json((self.directory if filename == "soap_note.json" else self.details) / filename, value)

    def status(self, **fields) -> None:
        self.save("status.json", {"updated_at": now(), **fields})

    def final_note(self, identifier: str, features, diagnosis, *, stop_reason: str, turns: int, specialists: list[str], uncollected: list[str]) -> None:
        def show(value):
            return value.strip() or "Not documented during the simulated consultation."

        sections = {
            "subjective": "\n\n".join(f"{label}: {show(getattr(features, field))}" for label, field in
                (("Basic information", "basic_info"), ("History of present illness", "present_illness"), ("Past history", "past_history"))),
            "objective": f"Physical examination: {show(features.physical_exam)}\n\nInvestigations: {show(features.aux_exam)}",
            "assessment": f"Preliminary diagnosis:\n{diagnosis.preliminary_diagnosis}\n\nDiagnostic discussion:\n{diagnosis.diagnosis_discussion}",
            "plan": diagnosis.treatment_plan,
        }
        self.save("soap_note.json", {
            "encounter_id": identifier, "soap": sections, "case_features": features.model_dump(),
            "diagnosis_and_plan": diagnosis.model_dump(), "stop_reason": stop_reason, "turns": turns,
            "activated_specialists": specialists, "uncollected_fields": uncollected,
            "assessment_plan_origin": "Model-generated reasoning and proposed care, not necessarily the recorded clinician's plan.",
        })
        lines = [f"# SOAP note — {identifier}", "", f"History-taking stop reason: {stop_reason}; turns: {turns}.", "",
                 "Assessment and Plan contain model-generated reasoning and proposed care.", ""]
        if not features.complete:
            lines.extend(["History taking ended before the agent confirmed completion. Unelicited facts remain unknown.", ""])
        for heading, key in (("Subjective", "subjective"), ("Objective", "objective"), ("Assessment", "assessment"), ("Plan", "plan")):
            lines.extend([f"## {heading}", "", sections[key], ""])
        (self.directory / "soap_note.md").write_text("\n".join(lines), encoding="utf-8")
