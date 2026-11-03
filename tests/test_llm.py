import json
import os
import sys

import pytest

from providers import claude_cli, manual, mock
from sve import jsonl
from sve.llm import (CONDITIONS, THEORIES, build_prompts, export_prompts, import_responses,
                     load_imported, load_prompts, parse_answer, prompt_hash, validate_row)
from sve.sim import FakeSim

GOOD = {"id": "x", "model": "m", "action": "brake", "reason": "Stops in time.",
        "predicted_outcome": {"pedestrians_hit": 0, "any_collision": False}, "raw": "{}"}


@pytest.fixture
def prompts(smoke):
    sim = FakeSim()
    return build_prompts(smoke, [sim.observe(s) for s in smoke])


def test_one_prompt_per_scenario_condition_theory(smoke):
    sim = FakeSim()
    obs = [sim.observe(s) for s in smoke]
    p = build_prompts(smoke, obs, theories=tuple(THEORIES))
    assert set(p) == set(CONDITIONS)
    assert all(len(rows) == len(smoke) * len(THEORIES) for rows in p.values())
    ids = [r["id"] for rows in p.values() for r in rows]
    assert len(ids) == len(set(ids))


def test_wrapper_is_shared_only_situation_differs(prompts):
    first = dict((c, rows[0]["text"]) for c, rows in prompts.items())
    heads = set(t.split("SITUATION:")[0] for t in first.values())
    tails = set(t.split("Reply with")[1] for t in first.values())
    assert len(heads) == 1 and len(tails) == 1
    assert len(set(first.values())) == 3


def test_theory_line_only_when_asked(smoke):
    sim = FakeSim()
    p = build_prompts(smoke[:1], [sim.observe(smoke[0])], ("enacted",),
                      ("neutral", "utilitarian", "kantian"))["enacted"]
    by = dict((r["theory_prompt"], r["text"]) for r in p)
    assert "utilitarian" not in by["neutral"].lower()
    assert "strict utilitarian" in by["utilitarian"]
    assert "universal law" in by["kantian"]


def test_enacted_needs_an_observation(smoke):
    with pytest.raises(ValueError, match="no observation"):
        build_prompts(smoke, [])


def test_prompt_hash_depends_on_model_and_text():
    assert prompt_hash("a", "t") != prompt_hash("b", "t")
    assert prompt_hash("a", "t") != prompt_hash("a", "u")
    assert prompt_hash("a", "t") == prompt_hash("a", "t")


# ---- validation ----------------------------------------------------------

def test_good_row_passes():
    assert validate_row(GOOD, model="m", known_ids={"x"}) == []
    assert validate_row(dict(GOOD, meta={"k": 1})) == []


@pytest.mark.parametrize("patch, message", [
    ({"action": "accelerate"}, "action"),
    ({"action": None}, "action"),
    ({"reason": " "}, "reason"),
    ({"predicted_outcome": {"pedestrians_hit": -1, "any_collision": False}}, "pedestrians_hit"),
    ({"predicted_outcome": {"pedestrians_hit": True, "any_collision": False}}, "pedestrians_hit"),
    ({"predicted_outcome": {"pedestrians_hit": 1, "any_collision": "yes"}}, "any_collision"),
    ({"predicted_outcome": {"pedestrians_hit": 1}}, "exactly"),
    ({"predicted_outcome": None}, "exactly"),
    ({"model": "other"}, "does not match"),
    ({"id": "nope"}, "unknown id"),
    ({"id": ["x"]}, "unknown id"),
    ({"raw": None}, "raw"),
    ({"meta": "x"}, "meta"),
    ({"extra": 1}, "unknown field"),
])
def test_bad_rows_are_rejected(patch, message):
    problems = validate_row(dict(GOOD, **patch), model="m", known_ids={"x"})
    assert any(message in p for p in problems), problems


def test_missing_field():
    row = dict(GOOD)
    del row["reason"]
    assert validate_row(row) == ["missing reason"]


@pytest.mark.parametrize("raw, action", [
    ('{"action": "brake", "one_sentence_reason": "r", '
     '"predicted_outcome": {"pedestrians_hit": 0, "any_collision": false}}', "brake"),
    ('Sure.\n```json\n{"action": "swerve_left", "one_sentence_reason": "r"}\n```', "swerve_left"),
    ('I choose {"action": "maintain"} because', "maintain"),
    ("no json here", None),
    ("{broken", None),
])
def test_parse_answer(raw, action):
    assert parse_answer(raw)["action"] == action


# ---- import --------------------------------------------------------------

def _write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def test_import_accepts_good_rejects_bad_reports_missing(tmp_path, prompts):
    rows = prompts["enacted"]
    good = [dict(GOOD, id=r["id"]) for r in rows[:2]]
    dup = dict(GOOD, id=rows[2]["id"])
    _write(str(tmp_path / "m" / "enacted.jsonl"),
           good + [dup, dup, dict(GOOD, id="ghost"), "not json"])
    report = import_responses({"enacted": rows}, str(tmp_path), "m")
    assert len(report.accepted) == 2
    assert {r["condition"] for r in report.accepted} == {"enacted"}
    assert report.accepted[0]["scenario_id"] == rows[0]["scenario_id"]
    problems = [p for r in report.rejected for p in r["problems"]]
    assert sum("answered 2 times" in p for p in problems) == 2
    assert any("unknown id" in p for p in problems)
    assert any("invalid JSON" in p for p in problems)
    assert set(report.missing) == set(r["id"] for r in rows[2:])
    assert not report.ok
    assert len(load_imported(str(tmp_path))) == 2
    assert "rejected" in report.summary()


