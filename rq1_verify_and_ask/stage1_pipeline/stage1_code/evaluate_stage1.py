"""Evaluate generated Stage 1 S/O against ground-truth S/O only.

Install optional metrics:
  pip install rouge-score bert-score

The evaluator does not score Assessment or Plan. Empty/missing predicted sections
are reported as empty strings rather than silently using the full SOAP note.
"""
import json
import re
from pathlib import Path
from statistics import mean
from config import OUTPUT_JSON, OUTPUT_DIR
from soap_parse import extract_section


def safe_mean(values):
    return round(mean(values), 4) if values else None


def main():
    if not OUTPUT_JSON.exists():
        raise FileNotFoundError(f"{OUTPUT_JSON} not found. Run run_stage1.py first.")
    data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    rows = []
    for record in data["records"]:
        if record["status"] != "success":
            continue
        so = record.get("stage1_so")
        if so is not None:
            pred_s, pred_o = so.get("subjective", ""), so.get("objective", "")
        else:  # older output without the S/O split
            pred_s = extract_section(record["generated_soap"], "Subjective")
            pred_o = extract_section(record["generated_soap"], "Objective")
        ref = record.get("reference_so", {})
        rows.append({
            "case_id": record["case_id"],
            "predicted_subjective": pred_s,
            "reference_subjective": ref.get("subjective", ""),
            "predicted_objective": pred_o,
            "reference_objective": ref.get("objective", ""),
            "subjective_missing": not bool(pred_s),
            "objective_missing": not bool(pred_o),
        })

    if not rows:
        raise RuntimeError("No successful generated notes available to evaluate.")

    metrics = {}
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(
            ["rouge1", "rouge2", "rougeL", "rougeLsum"],
            use_stemmer=True,
        )
        for section in ("subjective", "objective"):
            for metric in ("rouge1", "rouge2", "rougeL", "rougeLsum"):
                values = []
                for row in rows:
                    score = scorer.score(
                        row[f"reference_{section}"],
                        row[f"predicted_{section}"],
                    )
                    values.append(score[metric].fmeasure)
                metrics[f"{section}_{metric}_f1"] = safe_mean(values)
    except ImportError:
        metrics["rouge"] = "Not computed; install with: pip install rouge-score"

    try:
        from bert_score import score as bert_score
        for section in ("subjective", "objective"):
            refs = [r[f"reference_{section}"] or " " for r in rows]
            preds = [r[f"predicted_{section}"] or " " for r in rows]
            precision, recall, f1 = bert_score(
                preds, refs, lang="en", verbose=False
            )
            metrics[f"{section}_bertscore_precision"] = round(precision.mean().item(), 4)
            metrics[f"{section}_bertscore_recall"] = round(recall.mean().item(), 4)
            metrics[f"{section}_bertscore_f1"] = round(f1.mean().item(), 4)
    except ImportError:
        metrics["bertscore"] = "Not computed; install with: pip install bert-score"
    except Exception as exc:
        metrics["bertscore_error"] = f"{type(exc).__name__}: {exc}"

    result = {
        "stage": "stage1",
        "evaluated_scope": ["Subjective", "Objective"],
        "num_successful_cases_evaluated": len(rows),
        "num_subjective_missing": sum(r["subjective_missing"] for r in rows),
        "num_objective_missing": sum(r["objective_missing"] for r in rows),
        "metrics": metrics,
        "per_case": rows,
        "note": (
            "Reference S/O was used only for evaluation. Automatic text metrics "
            "measure overlap/similarity, not clinical correctness or grounding."
        ),
    }
    out_path = OUTPUT_DIR / "evaluation_results.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "num_cases": result["num_successful_cases_evaluated"],
        "missing_subjective": result["num_subjective_missing"],
        "missing_objective": result["num_objective_missing"],
        "metrics": metrics,
        "saved_to": str(out_path),
    }, indent=2))


if __name__ == "__main__":
    main()
