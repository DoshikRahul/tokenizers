"""
Full-SOAP evaluation of uMedSum: the project's evaluator (verify_and_ask_pipeline/Stage23_pipeline/code/evaluate.py),
extended from S/O to Subjective, Objective AND Assessment/Plan.

evaluate.py itself is not modified. This script loads its source, applies a few targeted changes, and runs it:
  * the note text used everywhere (ROUGE/BERTScore, fact extraction, fact recall) includes Assessment and Plan
  * grounding scores every sentence of S, O and A/P against the consultation
  * reference metrics are reported for the full note ("soap_"), Subjective ("subj_") and A/P ("ap_")
  * reference facts are extracted from the full reference SOAP note (S, O, A and P)

Records must come from run_umedsum_soap.py --scope soap (stage*_so and reference_so carry "assessment_and_plan").
Paths and settings come from the evaluator's config, so set RQ1_OUTPUT_DIR to the uMedSum output folder:
results go to <RQ1_OUTPUT_DIR>/evaluation/results_<split>.json/.md.

  RQ1_OUTPUT_DIR=<out> python evaluate_full_soap.py --eval-code <.../Stage23_pipeline/code> --stage23-json <file> --split all
"""
import argparse
import sys
import types
from pathlib import Path

SO_TO_TEXT_FULL = '''
def so_to_text(so: dict) -> str:
    """Full SOAP dict -> one text block (Subjective, Objective, Assessment and Plan)."""
    parts = []
    for key, title in (("subjective", "Subjective"), ("objective", "Objective"),
                       ("assessment_and_plan", "Assessment and Plan")):
        parts.append(f"{title}:\\n{(so.get(key) or '').strip()}")
    return "\\n\\n".join(parts).strip()
'''

PATCHES = [
    # full-note text everywhere so_to_text is used
    ("from common import read_json, so_to_text, write_json\n",
     "from common import read_json, write_json\n" + SO_TO_TEXT_FULL),
    # grounding: every section, A/P included
    ('for section in ("subjective", "objective"):', 'for section in ("subjective", "objective", "assessment_and_plan"):'),
    # reference metrics: full note, Subjective, A/P
    ('views = {"so_": (lambda x: so_to_text(x), "S/O"),',
     'views = {"soap_": (lambda x: so_to_text(x), "Full SOAP"),\n'
     '             "ap_": (lambda x: (x.get("assessment_and_plan") or "").strip(), "Assessment and Plan"),'),
    # facts from the whole reference note
    ('"Reference Subjective/Objective note:\\n{note}\\n\\n"',
     '"Reference SOAP note (Subjective, Objective, Assessment and Plan):\\n{note}\\n\\n"'),
    # markdown summary
    ('"Similarity to the ground-truth S/O (higher is better)"', '"Similarity to the ground-truth SOAP note (higher is better)"'),
    ('"so_rouge1_f", "so_rouge2_f", "so_rougeLsum_f", "so_bertscore_f1"]',
     '"soap_rouge1_f", "soap_rouge2_f", "soap_rougeLsum_f", "soap_bertscore_f1",\n'
     '          "ap_rouge1_f", "ap_rouge2_f", "ap_rougeLsum_f", "ap_bertscore_f1"]'),
    ('"Fact coverage vs the ground-truth S/O (higher is better)"', '"Fact coverage vs the ground-truth SOAP note (higher is better)"'),
    ('"A/P is not part of any score; S/O only."', '"Full SOAP: Subjective, Objective and Assessment/Plan are all scored."'),
    ('"Reference S/O used only for reference metrics and fact extraction."',
     '"Reference SOAP note (S, O, A/P) used only for reference metrics and fact extraction."'),
]


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--eval-code", required=True, help="path to verify_and_ask_pipeline/Stage23_pipeline/code")
    known, rest = ap.parse_known_args()
    code_dir = Path(known.eval_code).resolve()
    sys.path.insert(0, str(code_dir))

    src = (code_dir / "evaluate.py").read_text(encoding="utf-8")
    for old, new in PATCHES:
        if src.count(old) != 1:
            sys.exit(f"evaluate.py has changed; could not apply patch for: {old[:60]!r}")
        src = src.replace(old, new)

    mod = types.ModuleType("evaluate_full_soap_patched")
    mod.__file__ = str(code_dir / "evaluate.py")
    sys.argv = [sys.argv[0]] + rest
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    mod.main()


if __name__ == "__main__":
    main()
