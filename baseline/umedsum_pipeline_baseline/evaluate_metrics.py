"""
Comprehensive Benchmark Evaluation Script for uMedSum Clinical Summarization Pipeline.
Implements the evaluation metrics from Nagar et al., ACL 2025 (Section 4 & Table 1):

1. Reference-Based Metrics (vs Ground-Truth Doctor's Note 'tgt'):
   - ROUGE-1, ROUGE-2, ROUGE-L, ROUGE-Lsum (F1, Precision, Recall)
   - BERTScore (F1, Precision, Recall)

2. Reference-Free Metrics (vs Raw Dialogue 'src')            <-- NEW
   - SummaC (SummaC-Conv)        : sentence-level NLI consistency of summary vs source
   - QuestEval (w/o reference)   : QA-based consistency + informativeness vs source
   - Entailment                  : mean DeBERTa-v3 NLI entailment probability of each summary
                                   sentence w.r.t. the dialogue (same NLI model as Stage 2)

3. Descriptive stats: word count, compression ratio, Stage 2 confabulation rate, Stage 3 additions.

The final Stage 3 scores (all metrics above) are additionally written to a separate file:
    <dir of --output-json>/stage3_final_scores.json   (or --final-scores-json)
"""

import argparse
import json
import os
import re
import sys
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "stage_2"))  # for nli_scorer.DebertaNLIScorer

# ROUGE
try:
    from rouge_score import rouge_scorer
    HAS_ROUGE = True
except ImportError:
    HAS_ROUGE = False

# BERTScore
try:
    import bert_score
    HAS_BERTSCORE = True
except ImportError:
    HAS_BERTSCORE = False


def clean_text_for_rouge(text: str) -> str:
    """Strip extraneous blank lines and normalize whitespace."""
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def patch_questeval_for_new_transformers():
    """QuestEval passes decoder_start_token_id=None to generate(), which transformers>=5 rejects for T5.
    Fix it at runtime (no file edits): replace None by T5's start token id (0)."""
    try:
        import questeval.utils as qutils
    except Exception:
        return
    if not hasattr(qutils, "API_T2T") or getattr(qutils.API_T2T, "_umedsum_patched", False):
        return
    orig_init = qutils.API_T2T.__init__

    def new_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        try:
            self.model.generation_config.decoder_start_token_id = 0
        except Exception:
            pass
        orig_generate = self.model.generate

        def generate(*g_args, **g_kwargs):
            if "decoder_start_token_id" in g_kwargs and g_kwargs["decoder_start_token_id"] is None:
                g_kwargs["decoder_start_token_id"] = 0
            return orig_generate(*g_args, **g_kwargs)

        self.model.generate = generate

    qutils.API_T2T.__init__ = new_init
    qutils.API_T2T._umedsum_patched = True


