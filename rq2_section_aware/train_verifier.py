"""QLoRA fine-tuning of the verifier (Qwen2.5-3B-Instruct, LoRA rank 16) on {"messages", "target"} JSONL.

Inputs use the SAME prompt builders as inference (prompts.py), so label probabilities at test time
are meaningful. Loss is computed on the label tokens (+ end-of-turn) only.

  python train_verifier.py --data data_out/chain_train.jsonl --out models/verifier_qlora
  python train_verifier.py --data data_out/chain_train.jsonl data_out/so_train.jsonl --out models/verifier_qlora
  # 1080 Ti without 4-bit support in bitsandbytes: add --no-4bit (plain LoRA on fp16 weights, ~7 GB)

S/O pairs (if you build them) must look like: {"messages": prompts.entail_messages(evidence, claim), "target": "supported"}.
Encounters are split 90/10 into train / held-out (by encounter_id) and held-out label accuracy is printed.
"""
import argparse
import random

import config as C
from common import read_jsonl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--out", default=str(C.ROOT / "models" / "verifier_qlora"))
    ap.add_argument("--base", default=C.VERIFIER_BASE_MODEL)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=3072)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--no-4bit", action="store_true")
    a = ap.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer,
                              TrainingArguments)

    rows = [r for p in a.data for r in read_jsonl(p)]
    encs = sorted({r.get("encounter_id", str(i)) for i, r in enumerate(rows)})
    random.Random(C.SEED).shuffle(encs)
    held = set(encs[: max(1, len(encs) // 10)])
    train = [r for i, r in enumerate(rows) if r.get("encounter_id", str(i)) not in held]
    dev = [r for i, r in enumerate(rows) if r.get("encounter_id", str(i)) in held]
    print(f"train {len(train)}  held-out {len(dev)}  labels {sorted({r['target'] for r in rows})}")

    tok = AutoTokenizer.from_pretrained(a.base)
    tok.pad_token = tok.pad_token or tok.eos_token
    end = tok.eos_token if "<|im_end|>" not in tok.get_vocab() else "<|im_end|>"

    def encode(r):
        prompt = tok.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=True)
        p = tok(prompt, add_special_tokens=False)["input_ids"]
        t = tok(r["target"] + end, add_special_tokens=False)["input_ids"]
        if len(p) + len(t) > a.max_len:  # same truncation rule as verifier.HFVerifier
            keep = a.max_len - len(t)
            p = p[:64] + p[-(keep - 64):]
        return {"input_ids": p + t, "labels": [-100] * len(p) + t}

    train_ds = [encode(r) for r in train]

    def collate(batch):
        n = max(len(b["input_ids"]) for b in batch)
        ids = torch.full((len(batch), n), tok.pad_token_id)
        lab = torch.full((len(batch), n), -100)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):
            L = len(b["input_ids"])
            ids[i, :L], lab[i, :L], att[i, :L] = torch.tensor(b["input_ids"]), torch.tensor(b["labels"]), 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att}

    kw = {"device_map": "auto"}
    if a.no_4bit:
        kw["torch_dtype"] = torch.float16
    else:
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=torch.float16,
                                                       bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(a.base, **kw)
    if not a.no_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                                             "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()
    import inspect
    # transformers 5.x removed warmup_ratio; there a float < 1 in warmup_steps means the same ratio
    warm = ({"warmup_ratio": 0.03} if "warmup_ratio" in inspect.signature(TrainingArguments.__init__).parameters
            else {"warmup_steps": 0.03})
    args = TrainingArguments(output_dir=a.out, **warm, per_device_train_batch_size=1, gradient_accumulation_steps=a.grad_accum,
                             num_train_epochs=a.epochs, learning_rate=a.lr, lr_scheduler_type="cosine",
                             logging_steps=10, save_strategy="epoch", save_total_limit=1,
                             fp16=True, bf16=False,  # Pascal / Turing: no bf16
                             report_to=[], remove_unused_columns=False, seed=C.SEED)
    Trainer(model=model, args=args, train_dataset=train_ds, data_collator=collate).train()
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print("adapter saved ->", a.out)

    # held-out label accuracy with the exact inference scorer
    if dev:
        del model
        torch.cuda.empty_cache()
        from verifier import HFVerifier
        v = HFVerifier(base=a.base, adapter=a.out, load_4bit=not a.no_4bit)
        ok, per = 0, {}
        for r in dev:
            labels = C.LABELS_CHAIN if r["target"] in C.LABELS_CHAIN else C.LABELS_ENTAIL
            hit = v.score(r["messages"], labels)["label"] == r["target"]
            ok += hit
            n_hit = per.setdefault(r["target"], [0, 0])
            n_hit[0] += 1
            n_hit[1] += hit
        print(f"held-out accuracy {ok / len(dev):.3f} on {len(dev)} examples")
        for label, (n, h) in sorted(per.items()):  # accuracy alone hides a majority-class verifier
            print(f"  {label}: {h / n:.3f} on {n}")
        print(f"  balanced accuracy {sum(h / n for n, h in per.values()) / len(per):.3f}")


if __name__ == "__main__":
    main()
