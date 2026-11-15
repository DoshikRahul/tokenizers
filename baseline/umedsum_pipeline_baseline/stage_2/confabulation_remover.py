"""
Recursive Threshold-Based Text Segmentation & Confabulation Removal (RTB-TS).
Implements the exact logic and thresholds from Nagar et al., ACL 2025 (Section 3.2 & Appendix A.7):
- Sentence Boundary Segmentation: PySBD
- Entailment Threshold (Te): 0.9
- Confabulation Threshold (Tc): 0.8
- Atomic Fact Threshold (Ta): 0.5

Enhanced with:
- Section-Aware classification (Subjective vs Objective vs Assessment & Plan)
- Exact dialogue citations for verified claims
- Diagnostic reasoning analysis for discarded clinical inferences

CHANGE (requirement 2): the "uncertain" branch now performs true recursive decomposition
(paper Sec. 3.2 "Recursive Decomposition"): an uncertain DSU is split into atomic facts, each atom is
re-scored, atoms with E > Ta are retained, atoms that are still ambiguous are decomposed again
(up to `max_depth`), and the rest are discarded. Everything else is unchanged.
"""

import re
import pysbd
from typing import Dict, List, Any, Tuple
from nli_scorer import DebertaNLIScorer
from atomic_decomposer import AtomicDecomposer

# Paper Appendix A.7 thresholds
DEFAULT_TE = 0.9  # Entailment threshold (E > Te -> Faithful)
DEFAULT_TC = 0.8  # Confabulation threshold (N + C > Tc -> Confabulated)
DEFAULT_TA = 0.5  # Atomic Fact threshold (E > Ta -> Keep)
DEFAULT_MAX_DEPTH = 2  # max recursion levels of atomic decomposition


def detect_clinical_section(unit: str, current_section: str = "SUBJECTIVE") -> str:
    """Classifies unit into Subjective, Objective, or Assessment & Plan based on headers and keywords."""
    unit_lower = unit.lower()

    if re.search(r"\b(assessment|plan|impression|diagnosis|diagnoses|recommend|prescribe|follow-up|follow up|treatment)\b", unit_lower):
        return "ASSESSMENT_AND_PLAN"
    elif re.search(r"\b(exam|examination|vitals|blood pressure|temperature|lungs|heart|abdomen|edema|rhonchi|wheezing|imaging|labs|x-ray|a1c|panel|normal|unremarkable)\b", unit_lower):
        return "OBJECTIVE"
    elif re.search(r"\b(reports|complains|presents|history|hpi|chief complaint|states|denies|fatigue|fever|cough|pain|aches|duration|days|weeks|months|allergies)\b", unit_lower):
        return "SUBJECTIVE"

    return current_section


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


