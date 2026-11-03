"""Deterministic dummy answers. Never sees outcomes; picks from a hash.

    python -m providers.mock --prompts prompts --responses responses [--per-scenario]

``--per-scenario`` hashes only the scenario and theory, so every condition
gives the same answer (100% agreement); the default hashes the prompt id.
"""

import argparse
import hashlib
import json

from sve import ACTIONS

from .common import prompt_rows, response_row, write_responses

MODEL = "mock"


def answer(prompt, per_scenario=False):
    key = (prompt["scenario_id"] + "|" + prompt["theory_prompt"]) if per_scenario else prompt["id"]
    h = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
    hit = (h // 4) % 3
    return json.dumps({
        "action": ACTIONS[h % 4],
        "one_sentence_reason": "Mock answer chosen by hash.",
        "predicted_outcome": {"pedestrians_hit": hit, "any_collision": hit > 0},
    })


def run(prompt_dir, responses_dir, per_scenario=False, model=MODEL):
    out = {}
    for condition, prompt in prompt_rows(prompt_dir):
        out.setdefault(condition, []).append(
            response_row(prompt, model, answer(prompt, per_scenario), {"provider": "mock"}))
    write_responses(responses_dir, model, out)
    return sum(len(v) for v in out.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompts", default="prompts")
    ap.add_argument("--responses", default="responses")
    ap.add_argument("--per-scenario", action="store_true")
    args = ap.parse_args(argv)
    n = run(args.prompts, args.responses, args.per_scenario)
    print("mock: wrote {} answers to {}/{}".format(n, args.responses, MODEL))


if __name__ == "__main__":
    main()
