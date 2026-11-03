"""The steps the CLI runs, as plain functions.

A run directory (results/<jobid>/ or results/dryrun/run/) holds::

    run.json            how it was produced
    scenarios.jsonl     the expanded specs
    outcomes.jsonl      one row per scenario x action
    observations.jsonl  one row per scenario (t0 snapshot)
    determinism.jsonl   optional repeat check
    media/              optional frames, key frames and GIFs (CARLA --capture)
"""

import json
import os
import time

from . import ACTIONS, jsonl
from .analysis import Analysis
from .analysis import report as report_mod
from .llm import export_prompts, load_imported
from .scenarios import expand_grid, load_grid, scenario_from_dict, scenario_to_dict
from .sim import determinism_report, run_all


def simulate(sim, grid_path, run_dir, capture=False, determinism=0, repeats=3, log=print,
             only=None):
    grid = load_grid(grid_path)
    scenarios = expand_grid(grid)
    if only:
        scenarios = [s for s in scenarios if s.id in only]
    os.makedirs(run_dir, exist_ok=True)
    started = time.time()
    capture_dir = os.path.join(run_dir, "media") if capture else None
    outcomes, observations = run_all(sim, scenarios, capture_dir=capture_dir, log=log)
    jsonl.write(os.path.join(run_dir, "scenarios.jsonl"), [scenario_to_dict(s) for s in scenarios])
    jsonl.write(os.path.join(run_dir, "outcomes.jsonl"), outcomes)
    jsonl.write(os.path.join(run_dir, "observations.jsonl"), observations)
    det = []
    if determinism:
        det = determinism_report(sim, scenarios[:determinism], repeats)
        jsonl.write(os.path.join(run_dir, "determinism.jsonl"), det)
        for row in det:
            log("determinism {scenario_id} {action}: identical={discrete_identical} "
                "dx={final_x_range_m:.3f} dy={final_y_range_m:.3f} "
                "dv={impact_speed_range_mps:.3f}".format(**row))
    meta = {"grid": grid.get("name"), "grid_file": os.path.basename(grid_path), "sim": sim.name,
            "sim_info": getattr(sim, "info", {}), "scenarios": len(scenarios),
            "runs": len(outcomes), "capture": bool(capture), "determinism_checked": len(det),
            "seconds": round(time.time() - started, 1)}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
    return outcomes, observations, det


