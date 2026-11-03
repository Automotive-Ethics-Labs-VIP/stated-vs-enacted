"""Validate and import answers from responses/<model>/<condition>.jsonl.

A response row is::

    {"id", "model", "action", "reason", "predicted_outcome", "raw"}

with ``predicted_outcome`` = ``{"pedestrians_hit": int >= 0, "any_collision": bool}``.
Providers may add ``meta`` (a dict). Anything else is rejected, as is a row
for an unknown id, an id answered twice (every copy), or a model name that
doesn't match the directory. Unanswered ids are reported as missing.
"""

import json
import os
import re

from .. import ACTIONS, jsonl
from .prompts import CONDITIONS

REQUIRED = ("id", "model", "action", "reason", "predicted_outcome", "raw")
OPTIONAL = ("meta",)


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def validate_row(row, model=None, known_ids=None):
    """List of problems with one response row (empty if valid)."""
    if not isinstance(row, dict):
        return ["row is not a JSON object"]
    problems = []
    for key in REQUIRED:
        if key not in row:
            problems.append("missing {}".format(key))
    unknown = sorted(set(row) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        problems.append("unknown field(s) {}".format(", ".join(unknown)))
    if problems:
        return problems
    if not isinstance(row["id"], str) or (known_ids is not None and row["id"] not in known_ids):
        problems.append("unknown id {!r}".format(row["id"]))
    if not isinstance(row["model"], str) or not row["model"]:
        problems.append("model must be a non-empty string")
    elif model is not None and row["model"] != model:
        problems.append("model {!r} does not match directory {!r}".format(row["model"], model))
    if row["action"] not in ACTIONS:
        problems.append("action {!r} is not one of {}".format(row["action"], ", ".join(ACTIONS)))
    if not isinstance(row["reason"], str) or not row["reason"].strip():
        problems.append("reason must be a non-empty string")
    po = row["predicted_outcome"]
    if not isinstance(po, dict) or set(po) != {"pedestrians_hit", "any_collision"}:
        problems.append("predicted_outcome must have exactly pedestrians_hit and any_collision")
    else:
        if not _is_int(po["pedestrians_hit"]) or po["pedestrians_hit"] < 0:
            problems.append("predicted_outcome.pedestrians_hit must be an integer >= 0")
        if not isinstance(po["any_collision"], bool):
            problems.append("predicted_outcome.any_collision must be true or false")
    if not isinstance(row["raw"], str):
        problems.append("raw must be a string")
    if "meta" in row and not isinstance(row["meta"], dict):
        problems.append("meta must be an object")
    return problems


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_answer(raw_text):
    """Pull {action, reason, predicted_outcome} out of a model's reply.

    Returns a dict with those keys; values the reply didn't supply are None
    so that import rejects the row rather than guessing.
    """
    candidates = [m.group(1) for m in _FENCE.finditer(raw_text)] + [raw_text]
    data = None
    for c in candidates:
        start, end = c.find("{"), c.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            data = json.loads(c[start:end + 1])
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        return {"action": None, "reason": None, "predicted_outcome": None}
    reason = data.get("one_sentence_reason", data.get("reason"))
    return {"action": data.get("action"), "reason": reason,
            "predicted_outcome": data.get("predicted_outcome")}


class ImportReport(object):
    def __init__(self, model):
        self.model = model
        self.accepted = []
        self.rejected = []   # {condition, line, id, problems}
        self.missing = []    # prompt ids with no valid answer

    @property
    def ok(self):
        return not self.rejected and not self.missing

    def summary(self):
        lines = ["model {}: {} accepted, {} rejected, {} missing".format(
            self.model, len(self.accepted), len(self.rejected), len(self.missing))]
        for r in self.rejected[:20]:
            lines.append("  rejected {}:{} id={}: {}".format(
                r["condition"], r["line"], r["id"], "; ".join(r["problems"])))
        if len(self.rejected) > 20:
            lines.append("  ... {} more rejected".format(len(self.rejected) - 20))
        for pid in self.missing[:20]:
            lines.append("  missing {}".format(pid))
        if len(self.missing) > 20:
            lines.append("  ... {} more missing".format(len(self.missing) - 20))
        return "\n".join(lines)


def import_responses(prompts, responses_dir, model):
    """Validate responses/<model>/<condition>.jsonl against the prompts.

    ``prompts`` is {condition: [prompt rows]}. Accepted rows are written to
    responses/<model>/imported.jsonl joined with their prompt's metadata.
    """
    report = ImportReport(model)
    model_dir = os.path.join(responses_dir, model)
    for condition in CONDITIONS:
        if condition not in prompts:
            continue
        by_id = dict((p["id"], p) for p in prompts[condition])
        path = os.path.join(model_dir, condition + ".jsonl")
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    try:
                        rows.append((n, json.loads(line)))
                    except ValueError as e:
                        report.rejected.append({"condition": condition, "line": n, "id": None,
                                                "problems": ["invalid JSON: {}".format(e)]})
        counts = {}
        def row_id(row):
            rid = row.get("id") if isinstance(row, dict) else None
            return rid if isinstance(rid, str) else None

        for _, row in rows:
            counts[row_id(row)] = counts.get(row_id(row), 0) + 1
        answered = set()
        for n, row in rows:
            problems = validate_row(row, model=model, known_ids=by_id)
            rid = row_id(row)
            if not problems and counts.get(rid, 0) > 1:
                problems = ["id answered {} times".format(counts[rid])]
            if problems:
                report.rejected.append({"condition": condition, "line": n, "id": rid,
                                        "problems": problems})
                continue
            p = by_id[rid]
            answered.add(rid)
            report.accepted.append(dict(row, condition=condition, scenario_id=p["scenario_id"],
                                        theory_prompt=p["theory_prompt"]))
        report.missing.extend(pid for pid in by_id if pid not in answered)
    jsonl.write(os.path.join(model_dir, "imported.jsonl"), report.accepted)
    return report


def load_imported(responses_dir):
    """All accepted answers across models: [rows]."""
    rows = []
    if not os.path.isdir(responses_dir):
        return rows
    for model in sorted(os.listdir(responses_dir)):
        path = os.path.join(responses_dir, model, "imported.jsonl")
        if os.path.exists(path):
            rows.extend(jsonl.read(path))
    return rows
