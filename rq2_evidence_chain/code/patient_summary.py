# blocks 13-14: checked patient summary + H3
"""Blocks 13-14: plain-language patient summary from the signed note, each sentence checked, plus H3.

13 Summary writer  (generator, Qwen3-14B): rewrites the SIGNED note (signoff.py) for the patient.
14 Summary checker (verifier 3B, S/O entailment prompt): each summary sentence must be supported by the signed
                    note (P(supported) >= --tau, default 0.5); unsupported sentences are dropped and logged.

H3 control: the same writer on the UNVERIFIED record (RQ1 Stage 1 S/O + Stage 1 A/P, nothing checked), with no
checker. Both summaries are then measured the same way:
  unsupported_vs_signed   sentences not supported by the signed note (content the verified record does not hold)
  unsupported_vs_dialogue sentences not supported by the conversation (independent check)
  next_step_recall        share of signed Plan lines that the summary covers
  fk_grade                Flesch-Kincaid grade (reading level; lower = easier)
Warning-sign recall is not computed: the notes rarely state warning signs, so there is nothing to recall.

Usage (after signoff.py, generator server and verifier as for run_rq2.py):
  python patient_summary.py                     # all cases in ../rq2_on_verify_and_ask/cases
  python patient_summary.py --limit 5           # quick check
Writes, next to signoff.py's output:
  patient_summaries/<case>.md             final verified summary (reader 2)
  patient_summaries_unverified/<case>.md  H3 control summary
  summaries/<case>.json                   both summaries, every sentence with its check scores
  patient_summary_metrics.json / .md      H3 table (va_test, and all cases)
Resumable: finished cases are skipped.
"""
import argparse
import json
import re
from pathlib import Path

import config as C
from common import read_json, split_sentences, strip_bullet, write_json
from prompts import entail_messages

SYSTEM = ("You write plain-language visit summaries for patients, based only on the clinician's note you are "
          "given. Output JSON only.")
USER = """Clinician's note:
{note}

Write a short summary of this visit for the patient.
Rules:
- Use ONLY information in the note. Do not add any diagnosis, test, medicine, dose, number, timing or advice
  that the note does not contain. If the note has no plan, say that the next steps will be discussed.
- Speak to the patient as "you". Short sentences, everyday words, about a grade 6-8 reading level.
  If you must use a medical word, explain it in a few plain words.
- 5 to 10 sentences, grouped in these parts (skip a part if the note has nothing for it):
  "why_you_came", "what_we_found", "what_it_may_be", "next_steps".
Return JSON: {{"sentences": [{{"part": "why_you_came", "text": "..."}}, ...]}}"""
PART_TITLES = {"why_you_came": "Why you came in", "what_we_found": "What we found",
               "what_it_may_be": "What it may be", "next_steps": "What happens next"}


def note_text(so, assessment, plan):
    def block(x):
        if isinstance(x, list):
            return "\n".join(f"- {t}" for t in x) or "- (none)"
        lines = [strip_bullet(l.strip()) for l in (x or "").splitlines() if l.strip()]
        return "\n".join(f"- {l}" for l in lines) or "- (none)"
    return (f"SUBJECTIVE\n{block(so.get('subjective'))}\n\nOBJECTIVE\n{block(so.get('objective'))}\n\n"
            f"ASSESSMENT\n{block(assessment)}\n\nPLAN\n{block(plan)}")


def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups) - (1 if w.endswith("e") and len(groups) > 1 and not w.endswith("le") else 0)
    return max(1, n)


def fk_grade(sentences):
    words = [w for s in sentences for w in re.findall(r"[A-Za-z']+", s)]
    if not sentences or not words:
        return None
    return round(0.39 * len(words) / len(sentences) + 11.8 * sum(map(syllables, words)) / len(words) - 15.59, 2)


def p_supported(verifier, evidence, claim):
    return verifier.score(entail_messages(evidence, claim), C.LABELS_ENTAIL)["probs"]["supported"]


def write_summary(llm, note):
    out = llm.chat_json(SYSTEM, USER.format(note=note), temperature=0.0, max_tokens=900) or {}
    sents = []
    for item in out.get("sentences", []) if isinstance(out, dict) else []:
        txt = (item.get("text") or "").strip() if isinstance(item, dict) else ""
        for s in split_sentences(txt):
            sents.append(dict(part=item.get("part", "next_steps"), text=s))
    return sents


def stub_writer(system, user):
    """Offline test only: copies the note's lines as 'summary' sentences."""
    lines = [l[2:] for l in user.split("Write a short summary")[0].splitlines() if l.startswith("- ")][:8]
    return json.dumps({"sentences": [{"part": "what_we_found", "text": l} for l in lines if l != "(none)"]})


def measure(verifier, sents, signed, dialogue, plan_lines, tau):
    for s in sents:
        s.setdefault("p_vs_signed", round(p_supported(verifier, signed, s["text"]), 4))
        s["p_vs_dialogue"] = round(p_supported(verifier, dialogue, s["text"]), 4)
    summary_txt = " ".join(s["text"] for s in sents)
    covered = [p_supported(verifier, summary_txt, p) >= tau for p in plan_lines] if sents else [False] * len(plan_lines)
    return dict(n_sentences=len(sents),
                unsupported_vs_signed=sum(s["p_vs_signed"] < tau for s in sents),
                unsupported_vs_dialogue=sum(s["p_vs_dialogue"] < tau for s in sents),
                next_step_recall=round(sum(covered) / len(plan_lines), 4) if plan_lines else None,
                fk_grade=fk_grade([s["text"] for s in sents]))


