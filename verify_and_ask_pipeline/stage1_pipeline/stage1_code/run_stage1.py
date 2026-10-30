"""Generate Stage 1 SOAP notes using Ollama's local HTTP API.

Important: only the consultation conversation is placed in the generation prompt.
Reference S/O is carried into the output JSON for evaluation, never sent to Ollama.

Each case is checkpointed to OUTPUT_DIR/cases/<case_id>.json as soon as it finishes,
so an interrupted run (e.g. a Colab disconnect) resumes where it stopped.

Usage:
  python run_stage1.py                      # all cases, resuming finished ones
  python run_stage1.py --split dev          # only the dev split
  python run_stage1.py --limit 5            # first 5 selected cases
  python run_stage1.py --retry-errors       # also redo cases that previously failed
  python run_stage1.py --overwrite          # regenerate everything
"""
import argparse
import json
import re
import sys
import time
import requests
from config import (
    PREPARED_JSON, OUTPUT_DIR, OUTPUT_JSON, GENERATED_DIR, CASES_DIR,
    OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_NUM_CTX, TEMPERATURE,
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_BACKEND, LLM_MAX_TOKENS,
)
from soap_parse import split_soap

SYSTEM_PROMPT = """You are a clinical documentation assistant generating a faithful
SOAP note from a patient-doctor conversation.

SOURCE OF TRUTH
- Use only information explicitly stated in the conversation.
- Do not read or use the reference SOAP note when generating the note.
- Do not invent symptoms, vital signs, examination findings, investigation
  results, medication names or doses, diagnoses, or treatment decisions.
- A doctor's question does not establish that a symptom or condition is present.
- Preserve the distinction between patient-reported information and objective
  findings.
- Extract concrete details and actions from the conversation. Do not replace
  them with vague summaries.
- Do not write "Not specified" merely because information is incomplete.
  Record the information that is available and identify only what is missing.

SECTION RULES

## Subjective
Include relevant patient-reported symptoms, history, concerns, medication
adherence, lifestyle, and other details explicitly stated in the conversation.
Preserve relevant positive and negative symptoms only when the patient actually
reports them. Do not add demographic details unless stated.


## Objective
Extract all objective clinical information explicitly documented in the
consultation, including:

- Vital signs and measurements, such as blood pressure, heart rate,
  temperature, respiratory rate, oxygen saturation, and weight.
- Physical examination findings documented by the clinician.
- Laboratory results, imaging findings, and other investigation results.
- Other directly observed or measured clinical findings.

Rules:
- Include actual values and units when they are provided.
- Do not invent values, examination findings, test results, or observations.
- A patient reporting that their blood pressure rises does not establish
  an objectively measured blood pressure value.
- A doctor's question about a measurement or examination does not mean
  the measurement was obtained or the examination was performed.
- Do not move patient-reported symptoms or medical history into Objective.
- If some objective information is available, include it and identify
  only the relevant missing information when necessary.
- If no objective clinical information is documented, write:
  "No objective clinical measurements, examination findings, or
  investigation results were documented in the conversation."

## Assessment
Summarize the clinical problems or diagnoses explicitly established in the
conversation. Distinguish established history from current symptoms and
confirmed diagnoses from possibilities. Do not create new diagnoses.
If the conversation does not support a clinical assessment, state that clearly.

## Plan
Extract every explicit management or follow-up action discussed by the doctor
or patient, including medication review, requests to check medication bottles
or records, instructions, tests, referrals, and follow-up arrangements, when
these are actually mentioned.
Describe the action accurately: distinguish an action requested or proposed
from one agreed to or completed.
Do not invent treatment, medication changes, counseling, or follow-up.
If no management or follow-up action is discussed, write exactly:
"No explicit management or follow-up plan was documented in the conversation."

OUTPUT REQUIREMENTS
- Return only the SOAP note, without an introduction or closing commentary.
- Use exactly these headings in this order:
## Subjective
## Objective
## Assessment
## Plan
- Use concise, clinically appropriate bullet points.
- Avoid repeating the same information across sections unless necessary.
"""

MAX_ATTEMPTS = 3
SECTION_KEYS = ("subjective", "objective", "assessment", "plan")


MODEL_NAME = LLM_MODEL if LLM_BACKEND == "openai" else OLLAMA_MODEL


