"""Interactive sessions that drive the project's Aegle-style LangGraph.

The doctor team (orchestrator -> specialists -> aggregator) is the unmodified
``agentic_pipeline.consultation.Consultation`` graph. Only the outer loop is
re-implemented here so that it can stream events to the browser and so that
the *patient* can be either the human user (chat mode) or the project's
standardized ``PatientAgent`` grounded in an ACI-Bench dialogue (simulate mode).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

from agentic_pipeline.consultation import Consultation
from agentic_pipeline.patient import PatientAgent
from agentic_pipeline.schemas import FEATURE_FIELDS, CaseFeatures

FIRST_QUESTION = "Hello. Could you tell me your age and gender, and what brings you in today?"
FIELD_LABELS = {"basic_info": "Basic information", "present_illness": "Present illness",
                "past_history": "Past history", "physical_exam": "Physical examination",
                "aux_exam": "Investigations"}

Emit = Callable[[dict], None]


def soap_sections(features, diagnosis) -> dict:
    """Same section layout as agentic_pipeline.outputs.CaseOutput.final_note."""
    def show(value):
        return value.strip() or "Not documented during the simulated consultation."

    sections = {
        "subjective": "\n\n".join(f"{label}: {show(getattr(features, field))}" for label, field in
                                  (("Basic information", "basic_info"), ("History of present illness", "present_illness"),
                                   ("Past history", "past_history"))),
        "objective": f"Physical examination: {show(features.physical_exam)}\n\nInvestigations: {show(features.aux_exam)}",
    }
    if diagnosis is not None:
        sections["assessment"] = (f"Preliminary diagnosis:\n{diagnosis.preliminary_diagnosis}\n\n"
                                  f"Diagnostic discussion:\n{diagnosis.diagnosis_discussion}")
        sections["plan"] = diagnosis.treatment_plan
    return sections


def describe_output(agent: str, phase: str, output: dict) -> tuple[str, str, str]:
    """Human-readable card text; mirrors agentic_pipeline.outputs.CaseOutput.event."""
    if agent == "orchestrator":
        recipient = ", ".join(output["active_specialists"]) or "aggregator"
        text = (f"**Selected specialists:** {', '.join(output['active_specialists']) or 'none (simple follow-up)'}\n\n"
                f"**Instructions:** {output['instructions_to_specialists']}")
        if output.get("suggested_question"):
            text += f"\n\n**Suggested question:** {output['suggested_question']}"
        return recipient, "routing", text
    if agent.startswith("specialist:"):
        return "aggregator", "specialist proposal", (
            f"**Proposed record changes:**\n\n{output['draft_modifications']}\n\n"
            f"**Suggested follow-up:** {output['next_question']}")
    if phase == "historytaking":
        text = "\n\n".join(f"**{label}:** {output['updated_case_features'].get(field) or 'Not yet collected.'}"
                           for field, label in FIELD_LABELS.items())
        text += f"\n\n**History complete:** {output['historytaking_complete']}"
        if output.get("next_question_to_patient"):
            text += f"\n\n**Proposed next question:** {output['next_question_to_patient']}"
        return "shared_record", "evidence update", text
    diagnosis = output["diagnosis_and_plan"]
    return "soap_note", "diagnosis and plan", (
        f"**Preliminary diagnosis:**\n\n{diagnosis['preliminary_diagnosis']}\n\n"
        f"**Diagnostic discussion:**\n\n{diagnosis['diagnosis_discussion']}\n\n"
        f"**Proposed plan:**\n\n{diagnosis['treatment_plan']}")


class StepQueue:
    """Global FIFO: one consultation step uses the GPUs at a time; others wait in order.

    host.py already serialises single model calls; this queue serialises whole
    steps (a patient turn = orchestrator + specialists + aggregator) so concurrent
    visitors don't interleave and slow each other down, and shows each waiting
    browser its position.
    """

    def __init__(self):
        self.waiting: list[object] = []
        self.running: str | None = None
        self.lock = asyncio.Lock()  # asyncio.Lock wakes waiters in FIFO order

    def snapshot(self) -> dict:
        return {"running": self.running, "waiting": len(self.waiting)}

    @asynccontextmanager
    async def slot(self, emit: Emit, label: str):
        ticket = object()
        self.waiting.append(ticket)
        ticker = None
        try:
            if self.lock.locked():
                async def announce():
                    while True:
                        ahead = self.waiting.index(ticket) + 1  # +1 for the step currently running
                        emit({"type": "queue", "ahead": ahead,
                              "text": f"Waiting in queue — {ahead} step(s) ahead (one consultation step runs on the GPUs at a time)…"})
                        await asyncio.sleep(3)
                ticker = asyncio.create_task(announce())
            await self.lock.acquire()
        finally:
            if ticker:
                ticker.cancel()
            self.waiting.remove(ticket)
        self.running = label
        if ticker:
            emit({"type": "queue", "ahead": 0, "text": "Your turn — the doctor team is starting."})
        try:
            yield
        finally:
            self.running = None
            self.lock.release()


QUEUE = StepQueue()


class StreamLog:
    """Implements the ``log`` interface the pipeline expects (``event`` + ``turn``)."""

    def __init__(self):
        self.turn = 0
        self.emit: Emit = lambda item: None
        self.trace: list[dict] = []
        self._started: dict[str, float] = {}

    def event(self, event: dict) -> None:
        self.trace.append({"time": time.time(), "turn": self.turn, **event})
        kind = event.get("event")
        agent = event.get("agent", "")
        phase = event.get("phase", "diagnosis_and_plan")
        if kind == "request":
            self._started[agent] = time.time()
            self.emit({"type": "agent_start", "agent": agent, "phase": phase, "turn": self.turn,
                       "attempt": event.get("attempt", 1)})
        elif kind == "response":
            usage = event.get("usage") or {}
            self.emit({"type": "agent_tokens", "agent": agent, "turn": self.turn,
                       "seconds": round(time.time() - self._started.get(agent, time.time()), 1),
                       "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")})
        elif kind == "validated":
            if agent == "patient":
                return
            recipient, card_kind, text = describe_output(agent, phase, event["output"])
            self.emit({"type": "agent", "agent": agent, "recipient": recipient, "kind": card_kind,
                       "phase": phase, "turn": self.turn, "content": text})
        elif kind == "retry":
            self.emit({"type": "notice", "level": "warn", "turn": self.turn,
                       "text": f"{agent} attempt {event.get('attempt')} failed validation; retrying. ({str(event.get('error', ''))[:240]})"})
        elif kind == "context_adjustment":
            self.emit({"type": "notice", "level": "info", "turn": self.turn,
                       "text": f"{agent}: context limit reached, compacting derived context ({event.get('action')})."})
        elif kind == "diagnosis_routing":
            specialists = event.get("specialists", [])
            self.emit({"type": "agent", "agent": "orchestrator", "recipient": ", ".join(specialists) or "aggregator",
                       "kind": "routing", "phase": "diagnosis_and_plan", "turn": self.turn,
                       "content": "Reuse the specialists activated during history taking"
                                  f" ({', '.join(specialists) or 'none'}). " + event.get("instructions", "")})


class Session:
    def __init__(self, mode: str, client, *, max_turns: int, encounter=None):
        self.id = uuid.uuid4().hex[:12]
        self.mode = mode
        self.client = client
        self.max_turns = max_turns
        self.encounter = encounter
        self.log = StreamLog()
        self.graph = Consultation(client, self.log)
        self.lock = asyncio.Lock()
        self.turns = 0
        self.finished = False
        self.stop_requested = False
        self.soap: dict | None = None
        self.created = time.time()
        self.state = {
            "phase": "historytaking", "history": [], "features": CaseFeatures(), "activated": [], "active": [],
            "instructions": "", "suggested_question": None, "specialist_outputs": [],
            "next_question": FIRST_QUESTION, "history_complete": False, "diagnosis": None,
        }

    # ----------------------------------------------------------------- helpers
    def features_event(self, emit: Emit):
        features = self.state["features"]
        emit({"type": "features", "turn": self.turns, "features": {f: getattr(features, f) for f in FEATURE_FIELDS},
              "complete": self.state["history_complete"], "activated": self.state["activated"],
              "soap": soap_sections(features, None)})

    async def _graph_turn(self, emit: Emit, patient_text: str):
        """Doctor question + patient answer are already decided; run one graph turn."""
        turn = self.turns + 1
        self.log.turn = turn
        pending = {**self.state, "history": self.state["history"] + [
            {"role": "doctor", "content": self.state["next_question"]},
            {"role": "patient", "content": patient_text}]}
        emit({"type": "phase", "phase": "historytaking", "turn": turn,
              "text": f"Turn {turn}: orchestrator → specialists → aggregator"})
        new_state = await self.graph.invoke(pending)  # only committed when the whole turn succeeds
        self.state = new_state
        self.turns = turn
        self.features_event(emit)

    async def finalize(self, emit: Emit, stop_reason: str | None = None):
        if self.finished or self.turns == 0:
            return await self._finalize(emit, stop_reason)
        async with QUEUE.slot(emit, f"{self.id}:note"):
            await self._finalize(emit, stop_reason)

    async def _finalize(self, emit: Emit, stop_reason: str | None = None):
        if self.finished:
            emit({"type": "soap", "soap": self.soap, "meta": self.meta(stop_reason or "already_finished")})
            return
        if self.turns == 0:
            raise ValueError("Answer at least one question before generating the note.")
        stop_reason = stop_reason or ("history_complete" if self.state["history_complete"] else "user_finished")
        frozen = self.state["features"]
        uncollected = [field for field in FEATURE_FIELDS if not getattr(frozen, field).strip()]
        emit({"type": "frozen", "stop_reason": stop_reason, "uncollected": uncollected, "turn": self.turns,
              "soap": soap_sections(frozen, None)})
        self.log.turn = self.turns
        state = {**self.state, "phase": "diagnosis_and_plan", "active": [], "specialist_outputs": [],
                 "suggested_question": None}
        emit({"type": "phase", "phase": "diagnosis_and_plan", "turn": self.turns,
              "text": "Evidence frozen → diagnosis & plan by the same specialist team"})
        state = await self.graph.invoke(state)
        if state["features"] != frozen:
            raise RuntimeError("Frozen evidence changed during diagnostic synthesis.")
        self.state = state
        self.finished = True
        self.soap = soap_sections(frozen, state["diagnosis"])
        emit({"type": "soap", "soap": self.soap, "meta": self.meta(stop_reason, uncollected)})

    def meta(self, stop_reason, uncollected=None):
        return {"turns": self.turns, "stop_reason": stop_reason, "activated_specialists": self.state["activated"],
                "uncollected_fields": uncollected or [], "mode": self.mode,
                "encounter_id": getattr(self.encounter, "encounter_id", None)}

    def _after_turn(self) -> str | None:
        if self.state["history_complete"]:
            return "history_complete"
        if self.turns >= self.max_turns:
            return "max_turns"
        if self.stop_requested:
            return "stopped_by_user"
        return None

    # ------------------------------------------------------------ operations
    async def chat_step(self, emit: Emit, text: str):
        if self.finished:
            raise ValueError("This consultation is finished. Start a new one.")
        async with QUEUE.slot(emit, f"{self.id}:turn{self.turns + 1}"):
            await self._graph_turn(emit, text)
            reason = self._after_turn()
            if reason:
                emit({"type": "chat", "role": "doctor", "turn": self.turns,
                      "content": "Thank you — I have what I need. I'll now write up your clinical note."})
                await self._finalize(emit, reason)
            else:
                emit({"type": "chat", "role": "doctor", "turn": self.turns + 1, "content": self.state["next_question"]})

    async def simulate(self, emit: Emit):
        patient = PatientAgent(self.encounter.dialogue, self.client, self.log)
        while not self.finished:
            # One queue slot per turn, so a long simulation never blocks live visitors for minutes.
            async with QUEUE.slot(emit, f"{self.id}:turn{self.turns + 1}"):
                turn = self.turns + 1
                self.log.turn = turn
                question = self.state["next_question"]
                emit({"type": "chat", "role": "doctor", "turn": turn, "content": question})
                answer = await patient.answer(self.state["history"] + [{"role": "doctor", "content": question}])
                emit({"type": "chat", "role": "patient", "turn": turn, "content": answer})
                await self._graph_turn(emit, answer)
                reason = self._after_turn()
                if reason:
                    await self._finalize(emit, reason)


class SessionStore:
    def __init__(self, limit: int = 64):
        self.items: OrderedDict[str, Session] = OrderedDict()
        self.limit = limit

    def add(self, session: Session) -> Session:
        self.items[session.id] = session
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return session

    def get(self, identifier: str) -> Session:
        if identifier not in self.items:
            raise KeyError("Unknown or expired session; start a new consultation.")
        return self.items[identifier]


async def sse(session: Session, work: Callable[[Emit], Awaitable[None]]):
    """Run ``work`` under the session lock and stream its events as SSE."""
    queue: asyncio.Queue = asyncio.Queue()

    def emit(item: dict):
        queue.put_nowait(item)

    async def runner():
        started = time.time()
        if session.lock.locked():
            emit({"type": "notice", "level": "info", "text": "Waiting for the previous step of this session…"})
        async with session.lock:
            session.log.emit = emit
            try:
                await work(emit)
            except Exception as exc:  # surfaced to the browser
                emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                emit({"type": "done", "seconds": round(time.time() - started, 1), "turns": session.turns,
                      "finished": session.finished})
                session.log.emit = lambda item: None
                queue.put_nowait(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"  # long GPU calls; keep tunnels/proxies from idling out
                continue
            if item is None:
                break
            yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
    finally:
        # If the browser disconnects, let the step finish so session state stays consistent.
        if not task.done():
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
