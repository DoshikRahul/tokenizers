"""Aegle's per-turn LangGraph and outer standardized-patient consultation loop."""
import asyncio
import json
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langsmith import tracing_context

from .patient import PatientAgent
from .outputs import read_jsonl
from .prompts import doctor_prompt
from .schemas import (AggregatorDiagnosisOutput, AggregatorHistoryOutput, CaseFeatures,
                      DiagnosisAndPlan, FEATURE_FIELDS, OrchestratorDecision, SpecialistOutput)


class ConsultationState(TypedDict):
    phase: str
    history: list[dict]
    features: CaseFeatures
    activated: list[str]
    active: list[str]
    instructions: str
    suggested_question: str | None
    specialist_outputs: list[dict]
    next_question: str
    history_complete: bool
    diagnosis: DiagnosisAndPlan | None


class Consultation:
    def __init__(self, client, log):
        self.client = client
        self.log = log
        graph = StateGraph(ConsultationState)
        graph.add_node("orchestrator", self.orchestrator)
        graph.add_node("specialists", self.specialists)
        graph.add_node("aggregator", self.aggregator)
        graph.set_entry_point("orchestrator")
        graph.add_edge("orchestrator", "specialists")
        graph.add_edge("specialists", "aggregator")
        graph.add_edge("aggregator", END)
        self.graph = graph.compile()

    async def invoke(self, state):
        # Keep the case trace in the output folder, even if a shell has global
        # LangSmith tracing enabled for some other project.
        with tracing_context(enabled=False):
            return await self.graph.ainvoke(state, config={"callbacks": []})

    async def orchestrator(self, state: ConsultationState):
        if state["phase"] == "diagnosis_and_plan":
            # Match Aegle/manager.py: reuse all specialists activated during history.
            self.log.event({"event": "diagnosis_routing", "specialists": state["activated"],
                            "instructions": "Evidence is frozen. Provide preliminary diagnosis, diagnostic discussion and a treatment plan without asking further questions."})
            return {"active": list(state["activated"]), "specialist_outputs": [],
                    "instructions": "Evidence is frozen. Provide preliminary diagnosis, diagnostic discussion and a treatment plan without asking further questions."}
        decision = await self.client.complete(
            agent="orchestrator", phase=state["phase"], system=doctor_prompt("orchestrator", state["phase"]),
            payload={"case_features": state["features"].model_dump(), "recent_consultation": state["history"][-10:]},
            output=OrchestratorDecision, max_tokens=512, temperature=0.2, log=self.log,
        )
        return {"active": decision.active_specialists,
                "activated": list(dict.fromkeys(state["activated"] + decision.active_specialists)),
                "instructions": decision.instructions_to_specialists,
                "suggested_question": decision.suggested_question, "specialist_outputs": []}

    async def specialists(self, state: ConsultationState):
        # Every specialist sees the same evidence, never another specialist's proposal.
        base = {"case_features": state["features"].model_dump(), "orchestrator_instructions": state["instructions"]}
        if state["phase"] == "historytaking":
            base["recent_patient_responses"] = [entry["content"] for entry in state["history"] if entry["role"] == "patient"][-3:]

        async def call(identifier):
            result = await self.client.complete(
                agent=f"specialist:{identifier}", phase=state["phase"],
                system=doctor_prompt("specialist", state["phase"], identifier), payload=base,
                output=SpecialistOutput, max_tokens=1024, temperature=0.2, log=self.log,
            )
            return {"specialist_id": identifier, **result.model_dump()}

        results = await asyncio.gather(*(call(identifier) for identifier in state["active"]), return_exceptions=True)
        errors = [value for value in results if isinstance(value, BaseException)]
        if errors:
            raise RuntimeError(f"Specialist failed; no final note will be marked successful: {errors[0]}") from errors[0]
        return {"specialist_outputs": results}

    async def aggregator(self, state: ConsultationState):
        payload = {"case_features": state["features"].model_dump(), "specialist_outputs": state["specialist_outputs"],
                   "orchestrator_instructions": state["instructions"]}
        if state["phase"] == "historytaking":
            payload.update(latest_patient_response=state["history"][-1]["content"], suggested_question=state["suggested_question"])
            result = await self.client.complete(
                agent="aggregator", phase=state["phase"], system=doctor_prompt("aggregator", state["phase"]),
                payload=payload, output=AggregatorHistoryOutput, max_tokens=2048, temperature=0.2, log=self.log,
            )
            features = result.updated_case_features.model_copy(update={"complete": result.historytaking_complete})
            return {"features": features, "history_complete": result.historytaking_complete,
                    "next_question": result.next_question_to_patient.strip()}
        result = await self.client.complete(
            agent="aggregator", phase=state["phase"], system=doctor_prompt("aggregator", state["phase"]),
            payload=payload, output=AggregatorDiagnosisOutput, max_tokens=2048, temperature=0.2, log=self.log,
        )
        return {"diagnosis": result.diagnosis_and_plan.model_copy(update={"complete": True})}

    def checkpoint(self, state, completed_turns):
        self.log.save("checkpoint.json", {
            "version": 1, "completed_turns": completed_turns,
            "trace_sequence": self.log.trace_sequence, "message_sequence": self.log.sequence,
            "state": {**state, "features": state["features"].model_dump(),
                      "diagnosis": state["diagnosis"].model_dump() if state["diagnosis"] else None},
        })

    def restore(self, initial):
        checkpoint = self.log.details / "checkpoint.json"
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text())
            if saved.get("version") != 1:
                raise ValueError("Unsupported consultation checkpoint version.")
            # A process can die after appending a reply but before replacing the
            # checkpoint. Prefer the newer accepted log records in that case.
            records = read_jsonl(self.log.details / "consultation.jsonl")
            if (saved.get("trace_sequence") == self.log.trace_sequence
                    and saved.get("message_sequence") == self.log.sequence
                    and len(records) == len(saved["state"]["history"])):
                state = saved["state"]
                state["features"] = CaseFeatures.model_validate(state["features"])
                if state["diagnosis"] is not None:
                    state["diagnosis"] = DiagnosisAndPlan.model_validate(state["diagnosis"])
                return state, saved["completed_turns"]

        # Older runs predate checkpoints. Recover accepted evidence and pending
        # Q&A from the saved logs, never from the source or reference note.
        state = dict(initial)
        completed_turns = 0
        state["history"] = [{"role": e["role"], "content": e["content"]}
                            for e in read_jsonl(self.log.details / "consultation.jsonl")]
        for event in read_jsonl(self.log.details / "agent_trace.jsonl"):
            if event["event"] == "validated":
                output = event["output"]
                if event["agent"] == "orchestrator" and event["phase"] == "historytaking":
                    state["activated"] = list(dict.fromkeys(state["activated"] + output["active_specialists"]))
                elif event["agent"] == "aggregator" and event["phase"] == "historytaking":
                    result = AggregatorHistoryOutput.model_validate(output)
                    state["features"] = result.updated_case_features.model_copy(update={"complete": result.historytaking_complete})
                    state["history_complete"] = result.historytaking_complete
                    state["next_question"] = result.next_question_to_patient.strip()
                    completed_turns = event["turn"]
                elif event["agent"] == "aggregator" and event["phase"] == "diagnosis_and_plan":
                    state["diagnosis"] = AggregatorDiagnosisOutput.model_validate(output).diagnosis_and_plan.model_copy(update={"complete": True})
            elif event["event"] == "evidence_frozen":
                state["phase"] = "diagnosis_and_plan"
        if not 2 * completed_turns <= len(state["history"]) <= 2 * completed_turns + 2:
            raise ValueError("Saved conversation and completed turns disagree; preserving the logs for inspection.")
        return state, completed_turns

    async def run(self, encounter, *, max_turns: int, resume: bool = False):
        patient = PatientAgent(encounter.dialogue, self.client, self.log)
        state: ConsultationState = {
            "phase": "historytaking", "history": [], "features": CaseFeatures(), "activated": [], "active": [],
            "instructions": "", "suggested_question": None, "specialist_outputs": [],
            "next_question": "Hello. Could you tell me your age and gender, and what brings you in today?",
            "history_complete": False, "diagnosis": None,
        }
        completed_turns = 0
        if resume:
            state, completed_turns = self.restore(state)
            self.log.event({"event": "resumed", "phase": state["phase"], "completed_turns": completed_turns})
            self.log.message(sender="pipeline", recipient="doctor_team", phase=state["phase"],
                             kind="resumed", content=f"Resuming after {completed_turns} completed history-taking turns. Saved questions and patient answers are reused.")
        self.log.status(status="running", encounter_id=encounter.encounter_id, turns=completed_turns)
        turns = completed_turns
        self.checkpoint(state, completed_turns)
        try:
            for turn in range(completed_turns + 1, max_turns + 1):
                if state["history_complete"] or state["phase"] == "diagnosis_and_plan":
                    break
                turns = turn
                print(f"  {encounter.encounter_id}: consultation turn {turn}/{max_turns}", flush=True)
                self.log.turn = turn
                if len(state["history"]) == 2 * completed_turns:
                    question = state["next_question"]
                    state["history"] = state["history"] + [{"role": "doctor", "content": question}]
                    self.log.conversation("doctor", question, turn)
                    self.checkpoint(state, completed_turns)
                if state["history"][-1]["role"] == "doctor":
                    response = await patient.answer(state["history"])
                    state["history"] = state["history"] + [{"role": "patient", "content": response}]
                    self.log.conversation("patient", response, turn)
                    self.checkpoint(state, completed_turns)
                state = await self.invoke(state)
                completed_turns = turn
                self.checkpoint(state, completed_turns)
                self.log.save("case_features.json", state["features"].model_dump())
                self.log.save("activated_specialists.json", state["activated"])
                self.log.status(status="running", encounter_id=encounter.encounter_id, turns=turn,
                                historytaking_complete=state["history_complete"])
                if state["history_complete"]:
                    break
            stop_reason = "history_complete" if state["history_complete"] else "max_turns"
            uncollected = [field for field in FEATURE_FIELDS if not getattr(state["features"], field).strip()]
            frozen = state["features"]
            self.log.event({"event": "evidence_frozen", "stop_reason": stop_reason,
                            "case_features": frozen.model_dump(), "uncollected_fields": uncollected})
            print(f"  {encounter.encounter_id}: generating diagnosis and plan ({stop_reason})", flush=True)
            state = {**state, "phase": "diagnosis_and_plan", "active": [],
                     "specialist_outputs": [], "suggested_question": None}
            self.checkpoint(state, completed_turns)
            if state["diagnosis"] is None:
                state = await self.invoke(state)
                self.checkpoint(state, completed_turns)
            if state["features"] != frozen:
                raise RuntimeError("Frozen evidence changed during diagnostic synthesis.")
            self.log.final_note(encounter.encounter_id, frozen, state["diagnosis"], stop_reason=stop_reason,
                                turns=turns, specialists=state["activated"], uncollected=uncollected)
            self.log.status(status="completed", encounter_id=encounter.encounter_id, turns=turns,
                            historytaking_complete=frozen.complete, stop_reason=stop_reason, uncollected_fields=uncollected)
        except BaseException as exc:
            self.log.save("case_features.json", state["features"].model_dump())
            self.log.status(status="interrupted" if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)) else "failed",
                            encounter_id=encounter.encounter_id, turns=turns, error=str(exc))
            raise