def _request_note(conversation: str) -> str:
    """One generation call. Only the conversation is sent; never reference_so or soap_note."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Generate a SOAP note using only this consultation.\n\n"
            "=== BEGIN CONSULTATION ===\n"
            f"{conversation}\n"
            "=== END CONSULTATION ==="
        )},
    ]
    if LLM_BACKEND == "openai":
        headers = {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}
        response = requests.post(
            LLM_BASE_URL.rstrip("/") + "/chat/completions", headers=headers, timeout=OLLAMA_TIMEOUT,
            json={"model": LLM_MODEL, "messages": messages, "temperature": TEMPERATURE,
                  "max_tokens": LLM_MAX_TOKENS},
        )
        response.raise_for_status()
        return (response.json()["choices"][0]["message"].get("content") or "").strip()
    response = requests.post(
        OLLAMA_URL, timeout=OLLAMA_TIMEOUT,
        json={"model": OLLAMA_MODEL, "messages": messages, "stream": False, "keep_alive": "10m",
              "options": {"temperature": TEMPERATURE, "num_ctx": OLLAMA_NUM_CTX}},
    )
    response.raise_for_status()
    return (response.json().get("message", {}).get("content") or "").strip()


def generate_with_ollama(conversation: str) -> str:
    """Name kept for compatibility; works with either backend."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        text = _request_note(conversation)
        if text:
            return text
        print(f"Attempt {attempt}/{MAX_ATTEMPTS}: empty response")
        if attempt < MAX_ATTEMPTS:
            time.sleep(attempt * 3)
    raise RuntimeError("The model returned an empty response after all retry attempts.")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def build_output_record(record: dict, generated: str, status: str, error, seconds: float) -> dict:
    """Stage 1 record: S/O is the input to Stage 2; A/P is preserved separately and untouched."""
    if generated:
        parsed = split_soap(generated)
    else:
        parsed = {"sections": {k: "" for k in SECTION_KEYS},
                  "missing": list(SECTION_KEYS), "parse_ok": False}
    sec = parsed["sections"]
    return {
        "case_id": record["case_id"],
        "split": record.get("split"),
        "status": status,
        "model": MODEL_NAME,
        "generation_seconds": round(seconds, 3),
        "conversation": record["conversation"],
        "generated_soap": generated,
        "stage1_so": {"subjective": sec["subjective"], "objective": sec["objective"]},
        "stage1_ap": {"assessment": sec["assessment"], "plan": sec["plan"]},
        "parse_ok": parsed["parse_ok"],
        "parse_missing_sections": parsed["missing"],
        "reference_so": record["reference_so"],  # evaluator-only
        "source_paths": record["source_paths"],
        "error": error,
    }


def load_checkpoint(case_id: str):
    path = CASES_DIR / f"{safe_name(case_id)}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def aggregate(records: list) -> None:
    result = {
        "stage": "stage1",
        "model": MODEL_NAME,
        "num_cases": len(records),
        "num_success": sum(x["status"] == "success" for x in records),
        "num_errors": sum(x["status"] == "error" for x in records),
        "num_parse_failures": sum(x["status"] == "success" and not x["parse_ok"] for x in records),
        "records": records,
    }
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSuccess: {result['num_success']}; errors: {result['num_errors']}; "
          f"parse failures: {result['num_parse_failures']}")
    print(f"JSON: {OUTPUT_JSON}")
    print(f"Markdown notes: {GENERATED_DIR}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="max number of cases to process")
    parser.add_argument("--retry-errors", action="store_true", help="redo cases that previously failed")
    parser.add_argument("--overwrite", action="store_true", help="regenerate even finished cases")
    args = parser.parse_args()

    if not PREPARED_JSON.exists():
        raise FileNotFoundError(f"{PREPARED_JSON} missing. Run prepare_dataset.py first.")
    records = json.loads(PREPARED_JSON.read_text(encoding="utf-8")).get("records", [])
    if args.split != "all":
        records = [r for r in records if r.get("split") == args.split]
    if args.limit:
        records = records[: args.limit]
    if not records:
        raise RuntimeError("No records selected.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    output_records = []

    try:
        for i, record in enumerate(records, 1):
            case_id = record["case_id"]
            saved = None if args.overwrite else load_checkpoint(case_id)
            if saved and (saved["status"] == "success" or not args.retry_errors):
                print(f"[{i}/{len(records)}] {case_id}: reusing saved ({saved['status']})")
                output_records.append(saved)
                continue

            print(f"[{i}/{len(records)}] {case_id}")
            start = time.time()
            try:
                generated = generate_with_ollama(record["conversation"])
                status, error = "success", None
                (GENERATED_DIR / f"{safe_name(case_id)}.md").write_text(
                    f"# Stage 1 generated SOAP - {case_id}\n\n{generated}\n", encoding="utf-8")
            except Exception as exc:
                generated, status = "", "error"
                error = f"{type(exc).__name__}: {exc}"
                print(f"[ERROR] {case_id}: {error}", file=sys.stderr)

            out = build_output_record(record, generated, status, error, time.time() - start)
            if status == "success" and not out["parse_ok"]:
                print(f"[WARN] {case_id}: missing sections {out['parse_missing_sections']}",
                      file=sys.stderr)
            (CASES_DIR / f"{safe_name(case_id)}.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            output_records.append(out)
    except KeyboardInterrupt:
        print("\nInterrupted; finished cases are saved. Re-run to resume.")
    finally:
        if output_records:
            aggregate(output_records)


if __name__ == "__main__":
    main()
