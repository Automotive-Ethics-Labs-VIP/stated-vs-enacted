"""Answer prompts with headless Claude Code (`claude -p`), blind.

    python -m providers.claude_cli --model sonnet [--conditions enacted] [--max 400] [--yes]

Each prompt runs in a fresh, EMPTY temporary directory with:

- ``--tools ""``                   no tools at all, so no file or web access
- ``--safe-mode``                  no CLAUDE.md, memory, skills, plugins, hooks or MCP
- ``--strict-mcp-config``          no MCP servers
- ``--disable-slash-commands``     no skills or commands
- ``--no-session-persistence``     nothing saved; no conversation carries over
- ``--system-prompt``              a short neutral system prompt instead of the coding-agent one

It uses your existing Claude Code login and consumes your Claude usage. It
shows how many prompts need a model call (cached ones don't) and asks before
running more than 100; it refuses more than --max (default 400) per run.
Answers are cached by (model, prompt hash) in .cache/answers/.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from .common import cache_get, cache_put, prompt_rows, response_row, safe_name, write_responses

SYSTEM_PROMPT = "You are a helpful assistant. Answer the user's message directly."
ASK_ABOVE = 100
DEFAULT_MAX = 400


def find_claude():
    path = shutil.which("claude")
    if path:
        return path
    # The VS Code extension ships its own binary; take the newest.
    ext = os.path.join(os.path.expanduser("~"), ".vscode", "extensions")
    found = []
    if os.path.isdir(ext):
        for name in os.listdir(ext):
            if name.startswith("anthropic.claude-code"):
                exe = os.path.join(ext, name, "resources", "native-binary",
                                   "claude.exe" if os.name == "nt" else "claude")
                if os.path.exists(exe):
                    found.append((os.path.getmtime(exe), exe))
    if found:
        return max(found)[1]
    raise SystemExit("claude CLI not found; pass --claude PATH")


def command(claude, model, system_prompt=SYSTEM_PROMPT):
    return [claude, "-p", "--model", model, "--output-format", "json",
            "--tools", "", "--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence", "--system-prompt", system_prompt]


def ask_one(claude, model, text, timeout_s, system_prompt=SYSTEM_PROMPT):
    """Run one prompt blind; return a cache entry {raw, meta}."""
    workdir = tempfile.mkdtemp(prefix="sve-answer-")
    try:
        start = time.time()
        proc = subprocess.run(command(claude, model, system_prompt), input=text, cwd=workdir,
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout_s)
        meta = {"provider": "claude_cli", "model_arg": model, "system_prompt": system_prompt,
                "returncode": proc.returncode, "seconds": round(time.time() - start, 2)}
        try:
            out = json.loads(proc.stdout)
        except ValueError:
            meta["stderr"] = proc.stderr[-2000:]
            return {"raw": proc.stdout, "meta": meta, "error": True}
        meta["models_used"] = sorted((out.get("modelUsage") or {}).keys())
        meta["is_error"] = bool(out.get("is_error"))
        meta["cost_usd"] = out.get("total_cost_usd")
        return {"raw": out.get("result") or "", "meta": meta, "error": meta["is_error"]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run(prompt_dir, responses_dir, model, conditions=None, max_prompts=DEFAULT_MAX,
        assume_yes=False, claude=None, workers=1, timeout_s=180, confirm=input):
    rows = prompt_rows(prompt_dir, conditions)
    todo = [(c, p) for c, p in rows if cache_get(model, p["text"]) is None]
    print("claude_cli: {} prompts, {} cached, {} need a model call (model {})".format(
        len(rows), len(rows) - len(todo), len(todo), model))
    if len(todo) > max_prompts:
        raise SystemExit("refusing: {} calls is over --max {}".format(len(todo), max_prompts))
    if len(todo) > ASK_ABOVE and not assume_yes:
        reply = confirm("This uses your Claude usage for {} calls. Continue? [y/N] ".format(
            len(todo)))
        if reply.strip().lower() not in ("y", "yes"):
            raise SystemExit("cancelled")
    if todo:
        claude = claude or find_claude()

        def work(item):
            _, p = item
            entry = ask_one(claude, model, p["text"], timeout_s)
            if not entry.get("error"):
                cache_put(model, p["text"], entry)
            return p["id"], entry

        failures = {}
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for n, (pid, entry) in enumerate(pool.map(work, todo), 1):
                status = "error" if entry.get("error") else "ok"
                if entry.get("error"):
                    failures[pid] = entry
                print("  [{}/{}] {} {}".format(n, len(todo), pid, status), flush=True)
    else:
        failures = {}
    called = set(p["id"] for _, p in todo)
    out = {}
    for condition, p in rows:
        entry = failures.get(p["id"]) or cache_get(model, p["text"])
        if entry is None:
            continue
        meta = dict(entry["meta"], cached=p["id"] not in called)
        out.setdefault(condition, []).append(response_row(p, model, entry["raw"], meta))
    write_responses(responses_dir, model, out)
    print("claude_cli: wrote {} rows to {}/{} ({} errors)".format(
        sum(len(v) for v in out.values()), responses_dir, safe_name(model), len(failures)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, help="e.g. sonnet, opus, haiku or a full model id")
    ap.add_argument("--prompts", default="prompts")
    ap.add_argument("--responses", default="responses")
    ap.add_argument("--conditions", help="comma-separated; default all")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX, dest="max_prompts")
    ap.add_argument("--yes", action="store_true", help="don't ask before >100 calls")
    ap.add_argument("--claude", help="path to the claude binary")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args(argv)
    conditions = args.conditions.split(",") if args.conditions else None
    run(args.prompts, args.responses, args.model, conditions, args.max_prompts, args.yes,
        args.claude, args.workers, args.timeout)
    print("next: python -m sve import-responses --model {}".format(safe_name(args.model)))


if __name__ == "__main__":
    sys.exit(main())