def load_run(run_dir):
    scenarios = [scenario_from_dict(r) for r in jsonl.read(os.path.join(run_dir, "scenarios.jsonl"))]
    outcomes = jsonl.read(os.path.join(run_dir, "outcomes.jsonl"))
    observations = jsonl.read(os.path.join(run_dir, "observations.jsonl"))
    det_path = os.path.join(run_dir, "determinism.jsonl")
    det = jsonl.read(det_path) if os.path.exists(det_path) else []
    meta_path = os.path.join(run_dir, "run.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    return scenarios, outcomes, observations, det, meta


def export(run_dir, prompt_dir, conditions, theories):
    scenarios, _, observations, _, _ = load_run(run_dir)
    return export_prompts(scenarios, observations, prompt_dir, conditions, theories)


def _key_frames(run_dir, scenarios):
    """{scenario_id: {action: png}} for annotated key frames, if captured."""
    kf_dir = os.path.join(run_dir, "media", "keyframes")
    out = {}
    if not os.path.isdir(kf_dir):
        return out
    for s in scenarios:
        imgs = {}
        for a in ACTIONS:
            p = os.path.join(kf_dir, "{}_{}.png".format(s.id, a))
            if os.path.exists(p):
                imgs[a] = p
        if len(imgs) == len(ACTIONS):
            out[s.id] = imgs
    return out


def _media(run_dir, out_dir):
    media = os.path.join(run_dir, "media")
    if not os.path.isdir(media):
        return []
    return sorted(os.path.relpath(os.path.join(media, f), out_dir).replace(os.sep, "/")
                  for f in os.listdir(media) if f.endswith((".gif", ".mp4")))


def analyze(run_dir, responses_dir, out_dir, score="pedestrians"):
    from .analysis import figures  # matplotlib only needed here

    scenarios, outcomes, _, det, meta = load_run(run_dir)
    answers = load_imported(responses_dir)
    a = Analysis(scenarios, outcomes, answers, score=score)
    tables = a.write_csvs(os.path.join(out_dir, "tables"))
    by_scenario = {}
    for o in outcomes:
        by_scenario.setdefault(o["scenario_id"], []).append(o)
    fig_dir = os.path.join(out_dir, "figures")
    made = figures.make_all(a, by_scenario, fig_dir, key_frames=_key_frames(run_dir, scenarios))
    rel = dict((k, os.path.relpath(v, out_dir).replace(os.sep, "/")) for k, v in made.items())
    rep = build_report(a, meta, det, tables, rel, _media(run_dir, out_dir), score)
    return rep.write(out_dir), a


def build_report(a, meta, det, tables, figs, media, score):
    models = sorted(set(r["model"] for r in a.rows))
    r = report_mod.Report("Stated vs enacted: pilot report")
    if meta.get("sim") == "fake" or models == ["mock"]:
        r.p("**Pipeline test, not a result.** This report was made with "
            + ("FakeSim (a kinematic model, not CARLA)" if meta.get("sim") == "fake" else
               "CARLA") + (" and mock answers chosen by hash" if "mock" in models else "")
            + ". It shows the loop works; its numbers say nothing about the research question.")
    r.h(2, "Research question")
    r.p("Do text-based moral judgments predict behavior in simulated driving? For the same "
        "dilemma, an LLM chooses an action from a text description (STATED) and from a "
        "structured readout of the simulation at the decision point (ENACTED). Both are "
        "scored against the measured outcome of every action.")
    r.h(2, "Method")
    r.ol([
        "A grid of dilemmas varies speed, distance to the people and group sizes; people stand "
        "in the ego's lane and both neighbouring lanes.",
        "The simulator ({}) runs all 4 actions (maintain, brake, swerve_left, swerve_right) "
        "from the same t0 state and records who is hit and how fast.".format(
            meta.get("sim", "?")),
        "Prompts: STATED from templates over the spec (abstract or detailed), ENACTED from the "
        "simulator's t0 snapshot through a separate renderer; same wrapper and action menu.",
        "Models answer blind (fresh headless session, no tools or files); answers are "
        "validated and imported, never executed.",
        "Each choice is scored by looking up its measured outcome (score: `{}`).".format(score),
    ])
    r.h(2, "Run")
    r.ul([
        "grid `{}`: {} scenarios x 4 actions = {} simulated runs".format(
            meta.get("grid", "?"), len(a.scenarios), meta.get("runs", "?")),
        "answers: {} from model(s) {}".format(len(a.rows), ", ".join(models) or "none"),
        "determinism check: " + (_det_summary(det) if det else "not run"),
    ])
    r.h(2, "Key numbers")
    if a.rows:
        r.h(3, "Agreement between conditions")
        r.table(tables["agreement.csv"])
        r.img(figs.get("agreement_neutral", ""), "Share of scenarios where two conditions chose "
              "the same action (neutral prompt).")
        r.h(3, "Regret")
        r.p("Regret = pedestrians hit by the chosen action minus the fewest any action hits "
            "(in the score's primary unit). Optimal = chose one of the best actions.")
        r.table(tables["regret.csv"])
        r.img(figs.get("optimal_neutral", ""), "How often each condition chose a best action.")
        r.h(3, "Calibration of predicted outcomes")
        r.table(tables["calibration.csv"])
    else:
        r.p("No answers imported yet: only the simulated outcomes are shown.")
    r.h(3, "Does the best action change across the grid?")
    r.img(figs["heatmap"], "Best action for each speed x distance cell, by measured outcome.")
    r.table(tables["best_action_grid.csv"])
    r.h(2, "Scenarios")
    for sid, s in a.scenarios.items():
        r.h(3, sid)
        for k in sorted(figs):
            if k.startswith("contact_{}_".format(sid)):
                r.img(figs[k], "One panel per action with its measured outcome; outlines show "
                      "the action each condition chose; star = best action.")
        r.img(figs["schematic_" + sid], "Layout from the spec with each action's measured path.")
    if media:
        r.h(2, "Clips")
        r.p("Rendered in CARLA. Attributes are metadata labels; the walker models are generic.")
        r.ul(["[{}]({})".format(m.split("/")[-1], m) for m in media])
    r.h(2, "Simulated outcomes")
    r.table(tables["outcomes.csv"])
    r.h(2, "Limitations")
    r.ul(report_mod.LIMITATIONS)
    return r


def _det_summary(det):
    same = sum(1 for d in det if d["discrete_identical"])
    dx = max(d["final_x_range_m"] for d in det)
    dv = max(d["impact_speed_range_mps"] for d in det)
    return ("{}/{} (scenario, action) pairs gave identical hits over {} repeats; largest spread "
            "in final position {:.3f} m, in impact speed {:.3f} m/s").format(
                same, len(det), det[0]["repeats"], dx, dv)