class ConfabulationRemover:
    def __init__(
        self,
        nli_scorer: DebertaNLIScorer,
        decomposer: AtomicDecomposer,
        te: float = DEFAULT_TE,
        tc: float = DEFAULT_TC,
        ta: float = DEFAULT_TA,
        max_depth: int = DEFAULT_MAX_DEPTH
    ):
        self.nli_scorer = nli_scorer
        self.decomposer = decomposer
        self.te = te
        self.tc = tc
        self.ta = ta
        self.max_depth = max_depth
        self.segmenter = pysbd.Segmenter(language="en", clean=False)

    def clean_summary_text(self, text: str) -> List[Dict[str, str]]:
        """
        Strips chat preambles/disclaimers, tracks SOAP section context, and splits into units.
        """
        lines = text.splitlines()
        current_section = "SUBJECTIVE"
        units_with_section = []

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Update section context if line is a header
            clean_hdr = line_str.replace("*", "").replace(":", "").strip().upper()
            if "SUBJECTIVE" in clean_hdr or "HISTORY OF PRESENT ILLNESS" in clean_hdr or "CHIEF COMPLAINT" in clean_hdr:
                current_section = "SUBJECTIVE"
                continue
            elif "OBJECTIVE" in clean_hdr or "PHYSICAL EXAMINATION" in clean_hdr or "EXAM" in clean_hdr:
                current_section = "OBJECTIVE"
                continue
            elif "ASSESSMENT" in clean_hdr or "PLAN" in clean_hdr:
                current_section = "ASSESSMENT_AND_PLAN"
                continue

            # Skip chat conversational preambles
            if re.match(r"^(here is|here's|below is|this is the|soap note:?)", line_str, re.IGNORECASE):
                continue
            # Skip chat disclaimer postambles
            if re.match(r"^(please note|note:|disclaimer:)", line_str, re.IGNORECASE):
                continue

            # Strip leading bullet points or numbers
            cleaned_line = re.sub(r"^[-*+ \d.]+\s*", "", line_str).strip()
            cleaned_line = cleaned_line.replace("**", "").replace("__", "").strip()

            if len(cleaned_line.split()) >= 3:
                # Segment line into individual sentences
                segmented = self.segmenter.segment(cleaned_line)
                for seg in segmented:
                    seg_clean = seg.strip()
                    if len(seg_clean.split()) >= 3:
                        section = detect_clinical_section(seg_clean, current_section)
                        units_with_section.append({
                            "unit": seg_clean,
                            "section": section
                        })

        return units_with_section

    # ------------------------------------------------------------------ recursive decomposition
    def _recursive_decompose(
        self,
        dialogue: str,
        unit: str,
        depth: int,
        parent_entail: float,
        stats: Dict[str, int]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
        """
        Paper Sec. 3.2 'Recursive Decomposition'.
        Splits `unit` into atomic facts, re-scores each with the NLI model, keeps atoms with E > Ta,
        and re-decomposes atoms that are still ambiguous (Ta >= E and N+C <= Tc) until max_depth.
        Returns (retained_atoms, discarded_atoms, deepest_level_reached).
        """
        atoms, method = self.decomposer.decompose_with_info(unit)
        stats["decompose_calls"] += 1
        stats[f"method_{method}"] = stats.get(f"method_{method}", 0) + 1

        # Nothing new produced below the first level -> this atom cannot be refined further
        unchanged = len(atoms) == 1 and _norm(atoms[0]) == _norm(unit)
        if depth > 0 and unchanged:
            return [], [{
                "atom": unit,
                "reasoning": "Could not be decomposed further and not entailed above threshold Ta.",
                "entailment": round(parent_entail, 4),
                "depth": depth
            }], depth

        retained, discarded, deepest = [], [], depth
        for atom in atoms:
            sc = self.nli_scorer.score_hypothesis(dialogue, atom)
            e, n, c = sc.get("entailment", 0.0), sc.get("neutral", 0.0), sc.get("contradiction", 0.0)

            if e > self.ta:
                retained.append({
                    "atom": atom,
                    "citation": sc.get("best_citation", ""),
                    "entailment": round(e, 4),
                    "depth": depth + 1
                })
            elif (n + c) <= self.tc and depth + 1 < self.max_depth and len(atom.split()) > 4:
                # Still in the "uncertain" band -> recurse one level deeper
                sub_ret, sub_dis, sub_deep = self._recursive_decompose(
                    dialogue, atom, depth + 1, e, stats
                )
                retained.extend(sub_ret)
                discarded.extend(sub_dis)
                deepest = max(deepest, sub_deep)
            else:
                discarded.append({
                    "atom": atom,
                    "reasoning": "Sub-proposition not entailed above threshold Ta (%.2f)." % self.ta,
                    "entailment": round(e, 4),
                    "depth": depth + 1
                })
            deepest = max(deepest, depth + 1)

        return retained, discarded, deepest

    def process_summary(self, dialogue: str, stage1_summary: str) -> Dict[str, Any]:
        """
        Executes RTB-TS confabulation detection, extracts dialogue citations,
        and logs diagnostic reasoning for discarded inferences.
        """
        parsed_units = self.clean_summary_text(stage1_summary)

        faithful_units = []
        confabulated_units = []
        uncertain_units = []
        decision_details = []
        decomposition_stats: Dict[str, int] = {"uncertain_units": 0, "decompose_calls": 0}

        # Tracking for Section-Aware Analysis (RQ2)
        section_stats = {
            "SUBJECTIVE": {"total": 0, "faithful": 0, "discarded": 0},
            "OBJECTIVE": {"total": 0, "faithful": 0, "discarded": 0},
            "ASSESSMENT_AND_PLAN": {"total": 0, "faithful": 0, "discarded": 0}
        }

        for item in parsed_units:
            dsu = item["unit"]
            section = item["section"]
            section_stats[section]["total"] += 1

            scores = self.nli_scorer.score_hypothesis(dialogue, dsu)
            e_score = scores.get("entailment", 0.0)
            n_score = scores.get("neutral", 0.0)
            c_score = scores.get("contradiction", 0.0)
            confab_score = n_score + c_score
            best_citation = scores.get("best_citation", "")

            record = {
                "unit": dsu,
                "section": section,
                "scores": {
                    "entailment": round(e_score, 4),
                    "neutral": round(n_score, 4),
                    "contradiction": round(c_score, 4)
                }
            }

            if e_score > self.te:
                record["classification"] = "faithful"
                record["citation_source"] = "src (dialogue)"
                record["citation_text"] = best_citation
                record["reasoning"] = "Verified: claim is directly entailed by doctor/patient statements in the dialogue."
                faithful_units.append(dsu)
                section_stats[section]["faithful"] += 1

            elif confab_score > self.tc:
                record["classification"] = "confabulated"
                record["citation_source"] = "None (not explicitly in dialogue)"
                record["citation_text"] = "No supporting dialogue turn found."

                # Clinical reasoning explanation for why the LLM produced it
                if section == "ASSESSMENT_AND_PLAN":
                    record["reasoning"] = (
                        "Clinical Inference Purged: The LLM formulated a diagnostic conclusion or treatment recommendation "
                        "deduced from patient symptoms and vitals. However, because the doctor did not explicitly utter this "
                        "diagnostic label verbatim during the dialogue, uMedSum's uniform entailment check classified it as unsupported "
                        "and discarded it (Fact-Inference Category Error)."
                    )
                else:
                    record["reasoning"] = (
                        "Factual Hallucination Purged: Statement introduces an ungrounded symptom, physical exam finding, or detail "
                        "that was not stated by the patient or doctor in the dialogue transcript."
                    )

                confabulated_units.append(dsu)
                section_stats[section]["discarded"] += 1

            else:
                # ---- Uncertain: recursive atomic decomposition (paper Sec. 3.2) ----
                record["classification"] = "uncertain"
                record["citation_source"] = "Partial / Ambiguous dialogue grounding"
                record["citation_text"] = best_citation
                uncertain_units.append(dsu)
                decomposition_stats["uncertain_units"] += 1

                retained_atoms, discarded_atoms, deepest = self._recursive_decompose(
                    dialogue, dsu, depth=0, parent_entail=e_score, stats=decomposition_stats
                )

                for ra in retained_atoms:
                    faithful_units.append(ra["atom"])
                    section_stats[section]["faithful"] += 1
                section_stats[section]["discarded"] += len(discarded_atoms)

                record["atomic_decomposition"] = {
                    "original": dsu,
                    "retained": retained_atoms,
                    "discarded": discarded_atoms,
                    "decomposition_method": self.decomposer.last_method,
                    "max_depth_reached": deepest
                }

            decision_details.append(record)

        # Aggregate refined summary
        refined_summary = " ".join(faithful_units).strip()

        return {
            "stage2_summary": refined_summary,
            "faithful_units": faithful_units,
            "confabulated_units": confabulated_units,
            "uncertain_units": uncertain_units,
            "section_breakdown": section_stats,
            "decomposition_stats": decomposition_stats,
            "details": decision_details
        }