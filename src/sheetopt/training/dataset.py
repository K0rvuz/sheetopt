"""Build a traceable SFT seed from reviewed facts; no private workbook data.

WARNING: preparing examples changes NO model weights. Seed size is too small
for a credible domain fine-tune. Train only with an expanded, licensed,
human-reviewed corpus and independent held-out evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from sheetopt.knowledge.rules import knowledge_rules

_SYSTEM = (
    "Você é um analista técnico de Google Sheets. Use regras verificadas, "
    "explicite limitações e não invente documentação ou ganho de desempenho."
)


def prepare_dataset(out_dir: Path) -> dict[str, Any]:
    """Versioned deterministic split by rule ID, not by paraphrase."""
    out_dir.mkdir(parents=True, exist_ok=True)
    train: list[dict[str, Any]] = []
    heldout: list[dict[str, Any]] = []
    for rule in knowledge_rules():
        question = "Qual regra técnica verificável se aplica a " + ", ".join(
            rule["tags"][:3]
        ) + " e o que precisamos conferir antes de mudar uma fórmula?"
        answer = (
            f"{rule['claim']} Confirme: {', '.join(rule['requires'])}. "
            f"Referência: {rule['source_id']} ({rule['url']})."
        )
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        # Explicit text column for SFTTrainer, also preserve messages/provenance.
        text = "\n".join(
            f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>"
            for m in messages
        )
        record = {
            "text": text, "messages": messages, "rule_id": rule["id"],
            "source_id": rule["source_id"], "source_url": rule["url"],
            "provenance": "human_reviewed_fact_summary_not_full_google_documentation",
        }
        bucket = int(hashlib.sha256(rule["id"].encode()).hexdigest()[:8], 16) % 5
        (heldout if bucket == 0 else train).append(record)

    for name, records in (("train", train), ("eval", heldout)):
        with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as writer:
            for record in records:
                writer.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = {
        "schema_version": 1, "source": "curated_official_google_factual_summaries",
        "training_executed": False, "weights_modified": False,
        "scope": "seed_not_full_documentation",
        "train_count": len(train), "eval_count": len(heldout),
        "split": "sha256(rule_id)%5", "private_workbooks_included": False,
        "sufficient_for_domain_finetune": False,
        "needs_before_training": [
            "expand human-reviewed licensed documentation corpus",
            "document source terms and dataset provenance",
            "add real formula-case holdout evaluation without private data",
            "train in sufficient GPU environment",
            "measure baseline vs fine-tuned performance before release",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare reviewed Google Sheets SFT seed")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/sheets-sft"))
    args = parser.parse_args()
    print(json.dumps(prepare_dataset(args.output_dir), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
