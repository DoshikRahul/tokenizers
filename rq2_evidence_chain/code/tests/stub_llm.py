"""Fake generator LLM for the offline smoke test (GEN_BACKEND=stub). Produces structurally valid JSON."""
import json
import re


def _turns(user):
    return re.findall(r"\[(T\d+)\] (Doctor|Patient): (.*)", user)


def respond(system, user):
    if "construct evaluation data" in system:
        return json.dumps({
            "unsupported_diagnosis": {"problem": "", "claim": "Findings are consistent with early rheumatoid arthritis."},
            "plan_without_evidence": {"problem": "", "claim": "We will order a brain MRI with contrast."},
            "contradicted_inference": {"problem": "", "section": "Assessment",
                                       "claim": "The patient is allergic to all antibiotics.", "contradicting_turn": "T2"}})
    if "edit clinical encounter transcripts" in system:
        cues = re.compile(r"(prescrib|order|i want to|follow-?up|refer|recommend|increase|continue)", re.I)
        edits = [{"tid": t, "action": "remove"} for t, spk, txt in _turns(user) if spk == "Doctor" and cues.search(txt)]
        return json.dumps({"edits": edits})
    if "extract patient-specific clinical features" in system:
        feats = [{"text": txt[:160], "category": "symptom", "turns": [t]}
                 for t, spk, txt in _turns(user) if spk == "Patient" and len(txt.split()) > 6][:25]
        return json.dumps({"features": feats})
    if "split clinical Assessment/Plan" in system:
        claim = re.search(r"Statement: (.*)", user).group(1)
        parts = [p.strip() for p in re.split(r",? and |; ", claim) if len(p.split()) > 2]
        return json.dumps({"components": parts or [claim]})
    if "link clinical note statements" in system:
        claim = re.search(r"statement: (.*)", user).group(1).lower()
        w = set(re.findall(r"[a-z]{5,}", claim))
        feats = re.findall(r"\[(F\d+)\] (.*)", user)
        ranked = sorted(feats, key=lambda f: -len(w & set(re.findall(r"[a-z]{5,}", f[1].lower()))))
        return json.dumps({"feature_ids": [f[0] for f in ranked[:3]]})
    # uMedSum atomic decomposition prompt
    st = re.findall(r"Statement: (.*)", user)[-1]
    return "\n".join(f"- {p.strip()}" for p in re.split(r",| and ", st) if p.strip())
