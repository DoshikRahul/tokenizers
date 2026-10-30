"""Preflight check for the LLM server (OpenAI-compatible or Ollama).

  set LLM_BASE_URL=http://HOST:8080/v1 ; set LLM_API_KEY=...   (key from the environment only)
  python check_llm.py

Reports reachability, the model name, and whether the server's context window is large enough for
the pipeline prompts (Stage 1 needs ~2.5k tokens, Ask needs ~4-5k, plus the reply).
"""
import sys
import time

import config as C

NEEDED_TOKENS = 3600  # approx. tokens in the probe prompt (Stage 1 is ~2.3k; Ask can reach ~4k)


def main():
    import requests
    from llm_client import LLMClient
    llm = LLMClient()
    print(f"backend={llm.backend} url={llm.url} model={llm.model}")
    t0 = time.time()
    try:
        print("hello test ->", llm.chat("Reply briefly.", "Reply with the single word OK.", num_predict=5))
    except Exception as exc:
        sys.exit(f"FAILED basic call: {exc}")
    print(f"latency {time.time() - t0:.1f}s")

    filler = ("The patient reports mild intermittent headache without nausea. " * 400)  # ~NEEDED_TOKENS tokens
    headers = {"Authorization": f"Bearer {C.LLM_API_KEY}"} if C.LLM_API_KEY else {}
    r = requests.post(llm.url, headers=headers, timeout=300, json={
        "model": llm.model, "max_tokens": 5,
        "messages": [{"role": "user", "content": filler + "\nSay OK."}]})
    if r.ok:
        print(f"context check: OK (accepted a ~{NEEDED_TOKENS}-token prompt)")
    else:
        print(f"context check: FAILED ({r.status_code}) {r.text[:300]}")
        print("Ask the server owner to restart with a larger context, e.g. llama-server -c 8192 "
              "(with --parallel N the context is split across slots, so use 8192*N).")
        sys.exit(1)


if __name__ == "__main__":
    main()