# ======================================================================================
# Reference-free scorers (SummaC / QuestEval / Entailment)
# ======================================================================================
class ReferenceFreeScorers:
    """Lazily loads each metric once and reuses it across stages. A failing metric is reported, not fatal."""

    def __init__(self, device: str = "cpu", use_summac=True, use_questeval=True,
                 use_entailment=True, batch_size: int = 8, questeval_path: str = "/content/QuestEval"):
        self.device = device
        self.questeval_path = questeval_path
        self.use = {"summac_conv": use_summac, "questeval": use_questeval, "entailment": use_entailment}
        self.batch_size = batch_size
        self._summac = None
        self._questeval = None
        self._nli = None
        self._segmenter = None
        self.errors: Dict[str, str] = {}

    # ---------------- SummaC ----------------
    def _score_summac(self, sources: List[str], cands: List[str]) -> List[float]:
        if self._summac is None:
            from transformers import PreTrainedTokenizerBase
            if not hasattr(PreTrainedTokenizerBase, "batch_encode_plus"):
                def _bep(tok, batch, **kw):          # compat shim for transformers>=5
                    kw.pop("truncation_strategy", None)
                    if batch and isinstance(batch[0], (tuple, list)):
                        return tok([p[0] for p in batch], [p[1] for p in batch], **kw)
                    return tok(batch, **kw)
                PreTrainedTokenizerBase.batch_encode_plus = _bep
            from summac.model_summac import SummaCConv
            print("  Loading SummaC-Conv ...")
            self._summac = SummaCConv(
                models=["vitc"], bins="percentile", granularity="sentence",
                nli_labels="e", device=self.device, start_file="default", agg="mean"
            )
        scores = []
        for i in range(0, len(cands), self.batch_size):
            out = self._summac.score(sources[i:i + self.batch_size], cands[i:i + self.batch_size])
            scores.extend(float(s) for s in out["scores"])
            print(f"    SummaC {min(i + self.batch_size, len(cands))}/{len(cands)}", end="\r", flush=True)
        print()
        return scores

    # ---------------- QuestEval (reference-free) ----------------
    def _score_questeval(self, sources: List[str], cands: List[str]) -> List[float]:
        if self._questeval is None:
            if self.questeval_path and os.path.isdir(self.questeval_path) and self.questeval_path not in sys.path:
                sys.path.insert(0, self.questeval_path)
            try:
                from questeval.questeval_metric import QuestEval      # current GitHub repo
            except ImportError:
                from questeval.questeval_metrics import QuestEval     # older releases
            patch_questeval_for_new_transformers()
            print("  Loading QuestEval ...")
            self._questeval = QuestEval(no_cuda=(self.device != "cuda"))
        scores = []
        for i in range(0, len(cands), self.batch_size):
            out = self._questeval.corpus_questeval(
                hypothesis=cands[i:i + self.batch_size],
                sources=sources[i:i + self.batch_size]
            )
            scores.extend(float(s) for s in out["ex_level_scores"])
            print(f"    QuestEval {min(i + self.batch_size, len(cands))}/{len(cands)}", end="\r", flush=True)
        print()
        return scores

    # ---------------- Entailment (DeBERTa NLI) ----------------
    def _summary_sentences(self, text: str) -> List[str]:
        import pysbd
        if self._segmenter is None:
            self._segmenter = pysbd.Segmenter(language="en", clean=False)
        sents = []
        for line in text.splitlines():
            line = re.sub(r"^[-*+ \d.]+\s*", "", line.strip()).replace("**", "").replace("__", "").strip()
            if not line:
                continue
            if line.endswith(":") and len(line.split()) <= 5:  # section header such as "SUBJECTIVE:"
                continue
            for s in self._segmenter.segment(line):
                s = s.strip()
                if len(s.split()) >= 3:
                    sents.append(s)
        return sents or [text.strip()]

    def _score_entailment(self, sources: List[str], cands: List[str]) -> List[float]:
        import torch
        if self._nli is None:
            from nli_scorer import DebertaNLIScorer
            self._nli = DebertaNLIScorer(device=self.device)
        nli = self._nli
        use_amp = str(nli.device).startswith("cuda")
        scores = []
        for i, (src, cand) in enumerate(zip(sources, cands), 1):
            sents = self._summary_sentences(cand)
            chunks = nli.chunk_dialogue(src)
            pairs = [(c, s) for s in sents for c in chunks]          # sentence-major order
            ent_probs = []
            for j in range(0, len(pairs), 32):
                b = pairs[j:j + 32]
                enc = nli.tokenizer([p[0] for p in b], [p[1] for p in b], truncation=True,
                                    max_length=512, padding=True, return_tensors="pt").to(nli.device)
                with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                    logits = nli.model(**enc).logits
                ent_probs.append(torch.softmax(logits.float(), dim=-1)[:, nli.entail_idx].cpu())
            ent = torch.cat(ent_probs).view(len(sents), len(chunks)).max(dim=1).values  # best chunk per sentence
            scores.append(float(ent.mean()))
            print(f"    Entailment {i}/{len(cands)}", end="\r", flush=True)
        print()
        return scores

    # ---------------- driver ----------------
    def score_all(self, sources: List[str], cands: List[str]) -> Dict[str, Optional[List[float]]]:
        fns = {"summac_conv": self._score_summac, "questeval": self._score_questeval,
               "entailment": self._score_entailment}
        results: Dict[str, Optional[List[float]]] = {}
        for name, fn in fns.items():
            if not self.use[name] or name in self.errors:
                results[name] = None
                continue
            try:
                print(f"  Computing {name} ...")
                results[name] = fn(sources, cands)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self.errors[name] = msg
                print(f"  Warning: {name} failed -> {msg}")
                results[name] = None
        return results


