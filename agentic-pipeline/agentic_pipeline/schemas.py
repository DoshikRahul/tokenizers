"""English schemas adapted from Aegle/shared/data_models.py (Huangwei Chen, 2026)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FEATURE_FIELDS = ("basic_info", "present_illness", "past_history", "physical_exam", "aux_exam")
Phase = Literal["historytaking", "diagnosis_and_plan"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CaseFeatures(Record):
    basic_info: str = Field(default="", description="Patient demographics and chief complaint.")
    present_illness: str = Field(default="", description="Onset, symptoms, course, prior evaluation and response.")
    past_history: str = Field(default="", description="Past illnesses, surgery, allergies, medications, personal and family history.")
    physical_exam: str = Field(default="", description="Documented vital signs and examination findings; never invent values.")
    aux_exam: str = Field(default="", description="Available laboratory, imaging and other test results, with timing and units.")
    complete: bool = False


class DiagnosisAndPlan(Record):
    preliminary_diagnosis: str = Field(min_length=1, description="Diagnoses supported by finalized case features. Distinguish established from tentative; do not assign unsupported subtypes, stages, grades or risk categories.")
    diagnosis_discussion: str = Field(min_length=1, description="Diagnostic evidence, uncertainty and relevant differential diagnoses.")
    treatment_plan: str = Field(min_length=1, description="Proposed further evaluation, treatment, education and follow-up.")
    complete: bool = False


class OrchestratorDecision(Record):
    active_specialists: list[str] = Field(description="Relevant specialist IDs in snake_case, or [] for a simple direct follow-up.", max_length=8)
    instructions_to_specialists: str = Field(min_length=1, description="Shared instructions, or direct instructions to the aggregator when no specialist is needed.")
    suggested_question: str | None = Field(description="Direct follow-up question for simple cases; otherwise null.")

    @model_validator(mode="after")
    def specialist_ids(self):
        import re
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) for value in self.active_specialists):
            raise ValueError("Use specialist IDs such as general_practice, cardiology, or psychiatry.")
        if len(set(self.active_specialists)) != len(self.active_specialists):
            raise ValueError("Do not repeat specialist IDs.")
        return self


class SpecialistOutput(Record):
    next_question: str = Field(description="A targeted next question; use N/A in diagnosis_and_plan.")
    draft_modifications: str = Field(min_length=1, description="Proposed revisions with exact case-feature fields, or structured diagnosis/plan proposals.")


class AggregatorHistoryOutput(Record):
    next_question_to_patient: str
    historytaking_complete: bool
    updated_case_features: CaseFeatures

    @model_validator(mode="after")
    def completion_is_consistent(self):
        if self.historytaking_complete:
            if any(not getattr(self.updated_case_features, field).strip() for field in FEATURE_FIELDS):
                raise ValueError("Complete history requires all five fields populated, including explicit patient-confirmed unavailability.")
        elif not self.next_question_to_patient.strip():
            raise ValueError("Provide a follow-up question when history taking is not complete.")
        return self


class AggregatorDiagnosisOutput(Record):
    diagnosis_and_plan: DiagnosisAndPlan