def to_md(case_id, sents, title):
    md = [f"# {title} — {case_id}", ""]
    for part, head in PART_TITLES.items():
        ps = [s["text"] for s in sents if s["part"] == part]
        if ps:
            md += [f"## {head}", " ".join(ps), ""]
    if len(md) == 2:
        md.append("_No summary sentences passed the check._")
    return "\n".join(md) + "\n"


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", default=str(C.REPO / "rq2_on_verify_and_ask"), help="signoff.py output folder")
    ap.add_argument("--va-cases", default=str(C.REPO / "rq1_verify_and_ask" / "Stage23_pipeline" / "output"
                                              / "cases"))
    ap.add_argument("--tau", type=float, default=0.5, help="P(supported) needed to keep a summary sentence")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    from llm import GenLLM
    from verifier import make_verifier
    llm, verifier = GenLLM(), make_verifier()
    if C.GEN_BACKEND == "stub":
        llm.stub_fn = stub_writer
    final = Path(a.final)
    for d in ("patient_summaries", "patient_summaries_unverified", "summaries"):
        (final / d).mkdir(parents=True, exist_ok=True)

    cases = sorted((final / "cases").glob("*.json"))[:a.limit]
    rows = []
    for n, p in enumerate(cases, 1):
        case = read_json(p)
        cid = case["case_id"]
        out_p = final / "summaries" / f"{cid}.json"
        if out_p.exists():
            rows.append(read_json(out_p))
            continue
        signed = case["signed_note"]
        signed_txt = note_text(signed, signed["assessment"], signed["plan"])
        dialogue = "\n".join(f"[{t['tid']}] {t['speaker']}: {t['text']}" for t in case["conversation_turns"])
        va = json.loads((Path(a.va_cases) / f"{cid}.json").read_text(encoding="utf-8"))
        unverified_txt = note_text(va["stage1_so"], va["stage1_ap"].get("assessment"), va["stage1_ap"].get("plan"))

        # 13 + 14: verified summary
        draft = write_summary(llm, signed_txt)
        for s in draft:
            s["p_vs_signed"] = round(p_supported(verifier, signed_txt, s["text"]), 4)
            s["kept"] = s["p_vs_signed"] >= a.tau
        final_sents = [dict(s) for s in draft if s["kept"]]
        # H3 control: unverified record, no checker
        control = write_summary(llm, unverified_txt)

        m_final = measure(verifier, final_sents, signed_txt, dialogue, signed["plan"], a.tau)
        m_ctrl = measure(verifier, control, signed_txt, dialogue, signed["plan"], a.tau)
        row = dict(case_id=cid, rq2_split=case["rq2_split"], scored=case["scored"],
                   draft=draft, dropped=[s for s in draft if not s["kept"]],
                   verified_summary=final_sents, unverified_summary=control,
                   metrics_verified=m_final, metrics_unverified=m_ctrl,
                   draft_unsupported_vs_signed=sum(not s["kept"] for s in draft))
        write_json(out_p, row)
        (final / "patient_summaries" / f"{cid}.md").write_text(
            to_md(cid, final_sents, "Your visit summary"), encoding="utf-8")
        (final / "patient_summaries_unverified" / f"{cid}.md").write_text(
            to_md(cid, control, "Visit summary from the UNVERIFIED note (H3 control)"), encoding="utf-8")
        rows.append(row)
        print(f"  [{n}/{len(cases)}] {cid}: kept {len(final_sents)}/{len(draft)} sentences", flush=True)

    def table(sel):
        out = {}
        for key, name in (("metrics_verified", "verified (signed note + checker)"),
                          ("metrics_unverified", "unverified record, no checker")):
            ms = [r[key] for r in sel]
            out[name] = dict(cases=len(ms),
                             unsupported_vs_signed_per_summary=avg([m["unsupported_vs_signed"] for m in ms]),
                             unsupported_vs_dialogue_per_summary=avg([m["unsupported_vs_dialogue"] for m in ms]),
                             next_step_recall=avg([m["next_step_recall"] for m in ms]),
                             fk_grade=avg([m["fk_grade"] for m in ms]),
                             sentences_per_summary=avg([m["n_sentences"] for m in ms]))
        out["checker"] = dict(draft_sentences_dropped_per_summary=avg([r["draft_unsupported_vs_signed"] for r in sel]))
        return out

    res = {"tau": a.tau, "va_test": table([r for r in rows if r["rq2_split"] == "va_test"]),
           "all_cases": table(rows)}
    write_json(final / "patient_summary_metrics.json", res)
    md = ["# H3: patient summaries", "",
          "Unsupported = P(supported) below the threshold. Lower is better for unsupported counts and reading grade.", ""]
    for scope in ("va_test", "all_cases"):
        t = res[scope]
        md += [f"## {scope}", "", "| summary built from | cases | unsupported vs signed note | unsupported vs dialogue "
               "| next-step recall | reading grade (FK) | sentences |", "|---|---|---|---|---|---|---|"]
        for name, v in t.items():
            if name == "checker":
                continue
            md.append(f"| {name} | {v['cases']} | {v['unsupported_vs_signed_per_summary']} | "
                      f"{v['unsupported_vs_dialogue_per_summary']} | {v['next_step_recall']} | {v['fk_grade']} | "
                      f"{v['sentences_per_summary']} |")
        md += ["", f"Checker dropped {t['checker']['draft_sentences_dropped_per_summary']} draft sentence(s) "
                   f"per summary.", ""]
    (final / "patient_summary_metrics.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