# ======================================================================================
# Per-stage evaluation
# ======================================================================================
def evaluate_stage(
    samples: List[Dict[str, Any]],
    summary_key: str,
    compute_bertscore: bool = True,
    bertscore_model: str = "roberta-large",
    device: str = "cpu",
    rf_scorers: Optional[ReferenceFreeScorers] = None
) -> Dict[str, Any]:
    """
    Computes reference-based and reference-free metrics for a given summary field across all samples.
    """
    if not HAS_ROUGE:
        sys.exit("Error: rouge-score is not installed. Run `pip install rouge-score`.")

    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL", "rougeLsum"], use_stemmer=True)

    r1_list, r2_list, rl_list, rlsum_list = [], [], [], []
    r1_p_list, r2_p_list, rl_p_list = [], [], []
    r1_r_list, r2_r_list, rl_r_list = [], [], []
    summary_lens, ref_lens, comp_ratios = [], [], []

    candidates = []
    references = []
    sources = []
    per_sample_results = []

    for idx, item in enumerate(samples):
        cand = item.get(summary_key, "").strip()
        ref = item.get("tgt", "").strip()
        src = item.get("src", "").strip()

        if not cand:
            continue

        cand_clean = clean_text_for_rouge(cand)
        ref_clean = clean_text_for_rouge(ref)

        candidates.append(cand)
        references.append(ref)
        sources.append(src)

        # ROUGE
        scores = scorer.score(ref_clean, cand_clean)
        r1_list.append(scores["rouge1"].fmeasure)
        r2_list.append(scores["rouge2"].fmeasure)
        rl_list.append(scores["rougeL"].fmeasure)
        rlsum_list.append(scores["rougeLsum"].fmeasure)

        r1_p_list.append(scores["rouge1"].precision)
        r2_p_list.append(scores["rouge2"].precision)
        rl_p_list.append(scores["rougeL"].precision)

        r1_r_list.append(scores["rouge1"].recall)
        r2_r_list.append(scores["rouge2"].recall)
        rl_r_list.append(scores["rougeL"].recall)

        # Lengths & Compression
        cand_words = len(cand.split())
        ref_words = len(ref.split()) if ref else 0
        src_words = len(src.split()) if src else 0

        summary_lens.append(cand_words)
        ref_lens.append(ref_words)
        comp_ratio = cand_words / src_words if src_words > 0 else 0.0
        comp_ratios.append(comp_ratio)

        sample_rec = {
            "encounter_id": item.get("encounter_id") or item.get("file", f"sample_{idx}"),
            "summary_length": cand_words,
            "reference_length": ref_words,
            "compression_ratio": round(comp_ratio, 4),
            "rouge1_f": round(scores["rouge1"].fmeasure, 4),
            "rouge2_f": round(scores["rouge2"].fmeasure, 4),
            "rougeL_f": round(scores["rougeL"].fmeasure, 4),
            "rougeLsum_f": round(scores["rougeLsum"].fmeasure, 4),
        }
        per_sample_results.append(sample_rec)

    if not candidates:
        return {}

    # Aggregate ROUGE
    summary_metrics = {
        "num_evaluated": len(candidates),
        "rouge1": {
            "f": float(np.mean(r1_list)),
            "p": float(np.mean(r1_p_list)),
            "r": float(np.mean(r1_r_list)),
        },
        "rouge2": {
            "f": float(np.mean(r2_list)),
            "p": float(np.mean(r2_p_list)),
            "r": float(np.mean(r2_r_list)),
        },
        "rougeL": {
            "f": float(np.mean(rl_list)),
            "p": float(np.mean(rl_p_list)),
            "r": float(np.mean(rl_r_list)),
        },
        "rougeLsum": {
            "f": float(np.mean(rlsum_list)),
        },
        "avg_summary_len": float(np.mean(summary_lens)),
        "avg_reference_len": float(np.mean(ref_lens)),
        "avg_compression_ratio": float(np.mean(comp_ratios)),
    }

    # BERTScore
    if compute_bertscore and HAS_BERTSCORE and candidates and references:
        print(f"  Calculating BERTScore using '{bertscore_model}' on {device}...")
        try:
            P, R, F1 = bert_score.score(
                candidates,
                references,
                model_type=bertscore_model,
                device=device,
                batch_size=16,
                verbose=False
            )
            summary_metrics["bertscore"] = {
                "f1": float(F1.mean().item()),
                "precision": float(P.mean().item()),
                "recall": float(R.mean().item())
            }
            for i, rec in enumerate(per_sample_results):
                rec["bertscore_f1"] = round(F1[i].item(), 4)
        except Exception as e:
            print(f"  Warning: BERTScore computation encountered an error: {e}")
            summary_metrics["bertscore"] = {"f1": None, "precision": None, "recall": None}

    # Reference-free metrics (SummaC / QuestEval / Entailment) vs the source dialogue
    if rf_scorers is not None:
        rf_results = rf_scorers.score_all(sources, candidates)
        for name, vals in rf_results.items():
            if vals is None:
                summary_metrics[name] = {"score": None, "error": rf_scorers.errors.get(name)}
                continue
            summary_metrics[name] = {"score": float(np.mean(vals)), "std": float(np.std(vals))}
            for rec, v in zip(per_sample_results, vals):
                rec[name] = round(float(v), 4)

    # Pipeline Specific Audit Stats
    if summary_key in ["stage2_summary", "stage3_summary"]:
        faith_counts = [len(item.get("stage2_faithful_units", [])) for item in samples if "stage2_faithful_units" in item]
        confab_counts = [len(item.get("stage2_confabulated_units", [])) for item in samples if "stage2_confabulated_units" in item]
        if faith_counts:
            total_units = np.array(faith_counts) + np.array(confab_counts)
            valid_mask = total_units > 0
            if np.any(valid_mask):
                confab_rate = float(np.mean(np.array(confab_counts)[valid_mask] / total_units[valid_mask]))
                summary_metrics["stage2_confabulation_rate"] = confab_rate
            summary_metrics["stage2_avg_faithful_units"] = float(np.mean(faith_counts))
            summary_metrics["stage2_avg_purged_confabs"] = float(np.mean(confab_counts))

    if summary_key == "stage3_summary":
        added_counts = [len(item.get("stage3_missing_sentences_added", [])) for item in samples if "stage3_missing_sentences_added" in item]
        if added_counts:
            summary_metrics["stage3_avg_missing_added"] = float(np.mean(added_counts))

    return {
        "aggregate": summary_metrics,
        "per_sample": per_sample_results
    }


