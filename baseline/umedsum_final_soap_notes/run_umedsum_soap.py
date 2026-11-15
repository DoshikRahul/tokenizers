"""
uMedSum (Nagar et al., ACL 2025) on the 110 simulated consultations, matched to the RQ1 setup.

This is baseline B3 from the proposal ("Aegle intake -> note -> uMedSum filter"), run end to end:

  Stage 1  Element-Aware + 1-shot ICL full-SOAP generation (LLaMA-3-8B)   <- same prompts as the baseline
           -> split into S/O and A/P. A/P is kept aside and never changed.
  Stage 2  RTB-TS confabulation removal (DeBERTa-v3-large NLI, Te=0.9, Tc=0.8, Ta=0.5)   on S/O only
  Stage 3  MMR key sentences + KeyBERT coverage (cov_min=0.4, top_m=2) + GPT-2 perplexity insertion   on S/O only
  Final    Stage 3 S/O + the untouched Stage 1 A/P

Input is the same prepared dataset Verify-and-Ask uses (built from agentic-pipeline-output/soap_notes
by verify_and_ask_pipeline/stage1_pipeline/stage1_code/prepare_dataset.py, seed 42; pass it with --dataset). Only the consultation is given to the models; the agentic soap_note.md S/O is
carried in each record solely for evaluation.

Output records use the Verify-and-Ask record format (stage1_so / stage2_so / stage3_so, stage1_ap,
ap_unchanged, stage3_added, ...), so verify_and_ask_pipeline/Stage23_pipeline/code/evaluate.py scores
both systems with exactly the same code. Systems A/B/C in that evaluation = uMedSum Stage 1/2/3.

The Stage 1/2/3 algorithms are imported unchanged from Baseline_Implementation/umedsum_pipeline_baseline.
The only adaptation is section handling (S/O vs A/P), plus an optional fix to the baseline's header
detection (see FixedHeaderRemover), on by default.

  python run_umedsum_soap.py --limit 2            # smoke test
  python run_umedsum_soap.py                      # all 110 cases (resumes per case)
  python run_umedsum_soap.py --split test         # only the 88 test cases
"""
import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent  # .../tokenizers
BASELINE = REPO / "baseline" / "umedsum_pipeline_baseline"
for sub in ("stage_1", "stage_2", "stage_3"):
    sys.path.insert(0, str(BASELINE / sub))

DEFAULT_DATASET = REPO / "rq1_verify_and_ask" / "stage1_pipeline" / "stage1_output" / "prepared_dataset.json"
DEFAULT_ICL = REPO / "baseline" / "aci_dataset_rq1_baseline" / "icl_examples.json"
DEFAULT_OUT = HERE / "output"


