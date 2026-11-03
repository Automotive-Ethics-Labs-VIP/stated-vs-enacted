import os
import re

import pytest

from sve import ACTIONS
from sve.analysis import Analysis, best_actions, cohen_kappa
from sve.cli import main

from conftest import make_scenario


def outcome(sid, action, hits, impact=None, groups=("ahead",)):
    return {"scenario_id": sid, "action": action, "pedestrians_hit": hits,
            "hits": [{"group_id": groups[0], "person": i, "t": 1.0,
                      "impact_speed_mps": impact} for i in range(hits)],
            "groups_hit": list(groups) if hits else [], "first_impact_speed_mps": impact,
            "obstacles_hit": [], "any_collision": hits > 0, "initial_speed_mps": 10.0,
            "swerve_completed": None, "lost_control": False,
            "final": {"x": 0, "y": 0, "heading_deg": 0, "speed_mps": 0}, "duration_s": 1.0,
            "trajectory": [[0, 0, 0, 10]]}


def answer(sid, condition, action, pred_hits=0, pred_coll=False, model="m", theory="neutral"):
    return {"id": "{}__{}__{}".format(sid, condition, theory), "model": model,
            "action": action, "reason": "r", "raw": "",
            "predicted_outcome": {"pedestrians_hit": pred_hits, "any_collision": pred_coll},
            "condition": condition, "scenario_id": sid, "theory_prompt": theory}


@pytest.fixture
def two():
    s1 = make_scenario(speed=10, distance=10, id="s1")
    s2 = make_scenario(speed=14, distance=10, id="s2")
    outs = [
        outcome("s1", "maintain", 2, 10.0), outcome("s1", "brake", 0),
        outcome("s1", "swerve_left", 1, 9.0, ("left",)), outcome("s1", "swerve_right", 0),
        outcome("s2", "maintain", 2, 14.0), outcome("s2", "brake", 2, 6.0),
        outcome("s2", "swerve_left", 1, 13.0, ("left",)),
        outcome("s2", "swerve_right", 1, 13.2, ("left",)),
    ]
    return [s1, s2], outs


def test_best_actions_ties_and_tolerance():
    assert best_actions({"a": (0, 0.0), "b": (0, 0.0), "c": (1, 0.0)}) == ["a", "b"]
    assert best_actions({"a": (1, 9.0), "b": (1, 9.4), "c": (1, 11.0)}) == ["a", "b"]
    assert best_actions({"a": (2,), "b": (1,)}) == ["b"]


def test_best_regret_and_optimal(two):
    scenarios, outs = two
    answers = [answer("s1", "enacted", "swerve_left", 1, True),
               answer("s2", "enacted", "brake", 2, True),
               answer("s2", "stated-abstract", "swerve_right", 0, False)]
    a = Analysis(scenarios, outs, answers)
    assert a.best == {"s1": ["brake", "swerve_right"], "s2": ["swerve_left", "swerve_right"]}
    by = dict(((r["scenario_id"], r["condition"]), r) for r in a.rows)
    assert by[("s1", "enacted")]["regret"] == 1 and not by[("s1", "enacted")]["optimal"]
    assert by[("s2", "enacted")]["regret"] == 1
    assert by[("s2", "stated-abstract")]["regret"] == 0
    assert by[("s2", "stated-abstract")]["optimal"]


def test_agreement_and_kappa(two):
    scenarios, outs = two
    answers = [answer("s1", "stated-abstract", "brake"), answer("s1", "enacted", "brake"),
               answer("s2", "stated-abstract", "brake"), answer("s2", "enacted", "maintain")]
    rows = Analysis(scenarios, outs, answers).agreement_table()
    assert len(rows) == 1
    assert rows[0]["pair"] == "stated-abstract vs enacted"
    assert rows[0]["n"] == 2 and rows[0]["agreement"] == 0.5


def test_cohen_kappa_known_values():
    assert cohen_kappa([("brake", "brake"), ("maintain", "maintain")]) == pytest.approx(1.0)
    # all one category on both sides: chance agreement is 1, kappa undefined
    assert cohen_kappa([("brake", "brake"), ("brake", "brake")]) is None
    # observed 0.5, expected 0.5 -> 0
    pairs = [("brake", "brake"), ("brake", "maintain"), ("maintain", "brake"),
             ("maintain", "maintain")]
    assert cohen_kappa(pairs) == pytest.approx(0.0)
    assert cohen_kappa([]) is None


def test_calibration(two):
    scenarios, outs = two
    answers = [answer("s1", "enacted", "maintain", 2, True),
               answer("s2", "enacted", "brake", 0, False)]
    row = Analysis(scenarios, outs, answers).calibration_table()[0]
    assert row["hits_exact_rate"] == 0.5
    assert row["hits_mae"] == 1.0
    assert row["hits_mean_signed_error"] == -1.0
    assert row["collision_accuracy"] == 0.5


def test_best_action_grid_reports_changes(two):
    scenarios, outs = two
    rows = Analysis(scenarios, outs, []).best_action_table()
    assert {r["best_actions"] for r in rows} == {"brake|swerve_right", "swerve_left|swerve_right"}
    assert all(r["distinct_best_in_grid"] == 2 for r in rows)


def test_weighted_score_prefers_hitting_an_adult_over_a_child(two):
    scenarios, outs = two
    a = Analysis(scenarios, outs, [], score="weighted_vulnerable")
    # s2: left swerves hit the child group (weight 2) vs maintain hits 2 adults (2.0)
    assert a.scores["s2"]["swerve_left"][0] == 2.0
    assert a.scores["s2"]["maintain"][0] == 2.0


def test_missing_outcomes_are_an_error(two):
    scenarios, outs = two
    with pytest.raises(ValueError, match="outcomes missing"):
        Analysis(scenarios, outs[:-1], [])


def test_dryrun_end_to_end(tmp_path):
    out = str(tmp_path / "dry")
    assert main(["dryrun", "--out", out]) == 0
    for name in ("report.md", "report.html", "tables/answers.csv", "tables/agreement.csv",
                 "figures/best_action_heatmap.png", "figures/agreement_neutral.png"):
        assert os.path.exists(os.path.join(out, name)), name
    with open(os.path.join(out, "report.md"), encoding="utf-8") as f:
        md = f.read()
    assert "Pipeline test, not a result" in md
    assert "Limitations" in md
    with open(os.path.join(out, "report.html"), encoding="utf-8") as f:
        html = f.read()
    for line in md.splitlines():
        if line.startswith("!["):
            src = re.match(r"!\[.*\]\(([^()]+)\)$", line).group(1)
            assert os.path.exists(os.path.join(out, src)), src
            assert 'src="{}"'.format(src) in html


def test_cli_import_fails_on_incomplete(tmp_path, capsys):
    out = str(tmp_path / "dry")
    main(["dryrun", "--out", out])
    os.remove(os.path.join(out, "responses", "mock", "enacted.jsonl"))
    rc = main(["import-responses", "--model", "mock", "--prompts", os.path.join(out, "prompts"),
               "--responses", os.path.join(out, "responses")])
    assert rc == 1
    assert "4 missing" in capsys.readouterr().out
    assert ACTIONS  # sanity: package import
