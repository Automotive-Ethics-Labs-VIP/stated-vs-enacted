"""Simulator interface and the outcome / observation records both sims write.

An outcome row (one per scenario x action)::

    {scenario_id, action, sim, initial_speed_mps,
     hits: [{group_id, person, t, impact_speed_mps}],
     groups_hit, pedestrians_hit, obstacles_hit, any_collision,
     first_impact_speed_mps, swerve_completed, lost_control,
     final: {x, y, heading_deg, speed_mps}, duration_s,
     trajectory: [[t, x, y, speed], ...]}

An observation row (one per scenario, taken at t0)::

    {scenario_id, sim, ego: {speed_mps, heading_deg, lane_index, lanes_total,
     lane_width_m, left_lane_available, right_lane_available},
     detections: [{id, cls, rel_forward_m, rel_right_m, range_m, bearing_deg, tags}]}

Ranges and bearings are from the ego's centre; bearing is degrees clockwise
from the ego's heading (positive = right).
"""

import math

from .. import ACTIONS

DT = 0.05             # s, CARLA fixed_delta_seconds
MAX_DURATION_S = 8.0
PAST_MARGIN_M = 10.0  # stop once the ego is this far past the farthest actor
TRAJECTORY_EVERY = 2  # keep every 2nd tick (10 Hz) in the trajectory


class Simulator(object):
    name = "base"

    def run(self, scenario, action, capture_dir=None):
        """Run one action from the t0 state; return an outcome row."""
        raise NotImplementedError

    def observe(self, scenario):
        """Return the observation row at t0."""
        raise NotImplementedError

    def close(self):
        pass


def detection(det_id, cls, rel_forward, rel_right, tags):
    return {
        "id": det_id,
        "cls": cls,
        "rel_forward_m": rel_forward,
        "rel_right_m": rel_right,
        "range_m": math.hypot(rel_forward, rel_right),
        "bearing_deg": math.degrees(math.atan2(rel_right, rel_forward)),
        "tags": dict(tags),
    }


def outcome_row(scenario, action, sim, initial_speed, hits, obstacles_hit,
                swerve_done, lost_control, final, duration, trajectory):
    groups_hit = sorted(set(h["group_id"] for h in hits))
    first = min(hits, key=lambda h: h["t"]) if hits else None
    return {
        "scenario_id": scenario.id,
        "action": action,
        "sim": sim,
        "initial_speed_mps": initial_speed,
        "hits": hits,
        "groups_hit": groups_hit,
        "pedestrians_hit": len(hits),
        "obstacles_hit": sorted(obstacles_hit),
        "any_collision": bool(hits or obstacles_hit),
        "first_impact_speed_mps": first["impact_speed_mps"] if first else None,
        "swerve_completed": swerve_done,
        "lost_control": lost_control,
        "final": final,
        "duration_s": duration,
        "trajectory": trajectory,
    }


def run_all(sim, scenarios, capture_dir=None, log=print):
    """Every scenario x action plus one observation per scenario."""
    outcomes, observations = [], []
    for s in scenarios:
        observations.append(sim.observe(s))
        for action in ACTIONS:
            row = sim.run(s, action, capture_dir=capture_dir)
            outcomes.append(row)
            log("{} {:<12} hit={} groups={} v0={:.2f} impact={} swerve={} lost={}".format(
                s.id, action, row["pedestrians_hit"], ",".join(row["groups_hit"]) or "-",
                row["initial_speed_mps"],
                "-" if row["first_impact_speed_mps"] is None
                else "%.2f" % row["first_impact_speed_mps"],
                row["swerve_completed"], row["lost_control"]))
    return outcomes, observations


DETERMINISM_FIELDS = ("pedestrians_hit", "groups_hit", "obstacles_hit", "swerve_completed",
                      "lost_control")


def determinism_report(sim, scenarios, repeats=3):
    """Re-run each scenario x action ``repeats`` times; report the spread."""
    rows = []
    for s in scenarios:
        for action in ACTIONS:
            runs = [sim.run(s, action) for _ in range(repeats)]
            finals_x = [r["final"]["x"] for r in runs]
            finals_y = [r["final"]["y"] for r in runs]
            impacts = [r["first_impact_speed_mps"] for r in runs
                       if r["first_impact_speed_mps"] is not None]
            rows.append({
                "scenario_id": s.id,
                "action": action,
                "repeats": repeats,
                "discrete_identical": all(
                    all(r[k] == runs[0][k] for k in DETERMINISM_FIELDS) for r in runs),
                "final_x_range_m": max(finals_x) - min(finals_x),
                "final_y_range_m": max(finals_y) - min(finals_y),
                "impact_speed_range_mps": (max(impacts) - min(impacts)) if impacts else 0.0,
                "impact_count": len(impacts),
            })
    return rows