# ---------------------------------------------------------------------------------------------
# Section handling
# ---------------------------------------------------------------------------------------------
_MAIN_HEADING = re.compile(
    r"^(?P<name>subjective|objective|assessment\s*(?:and|&|/)\s*plan|assessment|plan|a\s*/\s*p)\b"
    r"(?:\s*\([^)]*\))?\s*(?P<colon>:)?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
# Used only if the model wrote no SUBJECTIVE / OBJECTIVE / ASSESSMENT headings at all.
_FALLBACK_SUBHEADINGS = [
    ("subjective", r"chief complaint|history of present illness|hpi|review of systems|past medical history|"
                   r"medications?|allergies|social history|family history|cc"),
    ("objective", r"physical exam(?:ination)?|exam(?:ination)?|vitals?|vital signs|diagnostic|results?|labs?|"
                  r"imaging|investigations?"),
    ("ap", r"diagnos[ie]s|impression|clinical reasoning|treatment|follow[- ]?up|recommendations?"),
]


def _strip_markup(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^#{1,6}\s*", "", s)
    s = re.sub(r"^(?:[-*+•]|\d+[.)]|[IVX]+[.)])\s+", "", s)
    s = s.replace("**", "").replace("__", "").strip()
    return s


def _main_heading(line: str):
    """Return (section, rest_of_line) if the line opens a SOAP section, else None."""
    s = _strip_markup(line)
    m = _MAIN_HEADING.match(s)
    if not m:
        return None
    rest = m.group("rest").strip()
    # "Subjective findings include ..." is prose, not a heading: need a colon or nothing after the name.
    if rest and not m.group("colon"):
        return None
    name = m.group("name").lower().replace(" ", "")
    section = "subjective" if name.startswith("subj") else "objective" if name.startswith("obj") else "ap"
    return section, rest.strip("* ")


def _fallback_heading(line: str):
    s = _strip_markup(line)
    head, _, rest = s.partition(":")
    head = head.strip()
    if not head or len(head.split()) > 6:
        return None
    if not (s.endswith(":") or rest):  # needs "Heading:" or "Heading: text"
        return None
    for section, pat in _FALLBACK_SUBHEADINGS:
        if re.fullmatch(rf"(?:{pat})(?:\s*\(.*\))?(?:\s*(?:&|and)\s*.*)?", head, re.IGNORECASE):
            return section, rest.strip()
    return None


_PREAMBLE = re.compile(r"^(here is|here's|below is|this is the|soap note|sure[,!.]|certainly)", re.IGNORECASE)


def split_umedsum_note(note: str) -> dict:
    """Split a Stage 1 uMedSum note into S, O and A/P.

    The baseline prompt asks for 'SUBJECTIVE:', 'OBJECTIVE:', 'ASSESSMENT AND PLAN:'. Text before the
    first heading (chat preambles) is dropped. If no main headings are found, the baseline's own
    sub-headings (Chief Complaint, Physical Examination, ...) are used instead.
    """
    out = {"subjective": [], "objective": [], "ap": [], "preamble": []}
    lines = note.splitlines()
    found = {"subjective": False, "objective": False, "ap": False}
    for detector in (_main_heading, _fallback_heading):
        out = {"subjective": [], "objective": [], "ap": [], "preamble": []}
        found = {"subjective": False, "objective": False, "ap": False}
        current = "preamble"
        for line in lines:
            h = detector(line)
            if h:
                current, rest = h
                found[current] = True
                if rest:
                    out[current].append(rest)
                continue
            out[current].append(line.rstrip())
        if found["subjective"] or found["objective"]:
            mode = "main_headings" if detector is _main_heading else "subheadings"
            break
    else:
        # No recognisable headings: keep the whole note as S/O so nothing is silently lost (flagged).
        mode = "unparsed"
        out = {"subjective": lines, "objective": [], "ap": [], "preamble": []}
    clean = lambda xs: "\n".join(xs).strip()
    return {
        "subjective": clean(out["subjective"]),
        "objective": clean(out["objective"]),
        "assessment_and_plan": clean(out["ap"]),
        "dropped_preamble": clean(out["preamble"]),
        "parse_mode": mode,
        "parse_ok": mode != "unparsed" and found["ap"],
    }


# ---------------------------------------------------------------------------------------------
# Stage 2 helper: the baseline's unit splitter, with the header bug fixed
# ---------------------------------------------------------------------------------------------
def make_remover_class(fix_header_bug: bool):
    from confabulation_remover import ConfabulationRemover

    class SectionRemover(ConfabulationRemover):
        """Runs RTB-TS on one section at a time.

        The baseline's clean_summary_text() treats ANY line that contains 'EXAM', 'PLAN', 'OBJECTIVE',
        'ASSESSMENT', 'SUBJECTIVE', 'CHIEF COMPLAINT' or 'HISTORY OF PRESENT ILLNESS' as a heading and
        drops it before NLI scoring (e.g. 'Physical examination revealed ...', 'He explained ...').
        Its bullet regex also strips leading numbers ('50-year-old' -> '-year-old'). With
        fix_header_bug=True only short heading-like lines are skipped and only real bullets are
        stripped; scoring and thresholds are unchanged. Set False to reproduce the baseline exactly.
        """
        forced_section = "SUBJECTIVE"

        def clean_summary_text(self, text):
            if not fix_header_bug:
                units = super().clean_summary_text(text)
                for u in units:
                    u["section"] = self.forced_section
                return units
            units = []
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                hdr = _strip_markup(s).rstrip(":").strip()
                if (":" not in hdr and len(hdr.split()) <= 6 and not re.search(r"[.!?]$", hdr) and (
                        s.endswith(":") or _main_heading(hdr) or _fallback_heading(hdr + ":"))):
                    continue  # a bare heading such as 'Chief Complaint:' or 'Physical Examination & Vitals'
                if re.match(r"^(here is|here's|below is|this is the|soap note:?)", s, re.IGNORECASE):
                    continue
                if re.match(r"^(please note|note:|disclaimer:)", s, re.IGNORECASE):
                    continue
                body = re.sub(r"^(?:[-*+•]|\d+[.)])\s+", "", s).replace("**", "").replace("__", "").strip()
                if len(body.split()) < 3:
                    continue
                for seg in self.segmenter.segment(body):
                    seg = seg.strip()
                    if len(seg.split()) >= 3:
                        units.append({"unit": seg, "section": self.forced_section})
            return units

    return SectionRemover


# ---------------------------------------------------------------------------------------------
# Stage 3 helper: Algorithm 2 (GPT-2 perplexity insertion) over S/O with section tracking
# ---------------------------------------------------------------------------------------------
def perplexity_insert(merger, units, missing):
    """units: list of (section, sentence). Each missing sentence goes where total perplexity is lowest
    (baseline Algorithm 2). Its section is that of the preceding sentence (or the next one at index 0)."""
    units = list(units)
    log = []
    for sent in missing:
        if not units:
            units.append(("subjective", sent))
            log.append({"inserted_sentence": sent, "location_index": 0, "section": "subjective", "best_ppl": None})
            continue
        best_loc, best_ppl = 0, float("inf")
        texts = [u[1] for u in units]
        for loc in range(len(texts) + 1):
            ppl = merger.calculate_perplexity(" ".join(texts[:loc] + [sent] + texts[loc:]))
            if ppl < best_ppl:
                best_loc, best_ppl = loc, ppl
        section = units[best_loc - 1][0] if best_loc > 0 else units[0][0]
        units.insert(best_loc, (section, sent))
        log.append({"inserted_sentence": sent, "location_index": best_loc, "section": section,
                    "best_ppl": round(best_ppl, 2)})
    return units, log


def units_to_so(units, sections=("subjective", "objective")):
    return {sec: "\n".join(t for s, t in units if s == sec) for sec in sections}


# ---------------------------------------------------------------------------------------------
# Per-case pipeline
# ---------------------------------------------------------------------------------------------
def run_case(rec, ctx, args):
    from stage1_generator import run_stage1_element_aware

    t0 = time.time()
    conv = rec["conversation"]
    out = {"case_id": rec["case_id"], "split": rec["split"], "is_icl_demo": rec["case_id"] in ctx["icl_ids"]}

    full = args.scope == "soap"
    sections = ("subjective", "objective", "assessment_and_plan") if full else ("subjective", "objective")

    # ---- Stage 1: unchanged baseline generator (Element-Aware 2-step + 1-shot ICL) ----------------
    s1 = None
    cache_p = Path(args.stage1_cache) / f"{rec['case_id']}.json" if args.stage1_cache else None
    if cache_p and cache_p.exists():
        prev = json.loads(cache_p.read_text(encoding="utf-8"))
        if prev.get("status") == "success" and prev.get("stage1_raw_note"):
            s1 = {"stage1_summary": prev["stage1_raw_note"], "stage1_elements": prev.get("stage1_elements")}
            out["stage1_reused_from"] = str(cache_p)
    if s1 is None:
        s1 = run_stage1_element_aware(ctx["client"], {"src": conv}, icl_prefix=ctx["icl_prefix"])
    parsed = split_umedsum_note(s1["stage1_summary"])
    stage1_so = {sec: parsed[sec] for sec in sections}
    stage1_ap = {"assessment_and_plan": parsed["assessment_and_plan"]}
    out.update({
        "stage1_elements": s1["stage1_elements"],
        "stage1_raw_note": s1["stage1_summary"],
        "stage1_parse": {k: parsed[k] for k in ("parse_mode", "parse_ok", "dropped_preamble")},
        "stage1_so": stage1_so,
        "stage1_ap": stage1_ap,
    })

    # ---- Stage 2: RTB-TS section by section (S, O; plus A/P in --scope soap) ------------------------
    remover = ctx["remover"]
    stage2_units, details, removed, n_claims, n_kept = [], {}, [], 0, 0
    for section in sections:
        text = stage1_so[section]
        if not text.strip():
            details[section] = []
            continue
        remover.forced_section = section.upper()
        res = remover.process_summary(conv, text)
        stage2_units += [(section, u) for u in res["faithful_units"]]
        details[section] = res["details"]
        for d in res["details"]:
            n_claims += 1
            kept = d["classification"] == "faithful" or bool(d.get("atomic_decomposition", {}).get("retained"))
            n_kept += int(kept)
            if d["classification"] == "confabulated":
                removed.append({"section": section, "claim": d["unit"], "scores": d["scores"], "reason": d["reasoning"]})
            for a in d.get("atomic_decomposition", {}).get("discarded", []):
                removed.append({"section": section, "claim": a["atom"], "entailment": a["entailment"],
                                "reason": a["reasoning"], "from_unit": d["unit"]})
    stage2_so = units_to_so(stage2_units, sections)
    counts = {}
    for sec in details.values():
        for d in sec:
            counts[d["classification"]] = counts.get(d["classification"], 0) + 1
    out.update({
        "stage2_so": stage2_so,
        "stage2_audit": details,
        "stage2_stats": {"decision_counts": counts, "num_claims": n_claims, "num_kept": n_kept,
                         "claim_retention_rate": round(n_kept / n_claims, 4) if n_claims else None},
    })

    # ---- Stage 3: missing-information addition on S/O --------------------------------------------
    extractor, detector, merger = ctx["extractor"], ctx["detector"], ctx["merger"]
    key_sents = extractor.extract_document_key_sentences(conv, top_m=args.top_m)
    so_flat = " ".join(t for _, t in stage2_units)
    phrases = extractor.extract_summary_key_phrases(so_flat, top_n=10)
    detection = detector.detect_missing_sentences(key_sents, phrases)
    missing = detection["missing_sentences"]
    if args.no_gpt2:
        final_units = stage2_units + [("subjective", m) for m in missing]
        ins_log = [{"inserted_sentence": m, "location_index": None, "section": "subjective", "best_ppl": None}
                   for m in missing]
    else:
        final_units, ins_log = perplexity_insert(merger, stage2_units, missing)
    stage3_so = units_to_so(final_units, sections)
    cov = {c["sentence"]: c["score"] for c in detection["coverage_scores"]}
    out.update({
        "stage3_so": stage3_so,
        "stage3_key_sentences": key_sents,
        "stage3_summary_key_phrases": phrases,
        "stage3_coverage_scores": detection["coverage_scores"],
        # Same shape as Verify-and-Ask so evaluate.py computes gap-detection / addition metrics.
        "stage3_candidate_log": [{"candidate": m, "statement": m, "coverage": cov.get(m), "status": "added",
                                  "reason": "coverage <= cov_min (uMedSum adds the dialogue sentence verbatim)",
                                  "insertion": {"section": l["section"], "line_index": l["location_index"],
                                                "perplexity": l["best_ppl"]}}
                                 for m, l in zip(missing, ins_log)],
        "stage3_added": [{"statement": m, "evidence": m, "section": l["section"], "candidate": m}
                         for m, l in zip(missing, ins_log)],
        "stage3_stats": {"num_key_sentences": len(key_sents), "num_flagged": len(missing), "num_added": len(missing)},
        "gaps": {"gaps": [], "dropped": [], "num_generated": 0},  # uMedSum has no Ask stage
        "unsupported_claims": {"removed_stage2": removed},
    })

    # ---- Final note ------------------------------------------------------------------------------
    if full:   # A/P went through Stages 2-3 like S and O (original uMedSum: the whole note is processed)
        final_ap = {"assessment_and_plan": stage3_so["assessment_and_plan"]}
        out.update({"final_ap": final_ap, "scope": "soap",
                    "ap_changed": final_ap["assessment_and_plan"] != stage1_ap["assessment_and_plan"]})
        ref = rec.get("reference_soap") or {}
        reference = {"subjective": ref.get("subjective", ""), "objective": ref.get("objective", ""),
                     "assessment_and_plan": "\n".join(x for x in (ref.get("assessment", ""), ref.get("plan", "")) if x).strip()}
    else:      # Stage 3 S/O + untouched Stage 1 A/P
        final_ap = dict(stage1_ap)
        out.update({"final_ap": final_ap, "scope": "so",
                    "ap_unchanged": final_ap == stage1_ap and final_ap["assessment_and_plan"] == parsed["assessment_and_plan"]})
        reference = rec["reference_so"]
    out.update({
        "thresholds": {"Te": args.te, "Tc": args.tc, "Ta": args.ta, "cov_min": args.cov_min, "top_m": args.top_m,
                       "fix_header_bug": not args.reproduce_header_bug},
        "models": {"llm": args.model, "nli": args.nli_model, "embedder": "all-MiniLM-L6-v2", "ppl": args.ppl_model},
        "status": "success",
        "seconds": round(time.time() - t0, 1),
        "conversation": conv,
        "reference_so": reference,  # evaluation only; never passed to a model (full SOAP in --scope soap)
    })
    return out


def write_final_note(path, r):
    so, ap = r["stage3_so"], r["final_ap"]["assessment_and_plan"]
    ap_title = "Assessment and Plan" if r.get("scope") == "soap" else "Assessment and Plan (Stage 1, unchanged)"
    path.write_text(
        f"# {r['case_id']} - uMedSum final note\n\n## Subjective\n{so['subjective'] or '(empty)'}\n\n"
        f"## Objective\n{so['objective'] or '(empty)'}\n\n## {ap_title}\n{ap or '(empty)'}\n",
        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="uMedSum on the agentic SOAP-note consultations (RQ1-matched)")
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--icl-json", default=str(DEFAULT_ICL))
    ap.add_argument("--n-shots", type=int, default=1)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--split", choices=["dev", "test", "all"], default="all")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default="llama3:8b")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--nli-model", default="MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli")
    ap.add_argument("--ppl-model", default="gpt2")
    ap.add_argument("--te", type=float, default=0.9)
    ap.add_argument("--tc", type=float, default=0.8)
    ap.add_argument("--ta", type=float, default=0.5)
    ap.add_argument("--cov-min", type=float, default=0.4)
    ap.add_argument("--top-m", type=int, default=2)
    ap.add_argument("--no-gpt2", action="store_true", help="append missing sentences instead of GPT-2 placement")
    ap.add_argument("--reproduce-header-bug", action="store_true",
                    help="use the baseline's original line filter in Stage 2 (drops lines containing EXAM/PLAN/...)")
    ap.add_argument("--exclude-from-scoring", nargs="*", default=[],
                    help="case ids that are run but kept out of scoring (their split becomes 'excluded_icl_demo'); "
                         "use for an ICL demonstration that falls in the test split, e.g. D2N002")
    ap.add_argument("--scope", choices=["so", "soap"], default="so",
                    help="so: Stages 2-3 on S/O, A/P passed through (RQ1-matched). "
                         "soap: Stages 2-3 on S, O and A/P, all scored (original uMedSum)")
    ap.add_argument("--stage1-cache", default=None,
                    help="folder of earlier per-case outputs (cases/) whose Stage 1 note is reused instead of regenerated")
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    cases_dir, notes_dir = out_dir / "cases", out_dir / "final_notes"
    cases_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    records = data["records"]
    n_dev = sum(r["split"] == "dev" for r in records)
    n_test = sum(r["split"] == "test" for r in records)
    print(f"Dataset: {len(records)} cases ({n_dev} dev / {n_test} test), seed {data.get('split_seed')}")

    # ---- leakage guard: the ICL demonstration must not be a test case ----------------------------
    icl_data = json.loads(Path(args.icl_json).read_text(encoding="utf-8"))["data"][: args.n_shots]
    icl_ids = {d.get("encounter_id") or d.get("file", "").split("-")[0] for d in icl_data}
    excluded = set(args.exclude_from_scoring)
    split_of = {r["case_id"]: ("excluded_icl_demo" if r["case_id"] in excluded else r["split"]) for r in records}
    leaked = {c for c in icl_ids if split_of.get(c) == "test"}
    if leaked:
        sys.exit(f"[LEAKAGE] ICL demonstration(s) {sorted(leaked)} are test cases. "
                 f"Pass --exclude-from-scoring {' '.join(sorted(leaked))} to run them but keep them out of scoring.")
    print(f"ICL demonstration(s): {sorted(icl_ids)} - none scored in the test split. "
          f"Excluded from scoring: {sorted(excluded) or 'none'}. "
          f"Demo cases by split: { {c: split_of.get(c, 'not in dataset') for c in sorted(icl_ids)} }")

    if args.split != "all":
        records = [r for r in records if r["split"] == args.split]
    if args.limit:
        records = records[: args.limit]

    # ---- models -----------------------------------------------------------------------------------
    from ollama_client import OllamaClient
    from prompts import format_icl_demonstrations
    from nli_scorer import DebertaNLIScorer
    from atomic_decomposer import AtomicDecomposer
    from key_extractor import KeyExtractor
    from missing_detector import MissingInformationDetector
    from perplexity_merger import PerplexityMerger

    client = OllamaClient(base_url=args.ollama_url, model=args.model)
    if not client.check_connection():
        sys.exit(f"Ollama is not reachable at {args.ollama_url}. Start `ollama serve` and pull {args.model}.")
    if not any(args.model in m for m in client.list_models()):
        sys.exit(f"Model {args.model} is not pulled. Run: ollama pull {args.model}")
    Remover = make_remover_class(fix_header_bug=not args.reproduce_header_bug)
    extractor = KeyExtractor()
    ctx = {
        "client": client,
        "icl_prefix": format_icl_demonstrations(icl_data, n_shots=args.n_shots),
        "icl_ids": icl_ids,
        "remover": Remover(DebertaNLIScorer(model_name=args.nli_model),
                           AtomicDecomposer(ollama_url=args.ollama_url, model=args.model),
                           te=args.te, tc=args.tc, ta=args.ta),
        "extractor": extractor,
        "detector": MissingInformationDetector(embedder=extractor.embedder, cov_min=args.cov_min),
        "merger": None if args.no_gpt2 else PerplexityMerger(model_name=args.ppl_model),
    }

    # ---- run, one checkpoint file per case ---------------------------------------------------------
    t_start = time.time()
    for i, rec in enumerate(records, 1):
        cpath = cases_dir / f"{rec['case_id']}.json"
        if cpath.exists() and not args.overwrite:
            prev = json.loads(cpath.read_text(encoding="utf-8"))
            if prev.get("status") == "success" and prev.get("scope", "so") != args.scope:
                sys.exit(f"{cpath} was produced with --scope {prev.get('scope', 'so')}; use a different --out-dir "
                         f"for --scope {args.scope} (pass the old cases/ folder as --stage1-cache to reuse Stage 1).")
            if prev.get("status") == "success" or not args.retry_errors:
                print(f"[{i}/{len(records)}] {rec['case_id']}: cached ({prev.get('status')})")
                continue
        print(f"[{i}/{len(records)}] {rec['case_id']} ({rec['split']}) ...", end="", flush=True)
        try:
            r = run_case(rec, ctx, args)
            write_final_note(notes_dir / f"{rec['case_id']}.md", r)
            st = r["stage2_stats"]
            print(f" done {r['seconds']}s | parse={r['stage1_parse']['parse_mode']} | "
                  f"S2 kept {st['num_kept']}/{st['num_claims']} | S3 added {r['stage3_stats']['num_added']}")
        except Exception as exc:
            r = {"case_id": rec["case_id"], "split": rec["split"], "status": "error",
                 "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            print(f" FAILED: {r['error']}")
        cpath.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- combine every case checkpoint into one file (the evaluator's input) ----------------------
    all_recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(cases_dir.glob("*.json"))]
    # Split labels always come from the dataset in use (cached cases may carry a label from an older split).
    all_recs = [r for r in all_recs if r["case_id"] in split_of]
    for r in all_recs:
        r["split"] = split_of[r["case_id"]]
    ok = [r for r in all_recs if r.get("status") == "success"]
    combined = {"system": "uMedSum (Element-Aware+1-shot ICL -> RTB-TS -> MMR/GPT-2), " + (
                    "full SOAP: S, O and A/P processed" if args.scope == "soap" else "S/O only, A/P passthrough"),
                "scope": args.scope,
                "num_cases": len(all_recs), "num_success": len(ok), "num_errors": len(all_recs) - len(ok),
                "icl_demo_ids": sorted(icl_ids), "excluded_from_scoring": sorted(excluded),
                "split_counts": {k: sum(r["split"] == k for r in all_recs) for k in sorted(set(split_of.values()))},
                "records": all_recs}
    (out_dir / "umedsum_output.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    parse_modes = {}
    for r in ok:
        m = r["stage1_parse"]["parse_mode"] + ("" if r["stage1_parse"]["parse_ok"] else " (no A/P heading)")
        parse_modes[m] = parse_modes.get(m, 0) + 1
    print(f"\nFinished in {round(time.time() - t_start)}s. {len(ok)}/{len(all_recs)} cases succeeded.")
    print("Stage 1 section parsing:", parse_modes)
    if ok and all("ap_unchanged" in r for r in ok):
        print("A/P unchanged rate:", round(sum(r["ap_unchanged"] for r in ok) / len(ok), 4))
    elif ok:
        print("A/P changed by Stages 2-3 in", sum(bool(r.get("ap_changed")) for r in ok), "of", len(ok), "cases (scope soap)")
    print("Saved", out_dir / "umedsum_output.json")


if __name__ == "__main__":
    main()