def _fmt(val, nd=4):
    return f"{val:.{nd}f}" if isinstance(val, (int, float)) else "N/A"


def print_comparison_table(results_by_stage: Dict[str, Dict[str, Any]]):
    """
    Renders an ASCII table comparing stages against each other and the paper's benchmark numbers.
    """
    header = (
        f"{'Pipeline Stage':<22} | {'R-1':<7} | {'R-2':<7} | {'R-L':<7} | {'R-Lsum':<7} | "
        f"{'BERTScore':<9} | {'S-C':<7} | {'QE':<7} | {'Ent.':<7} | {'Words':<6} | {'Comp.':<6}"
    )
    separator = "-" * len(header)

    print("\n" + "=" * len(header))
    print("                    uMedSum BENCHMARK EVALUATION RESULTS")
    print("=" * len(header))
    print(header)
    print(separator)

    display_names = {
        "stage1_summary": "Stage 1 (Initial ICL)",
        "stage2_summary": "Stage 2 (Purged RTB-TS)",
        "stage3_summary": "Stage 3 (Final uMedSum)"
    }

    for key, data in results_by_stage.items():
        name = display_names.get(key, key)
        agg = data.get("aggregate", {})
        r1 = _fmt(agg.get('rouge1', {}).get('f')) if agg.get('rouge1') else "N/A"
        r2 = _fmt(agg.get('rouge2', {}).get('f')) if agg.get('rouge2') else "N/A"
        rl = _fmt(agg.get('rougeL', {}).get('f')) if agg.get('rougeL') else "N/A"
        rlsum = _fmt(agg.get('rougeLsum', {}).get('f')) if agg.get('rougeLsum') else "N/A"
        bs = _fmt(agg.get('bertscore', {}).get('f1'))
        sc = _fmt(agg.get('summac_conv', {}).get('score'))
        qe = _fmt(agg.get('questeval', {}).get('score'))
        ent = _fmt(agg.get('entailment', {}).get('score'))
        words = f"{agg.get('avg_summary_len', 0):.1f}"
        comp = f"{agg.get('avg_compression_ratio', 0):.3f}"

        print(f"{name:<22} | {r1:<7} | {r2:<7} | {rl:<7} | {rlsum:<7} | {bs:<9} | {sc:<7} | {qe:<7} | {ent:<7} | {words:<6} | {comp:<6}")

    print(separator)
    print(f"{'Paper SOTA (Table 1)':<22} | {'~0.44':<7} | {'~0.22':<7} | {'~0.40':<7} | {'~0.42':<7} | {'~0.86':<9} | {'-':<7} | {'-':<7} | {'-':<7} | {'~140':<6} | {'~0.09':<6}")
    print("=" * len(header) + "\n")


