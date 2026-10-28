"""Infrastructure tests with controlled responses; no clinical/model scoring."""
import asyncio
import csv
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError

from agentic_pipeline.cli import execute, parser
from agentic_pipeline.client import ModelClient, ModelError
from agentic_pipeline.consultation import Consultation
from agentic_pipeline.dataset import Encounter, load_encounters
from agentic_pipeline.outputs import CaseOutput, create_run
from agentic_pipeline.resume import finished_case, generation_lock, resume_run
from agentic_pipeline.prompts import doctor_prompt, patient_prompt
from agentic_pipeline.schemas import AggregatorHistoryOutput, CaseFeatures, FEATURE_FIELDS

ROOT = Path(__file__).resolve().parent.parent


def features(complete=False):
    return {**{name: "TEST_EVIDENCE_" + name for name in FEATURE_FIELDS}, "complete": complete}


class ControlledEndpoint:
    def __init__(self, *, complete_after=2, fail_specialist=False, invalid_once=False, no_specialists=False):
        self.complete_after = complete_after
        self.fail_specialist = fail_specialist
        self.invalid_once = invalid_once
        self.no_specialists = no_specialists
        self.requests = []
        self.turns = 0
        self.rounds = 0
        self.active_requests = 0
        self.peak = 0

    async def __call__(self, request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ready", "model": "Qwen3-14B", "max_output_tokens": 2048})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "Qwen3-14B"}]})
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        payload = json.loads(body["messages"][1]["content"])
        phase = "diagnosis_and_plan" if "Current phase: diagnosis_and_plan\n" in system else "historytaking"
        if system.startswith("You are a professionally trained"):
            role = "patient"
            self.turns += 1
            result = "PATIENT_REPLY_" + str(self.turns)
        elif system.startswith("You are a Medical MDT"):
            role = "orchestrator"
            result = {"active_specialists": ["cardiology" if self.turns == 1 else "psychiatry"],
                      "instructions_to_specialists": "Review the available evidence.", "suggested_question": None}
            if self.no_specialists:
                result["active_specialists"] = []
                result["suggested_question"] = "What examination information is available?"
            if self.invalid_once:
                self.invalid_once = False
                result = {"wrong_key": "invalid routing output"}
        elif system.startswith("You are a specialist"):
            role = "specialist"
            if self.fail_specialist:
                return httpx.Response(503, text="Controlled specialist failure")
            result = {"next_question": "N/A" if phase == "diagnosis_and_plan" else "What history is available?",
                      "draft_modifications": "CONTROLLED_SPECIALIST_PROPOSAL"}
        else:
            role = "aggregator"
            if phase == "historytaking":
                self.rounds += 1
                complete = self.rounds >= self.complete_after
                result = {"next_question_to_patient": "" if complete else "What examination results were you told?",
                          "historytaking_complete": complete, "updated_case_features": features(complete)}
            else:
                result = {"diagnosis_and_plan": {"preliminary_diagnosis": "CONTROLLED_DIAGNOSIS",
                          "diagnosis_discussion": "CONTROLLED_DISCUSSION", "treatment_plan": "CONTROLLED_PLAN", "complete": True}}
        self.requests.append({"role": role, "phase": phase, "system": system, "payload": payload})
        self.active_requests += 1
        self.peak = max(self.peak, self.active_requests)
        await asyncio.sleep(0)
        self.active_requests -= 1
        text = result if isinstance(result, str) else json.dumps(result)
        return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})


