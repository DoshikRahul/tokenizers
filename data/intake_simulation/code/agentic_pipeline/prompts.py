from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "prompts"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def active_guidance(name: str) -> str:
    """Keep source translations intact; exclude worked patient examples at runtime."""
    lines = []
    skipping = False
    for line in read(name).splitlines():
        if line.strip().removeprefix("- ").startswith("Example:"):
            skipping = True
            continue
        if skipping:
            if line.strip():
                continue
            skipping = False
        lines.append(line)
    return "\n".join(lines)


def doctor_prompt(agent: str, phase: str, specialist: str = "") -> str:
    guidance_name = "historytaking" if phase == "historytaking" else "diagnosis_and_plan"
    guidance = active_guidance(f"original_en/guidance/{guidance_name}.prompt")
    if agent == "orchestrator":
        goal = (
            "Efficiently collect case features, fill gaps and clarify symptoms. Record actual basic information, present illness, past history, examination and test results. Do not formulate investigation or treatment plans."
            if phase == "historytaking" else
            "Based on frozen case features, organize specialist opinions to produce preliminary diagnosis, diagnostic discussion and a treatment plan."
        )
        prompt = read("original_en/orchestrator.prompt").format(current_phase_description=phase, phase_goal=goal)
    elif agent == "specialist":
        instructions = (
            f"From the perspective of {specialist}, review the case features and record actual clinical information. If information is insufficient, suggest a concrete question; otherwise state that no additional question is needed. Do not formulate investigation or treatment plans yet."
            if phase == "historytaking" else
            f"Based on frozen case features, provide the {specialist} perspective. Structure draft_modifications as preliminary diagnosis, diagnostic discussion (evidence and differential), and treatment plan (further evaluation, drug and non-drug measures, follow-up)."
        )
        template = read("original_en/specialist_core.prompt")
        template = "\n".join(line for line in template.splitlines() if not line.strip().startswith("- Write '"))
        template = template.replace("the exact destination field, for example:", "the exact destination field.")
        prompt = template.format(
            role_description=f"You are a specialist physician focusing on {specialist}. As an MDT member, help refine case information and provide precise diagnostic and treatment recommendations from your specialty's perspective.",
            phase_name=phase, phase_instructions=instructions, soap_guidance=guidance,
            next_question_instruction="Fill next_question with a concrete follow-up; if none, state that there is no additional question." if phase == "historytaking" else "Set next_question to 'N/A'; do not ask the patient new questions.",
        )
    else:
        task = (
            "Integrate specialist question suggestions and ask the patient. Confirm key symptoms, avoid unfamiliar medical terms, and collect all five case-feature fields. Complete history only after examination and test information has been obtained or the patient explicitly says it is unavailable."
            if phase == "historytaking" else
            "Integrate specialist opinions into preliminary diagnosis, diagnostic discussion and a treatment plan."
        )
        prompt = read("original_en/aggregator.prompt").format(
            PHASE_NAME=phase, SOAP_STRUCTURE_GUIDANCE=active_guidance(f"original_en/guidance/aggregator_{guidance_name}.prompt"),
            AGGREGATOR_TASK_DESCRIPTION=task,
        )
    return prompt + "\n\n" + read("adaptations/doctor.prompt")


def patient_prompt(dialogue: str) -> str:
    return read("original_en/sp.prompt").format(patient_view=dialogue) + "\n\n" + read("adaptations/patient.prompt")