def save_stage3_final_scores(stage3: Dict[str, Any], source_file: Path, total_samples: int, out_path: Path):
    """Writes the final (Stage 3) scores for every metric into its own JSON file."""
    agg = stage3.get("aggregate", {})
    final_metrics = {
        "rouge1_f": agg.get("rouge1", {}).get("f"),
        "rouge2_f": agg.get("rouge2", {}).get("f"),
        "rougeL_f": agg.get("rougeL", {}).get("f"),
        "rougeLsum_f": agg.get("rougeLsum", {}).get("f"),
        "bertscore_f1": agg.get("bertscore", {}).get("f1"),
        "summac_conv": agg.get("summac_conv", {}).get("score"),
        "questeval": agg.get("questeval", {}).get("score"),
        "entailment": agg.get("entailment", {}).get("score"),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_file": str(source_file),
            "summary_field": "stage3_summary",
            "total_samples": total_samples,
            "num_evaluated": agg.get("num_evaluated"),
            "final_scores": final_metrics,
            "reference_free_errors": {k: v.get("error") for k, v in agg.items()
                                      if isinstance(v, dict) and v.get("error")},
            "full_aggregate": agg,
            "per_sample": stage3.get("per_sample", []),
        }, f, indent=2, ensure_ascii=False)
    print(f"Final Stage 3 scores saved to: {out_path}\n")