class DatasetTests(unittest.TestCase):
    def test_all_main_encounters_only_and_no_reference_note_in_record(self):
        cases = load_encounters(ROOT.parent / "aci-bench-corpus", "all", None, 0)
        self.assertEqual(len(cases), 207)
        self.assertEqual(len({case.encounter_id for case in cases}), 207)
        self.assertNotIn("note", {field.name for field in fields(Encounter)})
        self.assertTrue(all("challenge_data" in case.source_file for case in cases))
        self.assertEqual(load_encounters(ROOT.parent / "aci-bench-corpus", "train", "D2N001", 1)[0].encounter_id, "D2N001")

    def test_missing_selection_is_an_error(self):
        with self.assertRaises(ValueError):
            load_encounters(ROOT.parent / "aci-bench-corpus", "train", "NOT_PRESENT", 1)

    def test_all_runtime_prompts_are_english_and_renderable(self):
        for phase in ("historytaking", "diagnosis_and_plan"):
            for role in ("orchestrator", "specialist", "aggregator"):
                text = doctor_prompt(role, phase, "cardiology")
                self.assertNotRegex(text, r"[\u4e00-\u9fff]")
        self.assertIn("absent from the source", patient_prompt("HIDDEN_SOURCE_TOKEN"))

    def test_completion_requires_five_populated_fields(self):
        value = {"historytaking_complete": True, "next_question_to_patient": "", "updated_case_features": features(True)}
        value["updated_case_features"]["aux_exam"] = ""
        with self.assertRaises(ValidationError):
            AggregatorHistoryOutput.model_validate(value)

    def test_worked_reference_cases_are_not_in_active_prompts(self):
        for phase in ("historytaking", "diagnosis_and_plan"):
            for role in ("specialist", "aggregator"):
                text = doctor_prompt(role, phase, "cardiology")
                for example_value in ("170/102", "150/90", "62 years old", "grade 2 hypertension (moderate risk)"):
                    self.assertNotIn(example_value, text)
        original = ROOT / "prompts/original_en/guidance/diagnosis_and_plan.prompt"
        self.assertIn("grade 2 hypertension (moderate risk)", original.read_text())

    def test_features_are_immutable(self):
        case = CaseFeatures()
        with self.assertRaises(ValidationError):
            case.basic_info = "mutated"


class ConsultationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.endpoint = ControlledEndpoint()
        self.client = self.make_client(self.endpoint)
        self.encounter = Encounter("train", "TEST001", "test", "HIDDEN_SOURCE_TOKEN", "test.csv")
        self.run = create_run(self.directory, {}, [self.encounter])
        self.output = CaseOutput(self.run, "train", "TEST001")

    def make_client(self, endpoint):
        return ModelClient("http://test/v1", "Qwen3-14B", "PRIVATE_TEST_API_KEY", retries=2,
                           transport=httpx.MockTransport(endpoint))

    async def asyncTearDown(self):
        await self.client.close()
        self.temporary.cleanup()

    async def test_full_loop_isolation_specialist_reuse_freeze_and_outputs(self):
        await self.client.check()
        await Consultation(self.client, self.output).run(self.encounter, max_turns=3)
        self.assertEqual(self.endpoint.turns, 2)
        self.assertEqual(self.endpoint.peak, 1)
        for request in self.endpoint.requests:
            serialized = json.dumps(request)
            self.assertEqual("HIDDEN_SOURCE_TOKEN" in serialized, request["role"] == "patient")
            if request["role"] == "specialist":
                self.assertNotIn("specialist_outputs", request["payload"])
            if request["phase"] == "diagnosis_and_plan":
                self.assertNotIn("recent_consultation", request["payload"])
                self.assertNotIn("recent_patient_responses", request["payload"])
        diagnostic_specialists = [r for r in self.endpoint.requests if r["role"] == "specialist" and r["phase"] == "diagnosis_and_plan"]
        self.assertEqual(len(diagnostic_specialists), 2)
        self.assertTrue(any("focusing on cardiology" in r["system"] for r in diagnostic_specialists))
        self.assertTrue(any("focusing on psychiatry" in r["system"] for r in diagnostic_specialists))
        note = json.loads((self.output.directory / "soap_note.json").read_text())
        self.assertEqual(note["case_features"], features(True))
        self.assertEqual(note["stop_reason"], "history_complete")
        self.assertEqual(set(note["soap"]), {"subjective", "objective", "assessment", "plan"})
        self.assertTrue((self.output.directory / "soap_note.md").exists())
        conversation = (self.output.details / "consultation.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(line)["role"] for line in conversation], ["doctor", "patient", "doctor", "patient"])
        self.assertNotIn("PRIVATE_TEST_API_KEY", (self.output.details / "agent_trace.jsonl").read_text())

    async def test_turn_limit_does_not_claim_history_is_complete(self):
        self.endpoint.complete_after = 99
        await Consultation(self.client, self.output).run(self.encounter, max_turns=1)
        note = json.loads((self.output.directory / "soap_note.json").read_text())
        self.assertFalse(note["case_features"]["complete"])
        self.assertEqual(note["stop_reason"], "max_turns")

    async def test_resume_reuses_saved_patient_answer_after_specialist_failure(self):
        self.endpoint.fail_specialist = True
        with patch("agentic_pipeline.client.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await Consultation(self.client, self.output).run(self.encounter, max_turns=2)
        self.endpoint.fail_specialist = False
        resumed = CaseOutput(self.run, "train", "TEST001", resume=True)
        await Consultation(self.client, resumed).run(self.encounter, max_turns=2, resume=True)
        records = [json.loads(line) for line in (resumed.details / "consultation.jsonl").read_text().splitlines()]
        self.assertEqual(self.endpoint.turns, 2)
        self.assertEqual([r["role"] for r in records], ["doctor", "patient", "doctor", "patient"])
        messages = [json.loads(line) for line in (resumed.details / "agent_messages.jsonl").read_text().splitlines()]
        self.assertEqual([m["sequence"] for m in messages], list(range(1, len(messages) + 1)))
        trace = [json.loads(line) for line in (resumed.details / "agent_trace.jsonl").read_text().splitlines()]
        self.assertEqual(len({r["event_id"] for r in trace}), len(trace))

    async def test_legacy_resume_without_checkpoint_reuses_answers(self):
        self.endpoint.fail_specialist = True
        with patch("agentic_pipeline.client.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await Consultation(self.client, self.output).run(self.encounter, max_turns=2)
        (self.output.details / "checkpoint.json").unlink()
        self.endpoint.fail_specialist = False
        resumed = CaseOutput(self.run, "train", "TEST001", resume=True)
        await Consultation(self.client, resumed).run(self.encounter, max_turns=2, resume=True)
        self.assertEqual(self.endpoint.turns, 2)
        self.assertTrue(finished_case(resumed.directory))

    async def test_resume_after_question_does_not_append_question_again(self):
        self.output.conversation("doctor", "A saved opening question?", 1)
        resumed = CaseOutput(self.run, "train", "TEST001", resume=True)
        await Consultation(self.client, resumed).run(self.encounter, max_turns=2, resume=True)
        records = [json.loads(line) for line in (resumed.details / "consultation.jsonl").read_text().splitlines()]
        self.assertEqual([r["role"] for r in records], ["doctor", "patient", "doctor", "patient"])
        self.assertEqual(records[0]["content"], "A saved opening question?")
        first_patient = next(r for r in self.endpoint.requests if r["role"] == "patient")
        self.assertEqual(first_patient["payload"]["simulated_consultation"][-1]["content"], "A saved opening question?")

    async def test_resume_retries_diagnosis_without_restarting_history(self):
        original = self.endpoint.__call__
        async def fail_diagnosis(request):
            if request.url.path.endswith("chat/completions"):
                body = json.loads(request.content)
                if "Current phase: diagnosis_and_plan\n" in body["messages"][0]["content"]:
                    return httpx.Response(503, text="Diagnosis interrupted")
            return await original(request)
        broken_client = self.make_client(fail_diagnosis)
        try:
            with patch("agentic_pipeline.client.asyncio.sleep", new=AsyncMock()):
                with self.assertRaises(RuntimeError):
                    await Consultation(broken_client, self.output).run(self.encounter, max_turns=2)
        finally:
            await broken_client.close()
        history_before = (self.output.details / "consultation.jsonl").read_bytes()
        resumed = CaseOutput(self.run, "train", "TEST001", resume=True)
        await Consultation(self.client, resumed).run(self.encounter, max_turns=2, resume=True)
        self.assertEqual(self.endpoint.turns, 2)
        self.assertEqual(history_before, (self.output.details / "consultation.jsonl").read_bytes())
        self.assertEqual(json.loads((resumed.directory / "soap_note.json").read_text())["turns"], 2)

    async def test_logs_newer_than_checkpoint_preserve_latest_answer(self):
        self.endpoint.fail_specialist = True
        with patch("agentic_pipeline.client.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await Consultation(self.client, self.output).run(self.encounter, max_turns=2)
        checkpoint = self.output.details / "checkpoint.json"
        saved = json.loads(checkpoint.read_text())
        saved["state"]["history"] = saved["state"]["history"][:1]
        saved["message_sequence"] = 1
        checkpoint.write_text(json.dumps(saved))
        self.endpoint.fail_specialist = False
        resumed = CaseOutput(self.run, "train", "TEST001", resume=True)
        await Consultation(self.client, resumed).run(self.encounter, max_turns=2, resume=True)
        self.assertEqual(self.endpoint.turns, 2)

    async def test_resume_recreates_note_from_accepted_diagnosis_without_model_calls(self):
        await Consultation(self.client, self.output).run(self.encounter, max_turns=2)
        (self.output.directory / "soap_note.md").unlink()
        (self.output.details / "checkpoint.json").unlink()
        self.assertFalse(finished_case(self.output.directory))
        requests_before = len(self.endpoint.requests)
        resumed = CaseOutput(self.run, "train", "TEST001", resume=True)
        await Consultation(self.client, resumed).run(self.encounter, max_turns=2, resume=True)
        self.assertEqual(len(self.endpoint.requests), requests_before)
        self.assertTrue(finished_case(resumed.directory))

    async def test_agent_exchanges_have_order_identity_and_trace_links(self):
        await Consultation(self.client, self.output).run(self.encounter, max_turns=2)
        messages = [json.loads(line) for line in (self.output.details / "agent_messages.jsonl").read_text().splitlines()]
        trace = [json.loads(line) for line in (self.output.details / "agent_trace.jsonl").read_text().splitlines()]
        ids = {event["event_id"] for event in trace}
        self.assertEqual([message["sequence"] for message in messages], list(range(1, len(messages) + 1)))
        for message in messages:
            self.assertEqual(message["encounter_id"], "TEST001")
            self.assertEqual(message["split"], "train")
            self.assertIn(message["turn"], (1, 2))
            self.assertTrue(message["sender"] and message["recipient"] and message["content"])
            if message["source_event_id"]:
                self.assertIn(message["source_event_id"], ids)
        self.assertEqual(sum(message["kind"] == "question" for message in messages), 2)
        self.assertEqual(sum(message["kind"] == "answer" for message in messages), 2)
        self.assertEqual(sum(message["kind"] == "diagnosis_and_plan" for message in messages), 1)
        self.assertTrue(any(message["sender"] == "specialist:cardiology" and message["recipient"] == "aggregator" for message in messages))

    async def test_readable_files_are_separate_from_raw_prompts(self):
        await Consultation(self.client, self.output).run(self.encounter, max_turns=2)
        self.assertEqual({path.name for path in self.output.directory.iterdir()},
                         {"soap_note.md", "soap_note.json", "consultation.md", "agent_conversation.md", "details"})
        conversation = (self.output.directory / "consultation.md").read_text()
        agent_conversation = (self.output.directory / "agent_conversation.md").read_text()
        self.assertIn("**Doctor:**", conversation)
        self.assertIn("PATIENT_REPLY_2", conversation)
        self.assertIn("CONTROLLED_SPECIALIST_PROPOSAL", agent_conversation)
        self.assertIn("Proposed next question", agent_conversation)
        self.assertNotIn("HIDDEN_SOURCE_TOKEN", agent_conversation)
        self.assertNotIn("Return exactly one JSON object", agent_conversation)
        self.assertTrue((self.output.details / "status.json").exists())

    async def test_failed_case_keeps_readable_and_structured_conversation(self):
        self.endpoint.fail_specialist = True
        with patch("agentic_pipeline.client.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await Consultation(self.client, self.output).run(self.encounter, max_turns=1)
        self.assertIn("PATIENT_REPLY_1", (self.output.directory / "consultation.md").read_text())
        messages = [json.loads(line) for line in (self.output.details / "agent_messages.jsonl").read_text().splitlines()]
        self.assertTrue(any(message["kind"] == "answer" for message in messages))
        self.assertEqual(json.loads((self.output.details / "status.json").read_text())["status"], "failed")

    async def test_direct_followup_path_without_specialist_activation(self):
        self.endpoint.no_specialists = True
        await Consultation(self.client, self.output).run(self.encounter, max_turns=2)
        self.assertFalse(any(request["role"] == "specialist" for request in self.endpoint.requests))
        note = json.loads((self.output.directory / "soap_note.json").read_text())
        self.assertEqual(note["activated_specialists"], [])
        self.assertEqual(note["stop_reason"], "history_complete")

    async def test_schema_repair_is_bounded_and_logged(self):
        self.endpoint.invalid_once = True
        with patch("agentic_pipeline.client.asyncio.sleep", new=AsyncMock()):
            await Consultation(self.client, self.output).run(self.encounter, max_turns=1)
        trace = [json.loads(line) for line in (self.output.details / "agent_trace.jsonl").read_text().splitlines()]
        self.assertTrue(any(event["event"] == "retry" and event["agent"] == "orchestrator" for event in trace))

    async def test_specialist_failure_saves_failure_and_no_final_note(self):
        self.endpoint.fail_specialist = True
        with patch("agentic_pipeline.client.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await Consultation(self.client, self.output).run(self.encounter, max_turns=1)
        self.assertEqual(json.loads((self.output.details / "status.json").read_text())["status"], "failed")
        self.assertFalse((self.output.directory / "soap_note.md").exists())

    async def test_preflight_checks_model_name(self):
        self.client.model = "wrong-model"
        with self.assertRaises(ModelError):
            await self.client.check()

    async def test_context_retry_keeps_source_and_reduces_only_old_chat(self):
        calls = []

        async def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            if len(calls) == 1:
                return httpx.Response(400, json={"detail": "Prompt has 9000 tokens; with max_tokens=512 it exceeds the 8192-token context limit."})
            return httpx.Response(200, json={"choices": [{"message": {"content": "Patient reply"}, "finish_reason": "stop"}]})

        client = self.make_client(handler)
        try:
            await client.complete(agent="patient", phase="historytaking", system="FULL_SOURCE_MUST_STAY",
                                  payload={"simulated_consultation": [{"role": "doctor", "content": str(i)} for i in range(10)]},
                                  output=None, max_tokens=512, temperature=0.1, log=self.output)
        finally:
            await client.close()
        self.assertEqual(calls[0]["messages"][0], calls[1]["messages"][0])
        self.assertEqual(len(json.loads(calls[1]["messages"][1]["content"])["simulated_consultation"]), 2)

    async def test_cli_reference_note_never_reaches_any_agent(self):
        fixture = self.directory / "dataset/challenge_data"
        fixture.mkdir(parents=True)
        with (fixture / "train.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["dataset", "encounter_id", "dialogue", "note"])
            writer.writeheader()
            writer.writerow({"dataset": "test", "encounter_id": "T001", "dialogue": "HIDDEN_SOURCE_TOKEN", "note": "GOLD_NOTE_SECRET"})
        args = parser().parse_args(["--dataset-dir", str(fixture.parent), "--output-dir", str(self.directory / "cli-output"), "--max-turns", "2"])
        with patch("agentic_pipeline.cli.ModelClient", return_value=self.client):
            result = await execute(args)
        self.assertEqual(result, 0)
        for path in (self.directory / "cli-output").rglob("*"):
            if path.is_file():
                text = path.read_text()
                self.assertNotIn("GOLD_NOTE_SECRET", text)
                self.assertNotIn("PRIVATE_TEST_API_KEY", text)


class ResumeBatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dataset = self.root / "dataset"
        (self.dataset / "challenge_data").mkdir(parents=True)
        for name in ("train.csv", "valid.csv", "clinicalnlp_taskB_test1.csv", "clinicalnlp_taskC_test2.csv", "clef_taskC_test3.csv"):
            with (self.dataset / "challenge_data" / name).open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["dataset", "encounter_id", "dialogue", "note"])
                writer.writeheader()
                if name == "train.csv":
                    writer.writerow({"dataset": "test", "encounter_id": "T001", "dialogue": "HIDDEN_SOURCE_TOKEN", "note": "GOLD_SECRET"})
        self.args = parser().parse_args(["--dataset-dir", str(self.dataset), "--output-dir", str(self.root / "outputs"), "--max-turns", "2"])
        self.endpoint = ControlledEndpoint()

    async def asyncTearDown(self):
        self.temporary.cleanup()

    async def execute(self):
        client = ModelClient("http://test/v1", "Qwen3-14B", "TEST_KEY", retries=1,
                             transport=httpx.MockTransport(self.endpoint))
        with patch("agentic_pipeline.cli.ModelClient", return_value=client):
            return await execute(self.args)

    async def test_resume_cli_skips_completed_notes_without_creating_another_run(self):
        self.assertEqual(await self.execute(), 0)
        run = next(self.args.output_dir.iterdir())
        note = run / "train/T001/soap_note.json"
        before = (note.read_bytes(), note.stat().st_mtime_ns, self.endpoint.turns)
        self.args.resume = "latest"
        self.assertEqual(await self.execute(), 0)
        self.assertEqual((note.read_bytes(), note.stat().st_mtime_ns, self.endpoint.turns), before)
        self.assertEqual(list(self.args.output_dir.iterdir()), [run])
        manifest = json.loads((run / "run_manifest.json").read_text())
        self.assertEqual(len(manifest["resume_attempts"]), 1)
        self.assertEqual(manifest["status"], "completed")

    async def test_resume_retries_failed_case_in_same_run_and_reuses_patient_answer(self):
        self.endpoint.fail_specialist = True
        self.assertEqual(await self.execute(), 1)
        self.endpoint.fail_specialist = False
        self.args.resume = "latest"
        self.assertEqual(await self.execute(), 0)
        self.assertEqual(self.endpoint.turns, 2)
        self.assertEqual(len(list(self.args.output_dir.iterdir())), 1)
        run = next(self.args.output_dir.iterdir())
        self.assertTrue(finished_case(run / "train/T001"))

    async def test_resume_refuses_changed_source_before_touching_manifest(self):
        self.assertEqual(await self.execute(), 0)
        self.args.resume = "latest"
        run, _ = resume_run(self.args)
        before = (run / "run_manifest.json").read_bytes()
        path = self.dataset / "challenge_data/train.csv"
        path.write_text(path.read_text().replace("HIDDEN_SOURCE_TOKEN", "CHANGED_SOURCE"))
        with self.assertRaisesRegex(ValueError, "Source conversation changed"):
            resume_run(self.args)
        self.assertEqual((run / "run_manifest.json").read_bytes(), before)

    async def test_resume_refuses_changed_prompts_or_settings(self):
        self.assertEqual(await self.execute(), 0)
        self.args.resume = "latest"
        run, _ = resume_run(self.args)
        self.args.max_turns = 3
        with self.assertRaisesRegex(ValueError, "original --model and --max-turns"):
            resume_run(self.args)
        self.args.max_turns = 2
        path = run / "run_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["prompt_sha256"]["adaptations/doctor.prompt"] = "changed"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Prompts changed"):
            resume_run(self.args)

    def test_generation_lock_blocks_a_second_writer_and_releases_after_exit(self):
        with generation_lock(self.args.output_dir):
            with self.assertRaisesRegex(ValueError, "Another generation process"):
                with generation_lock(self.args.output_dir):
                    self.fail("Second writer acquired the lock")
        with generation_lock(self.args.output_dir):
            pass
        self.assertEqual(list(self.args.output_dir.iterdir()), [])


class LauncherTests(unittest.TestCase):
    def test_full_dataset_launcher_forwards_defaults_and_user_options(self):
        with tempfile.TemporaryDirectory(prefix="soap launcher ") as temp:
            folder = Path(temp)
            (folder / "generate_soap.sh").write_text((ROOT / "generate_soap.sh").read_text())
            (folder / "req.txt").write_text("# Controlled launcher test\n")
            (folder / ".venv/bin").mkdir(parents=True)
            (folder / ".venv/bin/activate").write_text('export SOAP_LAUNCHER_ACTIVATED=yes\n')
            python = folder / ".venv/bin/python"
            python.write_text('#!/bin/bash\n[[ "$SOAP_LAUNCHER_ACTIVATED" == yes ]] || exit 1\nprintf "%s\\n" "$@"\n')
            python.chmod(0o755)
            digest = hashlib.sha256((folder / "req.txt").read_bytes()).hexdigest()
            (folder / ".venv/requirements.sha256").write_text(digest + "\n")
            result = subprocess.run(["bash", str(folder / "generate_soap.sh"), "--split", "train", "--limit", "1"],
                                    text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.splitlines(), ["-m", "agentic_pipeline.cli", "--split", "all", "--limit", "0", "--split", "train", "--limit", "1"])


if __name__ == "__main__":
    unittest.main()
