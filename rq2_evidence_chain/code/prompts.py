"""Verifier prompts. Single source of truth: the QLoRA training script must build its inputs with these
same functions (and the same label strings in config.LABELS_*), otherwise label probabilities are
meaningless. Each builder returns chat messages; the target is the bare label string.
"""

ENTAIL_SYSTEM = (
    "You verify one statement from a clinical note against the evidence given. "
    "Answer with exactly one label:\n"
    "supported - the evidence states or directly entails the statement\n"
    "contradicted - the evidence states something incompatible with the statement\n"
    "unsupported - the evidence neither entails nor contradicts the statement")

CHAIN_SYSTEM = (
    "You check the evidence chain behind one Assessment or Plan statement in a clinical note. "
    "Assessment and Plan statements are clinical inferences: they do not need to be stated in the "
    "conversation. Judge whether the cited patient features{ref_clause}, combined with standard clinical "
    "knowledge, justify the statement as a reasonable conclusion (Assessment) or a reasonable, indicated "
    "action (Plan) for THIS patient.\n"
    "Answer with exactly one label:\n"
    "chain_ok - the cited features justify the statement and no cited feature conflicts with it\n"
    "chain_broken - the features do not justify it, a feature conflicts with it, or it depends on "
    "patient information that is not among the features")


def entail_messages(evidence: str, claim: str):
    return [{"role": "system", "content": ENTAIL_SYSTEM},
            {"role": "user", "content": f"Evidence:\n{evidence}\n\nStatement:\n{claim}\n\nLabel:"}]


def format_features(features):
    """features: [{'fid','text','turns':[...], 'quote'}]"""
    if not features:
        return "(no patient features were linked to this statement)"
    lines = []
    for f in features:
        src = f" (from {', '.join(f.get('turns') or [])})" if f.get("turns") else ""
        lines.append(f"- [{f['fid']}] {f['text']}{src}")
    return "\n".join(lines)


def format_references(passages):
    return "\n".join(f"[R{i}] {p['title']} - {p['section']}: {p['text']}" for i, p in enumerate(passages, 1))


def chain_messages(section: str, claim: str, features, passages=None):
    ref_clause = " and the reference passages" if passages else ""
    user = f"Section: {section}\nStatement: {claim}\n\nCited patient features:\n{format_features(features)}"
    if passages:
        user += f"\n\nReference passages (consumer-level, may be incomplete):\n{format_references(passages)}"
    user += "\n\nLabel:"
    return [{"role": "system", "content": CHAIN_SYSTEM.format(ref_clause=ref_clause)},
            {"role": "user", "content": user}]
