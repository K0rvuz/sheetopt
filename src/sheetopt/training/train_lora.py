"""Experimental LoRA trainer for externally provisioned GPU, never run by CI.

Requires a separately reviewed/licensed, sufficiently large train/eval dataset.
Use Unsloth Qwen3.5 4B bf16 LoRA. This is real gradient training, not RAG.
"""
from __future__ import annotations

# Unsloth has an import-order requirement in GPU training environments.
# ruff: noqa: I001

import argparse
import json
from pathlib import Path


def validate_training_inputs(data_dir: Path, *, min_rules: int = 100) -> tuple[Path, Path]:
    train_path = data_dir / "train.jsonl"
    eval_path = data_dir / "eval.jsonl"
    train = [json.loads(line) for line in train_path.read_text(encoding="utf-8").splitlines()]
    eval_rows = [
        json.loads(line) for line in eval_path.read_text(encoding="utf-8").splitlines()
    ]
    if len(train) < min_rules or len(eval_rows) < 15:
        raise ValueError(
            "Training refused: insufficient independently reviewed facts and held-out "
            "evaluation cases. Seed data alone is not adequate to claim learning."
        )
    train_ids = {row["rule_id"] for row in train}
    eval_ids = {row["rule_id"] for row in eval_rows}
    if train_ids & eval_ids:
        raise ValueError("Rule leakage between train and evaluation data.")
    for row in train + eval_rows:
        if row.get("provenance") != "human_reviewed_fact_summary_not_full_google_documentation":
            raise ValueError("Unreviewed training record detected.")
        if not row.get("source_url", "").startswith(
            ("https://support.google.com/docs/", "https://developers.google.com/workspace/sheets/")
        ):
            raise ValueError("Non-official source in training data.")
        if not row.get("text") or "messages" not in row:
            raise ValueError("Invalid supervised example.")
    return train_path, eval_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit LoRA fine-tuning on a GPU")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/sheets-lora"))
    parser.add_argument("--allow-gpu-training", action="store_true")
    parser.add_argument("--approved-content-license", action="store_true")
    args = parser.parse_args()
    train_path, eval_path = validate_training_inputs(args.data_dir)
    if not args.allow_gpu_training or not args.approved_content_license:
        parser.error("Training requires both explicit GPU and source-license approval.")

    try:
        # Unsloth must patch model kernels before TRL imports transformers.
        from unsloth import FastLanguageModel
        import torch
        from datasets import load_dataset
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit(
            "Install current Unsloth, transformers v5, datasets and TRL "
            "on an appropriately provisioned GPU training system."
        ) from exc
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for this training recipe.")
    vram = torch.cuda.get_device_properties(0).total_memory
    if vram < 10 * 1024**3:
        raise RuntimeError("Qwen3.5 4B BF16 LoRA needs approximately 10 GB VRAM.")
    dataset = load_dataset(
        "json",
        data_files={"train": str(train_path), "validation": str(eval_path)},
    )
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/Qwen3.5-4B",
        max_seq_length=2048,
        load_in_4bit=False,
        load_in_16bit=True,
        full_finetuning=False,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=16, lora_dropout=0, bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407, max_seq_length=2048,
    )
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer,
        train_dataset=dataset["train"], eval_dataset=dataset["validation"],
        args=SFTConfig(
            max_seq_length=2048,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=4,
            num_train_epochs=2,
            eval_strategy="epoch",
            logging_steps=10,
            output_dir=str(args.output_dir),
            optim="adamw_8bit",
            seed=3407,
            dataset_num_proc=1,
        ),
    )
    trainer.train()
    model.save_pretrained(str(args.output_dir / "lora-adapter"))
    tokenizer.save_pretrained(str(args.output_dir / "lora-adapter"))
    print("Adapter trained. This does NOT establish model quality; evaluate on holdout.")


if __name__ == "__main__":
    main()
