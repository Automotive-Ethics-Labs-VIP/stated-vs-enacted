"""Helpers shared by the answer providers."""

import json
import os
import re

from sve import jsonl
from sve.llm import CONDITIONS, load_prompts, parse_answer, prompt_hash

CACHE_DIR = os.path.join(".cache", "answers")


def safe_name(model):
    return re.sub(r"[^A-Za-z0-9._-]", "_", model)


def prompt_rows(prompt_dir, conditions=None):
    """[(condition, prompt row)] in a stable order."""
    prompts = load_prompts(prompt_dir, conditions or CONDITIONS)
    if not prompts:
        raise SystemExit("no prompt files found in {}".format(prompt_dir))
    return [(c, row) for c in CONDITIONS if c in prompts for row in prompts[c]]


def cache_path(model, text, cache_dir=CACHE_DIR):
    return os.path.join(cache_dir, safe_name(model), prompt_hash(model, text) + ".json")


def cache_get(model, text, cache_dir=CACHE_DIR):
    path = cache_path(model, text, cache_dir)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def cache_put(model, text, entry, cache_dir=CACHE_DIR):
    path = cache_path(model, text, cache_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=1, sort_keys=True)


def response_row(prompt, model, raw, meta):
    parsed = parse_answer(raw)
    return {"id": prompt["id"], "model": safe_name(model), "action": parsed["action"],
            "reason": parsed["reason"], "predicted_outcome": parsed["predicted_outcome"],
            "raw": raw, "meta": meta}


def write_responses(responses_dir, model, rows_by_condition):
    for condition, rows in rows_by_condition.items():
        jsonl.write(os.path.join(responses_dir, safe_name(model), condition + ".jsonl"), rows)
