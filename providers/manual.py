"""Answer prompts by hand in a chat window.

    python -m providers.manual write   --prompts prompts --out manual
    python -m providers.manual collect --out manual --model <name> --responses responses

``write`` makes, per condition, a prompt sheet (manual/<condition>_prompts.md)
and an answer sheet (manual/<condition>_answers.txt) with one block per id.
Paste each prompt into a NEW chat (no project, no memory, nothing else in
it), and paste the whole reply under its id in the answer sheet. ``collect``
parses the sheets into responses/<model>/<condition>.jsonl for import.
"""

import argparse
import os
import re

from .common import prompt_rows, response_row, safe_name, write_responses

HEADER = "=== {} ==="
_BLOCK = re.compile(r"^=== (.+?) ===\s*$", re.M)

INSTRUCTIONS = """# Prompts: {condition}

Rules, so answers stay blind:
- Open a **new chat for every prompt**. No project, no custom instructions, memory off if you can.
- Paste exactly one prompt (the text inside the box), nothing else.
- Don't paste prompts from other conditions into the same chat.
- Copy the whole reply into `{answers}` under the matching `=== id ===` line.

"""


def write(prompt_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    by_condition = {}
    for condition, prompt in prompt_rows(prompt_dir):
        by_condition.setdefault(condition, []).append(prompt)
    for condition, prompts in by_condition.items():
        answers = condition + "_answers.txt"
        with open(os.path.join(out_dir, condition + "_prompts.md"), "w", encoding="utf-8") as f:
            f.write(INSTRUCTIONS.format(condition=condition, answers=answers))
            for p in prompts:
                f.write("## {}\n\n````\n{}\n````\n\n".format(p["id"], p["text"]))
        with open(os.path.join(out_dir, answers), "w", encoding="utf-8") as f:
            for p in prompts:
                f.write(HEADER.format(p["id"]) + "\n\n\n")
    return dict((c, len(p)) for c, p in by_condition.items())


def parse_sheet(text):
    """{id: reply} from an answer sheet; empty replies are dropped."""
    marks = list(_BLOCK.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        reply = text[m.end():end].strip()
        if reply:
            out[m.group(1).strip()] = reply
    return out


def collect(prompt_dir, out_dir, model, responses_dir):
    rows = {}
    for condition, prompt in prompt_rows(prompt_dir):
        path = os.path.join(out_dir, condition + "_answers.txt")
        if not os.path.exists(path):
            continue
        if condition not in rows:
            with open(path, encoding="utf-8") as f:
                rows[condition] = {"_sheet": parse_sheet(f.read()), "rows": []}
        reply = rows[condition]["_sheet"].get(prompt["id"])
        if reply is not None:
            rows[condition]["rows"].append(
                response_row(prompt, model, reply, {"provider": "manual"}))
    out = dict((c, v["rows"]) for c, v in rows.items())
    write_responses(responses_dir, model, out)
    return dict((c, len(v)) for c, v in out.items())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--prompts", default="prompts")
    w.add_argument("--out", default="manual")
    c = sub.add_parser("collect")
    c.add_argument("--prompts", default="prompts")
    c.add_argument("--out", default="manual")
    c.add_argument("--model", required=True, help="name of the chat model you used")
    c.add_argument("--responses", default="responses")
    args = ap.parse_args(argv)
    if args.cmd == "write":
        counts = write(args.prompts, args.out)
        print("manual: wrote sheets to {}: {}".format(args.out, counts))
    else:
        counts = collect(args.prompts, args.out, args.model, args.responses)
        print("manual: collected {} into {}/{}".format(counts, args.responses,
                                                       safe_name(args.model)))
        print("next: python -m sve import-responses --model {}".format(safe_name(args.model)))


if __name__ == "__main__":
    main()