def main():
    parser = argparse.ArgumentParser(description="uMedSum Comprehensive Benchmark Evaluation")
    parser.add_argument("--input-json", type=str, required=True, help="Input JSON file containing pipeline outputs")
    parser.add_argument("--output-json", type=str, default=None, help="Optional output JSON to save detailed metric scores")
    parser.add_argument("--final-scores-json", type=str, default=None,
                        help="Where to save the Stage 3 final scores (default: stage3_final_scores.json next to --output-json, or results/)")
    parser.add_argument("--stages", nargs="+", default=["auto"], help="Summary fields to evaluate (e.g. stage1_summary stage2_summary stage3_summary)")
    parser.add_argument("--skip-bertscore", action="store_true", help="Skip BERTScore calculation (runs fast ROUGE only)")
    parser.add_argument("--bertscore-model", type=str, default="roberta-large", help="Model checkpoint for BERTScore (default: roberta-large)")
    parser.add_argument("--skip-reference-free", action="store_true", help="Skip SummaC, QuestEval and Entailment")
    parser.add_argument("--skip-summac", action="store_true", help="Skip SummaC")
    parser.add_argument("--skip-questeval", action="store_true", help="Skip QuestEval")
    parser.add_argument("--skip-entailment", action="store_true", help="Skip Entailment (DeBERTa NLI)")
    parser.add_argument("--rf-stages", nargs="+", default=["all"],
                        help="Stages to run SummaC/QuestEval/Entailment on (default: all stages; e.g. --rf-stages stage3_summary)")
    parser.add_argument("--questeval-path", type=str, default="/content/QuestEval",
                        help="Path of the cloned QuestEval repo (used if present)")
    parser.add_argument("--rf-batch-size", type=int, default=8, help="Batch size for SummaC / QuestEval")
    parser.add_argument("--device", type=str, default=None, help="Device for model-based metrics ('cuda' or 'cpu')")
    args = parser.parse_args()

    input_path = Path(args.input_json)
    if not input_path.exists():
        sys.exit(f"Error: Input JSON not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    samples = data.get("data", []) if isinstance(data, dict) else data
    if not samples:
        sys.exit(f"Error: No samples found in {input_path}")

    # Determine stages to evaluate
    first_sample = samples[0]
    candidate_stages = []
    if "auto" in args.stages:
        for s in ["stage1_summary", "stage2_summary", "stage3_summary"]:
            if s in first_sample and first_sample[s]:
                candidate_stages.append(s)
    else:
        candidate_stages = args.stages

    if not candidate_stages:
        sys.exit("Error: No valid summary fields found to evaluate.")

    import torch
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    rf_scorers = None
    if not args.skip_reference_free:
        rf_scorers = ReferenceFreeScorers(
            device=device,
            use_summac=not args.skip_summac,
            use_questeval=not args.skip_questeval,
            use_entailment=not args.skip_entailment,
            batch_size=args.rf_batch_size,
            questeval_path=args.questeval_path,
        )

    print(f"\n--- Running Evaluation on {len(samples)} samples ---")
    print(f"  Input File: {input_path.name}")
    print(f"  Stages to Evaluate: {candidate_stages}")
    print(f"  BERTScore: {'Disabled' if args.skip_bertscore else f'Enabled ({args.bertscore_model})'}")
    print(f"  Reference-free (SummaC/QuestEval/Entailment): {'Disabled' if rf_scorers is None else 'Enabled on ' + ', '.join(args.rf_stages)}")
    print(f"  Device: {device}\n")

    results_by_stage = {}
    for stage_key in candidate_stages:
        print(f"Evaluating {stage_key}...")
        results = evaluate_stage(
            samples=samples,
            summary_key=stage_key,
            compute_bertscore=not args.skip_bertscore,
            bertscore_model=args.bertscore_model,
            device=device,
            rf_scorers=rf_scorers if ("all" in args.rf_stages or stage_key in args.rf_stages) else None
        )
        results_by_stage[stage_key] = results

    # Print publication-grade comparison table
    print_comparison_table(results_by_stage)

    # Save detailed JSON if requested
    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "source_file": str(input_path),
                "total_samples": len(samples),
                "stages": results_by_stage
            }, f, indent=2, ensure_ascii=False)
        print(f"Detailed metric scores saved to: {out_path}\n")

    # Separate file with the final (Stage 3) scores
    if "stage3_summary" in results_by_stage and results_by_stage["stage3_summary"]:
        if args.final_scores_json:
            final_path = Path(args.final_scores_json)
        elif args.output_json:
            final_path = Path(args.output_json).parent / "stage3_final_scores.json"
        else:
            final_path = BASE_DIR / "results" / "stage3_final_scores.json"
        save_stage3_final_scores(results_by_stage["stage3_summary"], input_path, len(samples), final_path)


if __name__ == "__main__":
    main()