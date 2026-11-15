"""Build the U4 reference corpus from MedlinePlus Health Topics (public-domain XML, NLM).

  python medlineplus.py                       # discover the current XML on medlineplus.gov/xml.html, download
  python medlineplus.py --xml mplus_topics_2026-11-01.xml   # or use a file you downloaded yourself

Writes reference_corpus/chunks.jsonl (one passage per section/paragraph group) and an embedding matrix.
Only Health Topic summaries are used: the A.D.A.M. encyclopedia pages on MedlinePlus are licensed, not
public domain, so they are deliberately not scraped.
"""
import argparse
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import config as C
from common import write_jsonl, read_jsonl

INDEX_URL = "https://medlineplus.gov/xml.html"


def discover_url():
    import requests
    page = requests.get(INDEX_URL, timeout=60).text
    files = sorted(set(re.findall(r"(https?://medlineplus\.gov/xml/mplus_topics_\d{4}-\d{2}-\d{2}\.xml)", page)))
    if not files:
        files = sorted(set("https://medlineplus.gov/xml/" + f
                           for f in re.findall(r"(mplus_topics_\d{4}-\d{2}-\d{2}\.xml)", page)))
    if not files:
        raise RuntimeError("Could not find mplus_topics_*.xml on xml.html; pass --xml or MEDLINEPLUS_XML_URL")
    return files[-1]


def download(url, dest: Path):
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for b in r.iter_content(1 << 20):
                f.write(b)
    return dest


def _html_blocks(summary_html: str):
    """Split the full-summary HTML into (heading, text) blocks."""
    s = re.sub(r"<(ul|ol)>", "\n", summary_html)
    s = re.sub(r"<li>", "\n- ", s)
    parts = re.split(r"<h[2-4][^>]*>(.*?)</h[2-4]>", s, flags=re.DOTALL)
    blocks, heading = [], "Summary"
    for i, p in enumerate(parts):
        if i % 2 == 1:
            heading = re.sub(r"<[^>]+>", "", p).strip() or heading
            continue
        text = html.unescape(re.sub(r"<[^>]+>", " ", p))
        text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()
        if text:
            blocks.append((heading, text))
    return blocks


def chunk_words(text, max_words=140):
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    out, cur = [], []
    for p in paras:
        if cur and len(" ".join(cur + [p]).split()) > max_words:
            out.append(" ".join(cur))
            cur = []
        cur.append(p)
    if cur:
        out.append(" ".join(cur))
    return out


def parse(xml_path: Path):
    root = ET.parse(xml_path).getroot()
    chunks = []
    for t in root.iter("health-topic"):
        if t.get("language", "English") != "English":
            continue
        title = t.get("title", "")
        syn = [a.text for a in t.findall("also-called") if a.text]
        fs = t.find("full-summary")
        if fs is None or not (fs.text or "").strip():
            continue
        for heading, text in _html_blocks(fs.text):
            for j, piece in enumerate(chunk_words(text)):
                chunks.append(dict(pid=f"{t.get('id')}_{len(chunks)}", title=title, section=heading,
                                   url=t.get("url", ""), also_called=syn,
                                   text=piece, index_text=f"{title} ({', '.join(syn)}). {heading}. {piece}"))
    return chunks


def load_reference_index(embedder=None):
    """HybridIndex over MedlinePlus chunks (embeddings cached to disk)."""
    import numpy as np
    from retrieval import HybridIndex, get_embedder
    chunks = read_jsonl(C.REF_DIR / "chunks.jsonl")
    if not chunks:
        raise FileNotFoundError("reference_corpus/chunks.jsonl missing - run medlineplus.py first")
    emb = embedder or get_embedder()
    tag = re.sub(r"\W+", "_", C.EMBED_MODEL if embedder is None else type(embedder).__name__)
    cache = C.REF_DIR / f"emb_{tag}.npy"
    if cache.exists():
        E = np.load(cache)
    else:
        E = np.asarray(emb.encode([c["index_text"] for c in chunks], normalize_embeddings=True,
                                  batch_size=64, show_progress_bar=True))
        np.save(cache, E)
    return HybridIndex(chunks, text_key="index_text", embedder=emb, embeddings=E)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", help="local mplus_topics_*.xml")
    a = ap.parse_args()
    if a.xml:
        xml_path = Path(a.xml)
    else:
        url = C.MEDLINEPLUS_XML_URL or discover_url()
        print("downloading", url)
        xml_path = download(url, C.REF_DIR / Path(url).name)
    chunks = parse(xml_path)
    write_jsonl(C.REF_DIR / "chunks.jsonl", chunks)
    print(f"{len(chunks)} passages from {len({c['title'] for c in chunks})} topics -> {C.REF_DIR / 'chunks.jsonl'}")
    load_reference_index()
    print("embeddings cached")
