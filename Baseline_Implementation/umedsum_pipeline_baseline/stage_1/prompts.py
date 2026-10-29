"""
Prompts for Stage 1 (Initial Summary Generation) on ACI-BENCH.
Dedicated to the Paper SOTA:
Element-Aware Summarization with In-Context Learning (Wang et al., 2023 / Nagar et al., ACL 2025).

Updated for Full SOAP Note Generation (Subjective, Objective, Assessment and Plan).
"""

ELEMENT_AWARE_SYSTEM_PROMPT = (
    "You are an expert clinical documentation assistant. "
    "Your task is to accurately summarize doctor-patient clinical conversations "
    "into a professional, clinically faithful, and complete SOAP Note (Subjective, Objective, Assessment and Plan)."
)

ELEMENT_AWARE_STEP1_PROMPT = (
    "You are an expert clinical assistant. Read the following doctor-patient dialogue carefully.\n"
    "Identify and extract the following essential clinical elements in concise bullet points:\n"
    "1. Subjective Elements: Chief complaints, history of present illness (symptoms, onset, duration), and relevant medical history/medications.\n"
    "2. Objective Elements: Physical examination findings, vital signs mentioned, and diagnostic lab/imaging results.\n"
    "3. Assessment Elements: Diagnoses and clinical impressions made by the doctor.\n"
    "4. Plan Elements: Medical treatment plan, prescriptions/dosages, tests ordered, and follow-up instructions.\n\n"
    "Dialogue:\n{dialogue}\n\n"
    "Extracted Clinical Elements:"
)

ELEMENT_AWARE_STEP2_PROMPT = (
    "You are an expert clinical assistant. Based on the doctor-patient dialogue and the extracted clinical elements below, "
    "generate a complete, comprehensive, and faithful clinical SOAP visit note.\n\n"
    "Dialogue:\n{dialogue}\n\n"
    "Extracted Clinical Elements:\n{elements}\n\n"
    "Instructions: Structure the note using standard clinical headings:\n"
    "SUBJECTIVE:\n"
    "- Chief Complaint\n"
    "- History of Present Illness (HPI)\n\n"
    "OBJECTIVE:\n"
    "- Physical Examination & Vitals\n"
    "- Diagnostic Results & Labs\n\n"
    "ASSESSMENT AND PLAN:\n"
    "- Diagnoses and Clinical Reasoning\n"
    "- Treatment Plan, Medications, and Follow-up\n\n"
    "SOAP NOTE:"
)

def format_icl_demonstrations(icl_samples: list, n_shots: int = 1) -> str:
    """Format in-context learning demonstrations from held-out train examples with full SOAP notes."""
    if not icl_samples or n_shots <= 0:
        return ""
    
    demos = []
    for idx, sample in enumerate(icl_samples[:n_shots], 1):
        src = sample.get("src", "").strip()
        tgt = sample.get("tgt_full") or sample.get("tgt", "").strip()
        demo_str = (
            f"--- Reference Example {idx} ---\n"
            f"Dialogue:\n{src}\n\n"
            f"Full SOAP Note:\n{tgt}\n"
        )
        demos.append(demo_str)
    
    return "\nHere are reference examples of complete clinical SOAP note generation:\n\n" + "\n".join(demos) + "\n--- End of Examples ---\n\n"