# ---- providers -----------------------------------------------------------

@pytest.fixture
def prompt_dir(tmp_path, smoke):
    sim = FakeSim()
    d = str(tmp_path / "prompts")
    export_prompts(smoke, [sim.observe(s) for s in smoke], d)
    return d


def test_mock_is_deterministic_and_imports_cleanly(tmp_path, prompt_dir):
    r1, r2 = str(tmp_path / "r1"), str(tmp_path / "r2")
    mock.run(prompt_dir, r1)
    mock.run(prompt_dir, r2)
    for c in CONDITIONS:
        assert jsonl.read(os.path.join(r1, "mock", c + ".jsonl")) == jsonl.read(
            os.path.join(r2, "mock", c + ".jsonl"))
    assert import_responses(load_prompts(prompt_dir), r1, "mock").ok


def test_mock_per_scenario_agrees_across_conditions(tmp_path, prompt_dir):
    out = str(tmp_path / "r")
    mock.run(prompt_dir, out, per_scenario=True)
    import_responses(load_prompts(prompt_dir), out, "mock")
    by = {}
    for row in load_imported(out):
        by.setdefault(row["scenario_id"], set()).add(row["action"])
    assert all(len(v) == 1 for v in by.values())


def test_manual_round_trip(tmp_path, prompt_dir):
    out = str(tmp_path / "manual")
    counts = manual.write(prompt_dir, out)
    assert counts == dict((c, 4) for c in CONDITIONS)
    sheet = os.path.join(out, "enacted_answers.txt")
    with open(sheet, encoding="utf-8") as f:
        text = f.read()
    first_id = load_prompts(prompt_dir)["enacted"][0]["id"]
    reply = ('```json\n{"action": "brake", "one_sentence_reason": "Stop.", '
             '"predicted_outcome": {"pedestrians_hit": 0, "any_collision": false}}\n```')
    text = text.replace("=== {} ===\n".format(first_id), "=== {} ===\n{}\n".format(first_id, reply))
    with open(sheet, "w", encoding="utf-8") as f:
        f.write(text)
    responses = str(tmp_path / "responses")
    manual.collect(prompt_dir, out, "chat model", responses)
    report = import_responses(load_prompts(prompt_dir), responses, "chat_model")
    assert len(report.accepted) == 1 and report.accepted[0]["action"] == "brake"
    assert len(report.missing) == 11


FAKE_CLAUDE = r'''
import json, os, sys
prompt = sys.stdin.read()
log = os.environ["FAKE_CLAUDE_LOG"]
with open(log, "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd_files": os.listdir("."),
                        "cwd": os.getcwd()}) + "\n")
answer = {"action": "brake", "one_sentence_reason": "r",
          "predicted_outcome": {"pedestrians_hit": 0, "any_collision": False}}
print(json.dumps({"result": json.dumps(answer), "is_error": False,
                  "modelUsage": {"claude-test-1": {}}, "total_cost_usd": 0.0}))
'''


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    real = claude_cli.command

    def command(claude, model, system_prompt=claude_cli.SYSTEM_PROMPT):
        return [sys.executable, str(script)] + real(claude, model, system_prompt)[1:]

    monkeypatch.setattr(claude_cli, "command", command)
    monkeypatch.chdir(tmp_path)  # cache goes under tmp_path/.cache
    return log


def test_claude_cli_runs_blind_and_caches(tmp_path, prompt_dir, fake_claude):
    responses = str(tmp_path / "responses")
    claude_cli.run(prompt_dir, responses, "sonnet", claude="unused")
    calls = jsonl.read(str(fake_claude))
    assert len(calls) == 12
    for c in calls:
        assert c["cwd_files"] == []  # empty working directory
        assert not os.path.exists(c["cwd"])  # and removed afterwards
        argv = c["argv"]
        assert argv[argv.index("--tools") + 1] == ""
        assert argv[argv.index("--model") + 1] == "sonnet"
        for flag in ("-p", "--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
                     "--no-session-persistence", "--system-prompt"):
            assert flag in argv
    report = import_responses(load_prompts(prompt_dir), responses, "sonnet")
    assert report.ok
    assert report.accepted[0]["meta"]["models_used"] == ["claude-test-1"]
    claude_cli.run(prompt_dir, responses, "sonnet", claude="unused")  # all cached now
    assert len(jsonl.read(str(fake_claude))) == 12
    assert all(r["meta"]["cached"] for r in jsonl.read(os.path.join(responses, "sonnet",
                                                                    "enacted.jsonl")))


def test_claude_cli_asks_above_100_and_refuses_over_max(tmp_path, prompt_dir, fake_claude,
                                                         monkeypatch):
    monkeypatch.setattr(claude_cli, "ASK_ABOVE", 5)
    with pytest.raises(SystemExit, match="cancelled"):
        claude_cli.run(prompt_dir, str(tmp_path / "r"), "sonnet", claude="unused",
                       confirm=lambda _: "n")
    assert not fake_claude.exists()
    with pytest.raises(SystemExit, match="over --max"):
        claude_cli.run(prompt_dir, str(tmp_path / "r"), "sonnet", max_prompts=10,
                       claude="unused")
    claude_cli.run(prompt_dir, str(tmp_path / "r"), "sonnet", claude="unused",
                   confirm=lambda _: "y")
    assert len(jsonl.read(str(fake_claude))) == 12
