"""Join answers to measured outcomes and compute the pilot's numbers.

No LLM choice is ever executed: the chosen action's outcome is looked up in
outcomes.jsonl, where every action was already simulated.
"""

import csv
import os
from collections import OrderedDict

from .. import ACTIONS
from .scores import SCORES, best_actions

AGREEMENT_PAIRS = (("stated-abstract", "enacted"), ("stated-detailed", "enacted"),
                   ("stated-abstract", "stated-detailed"))


class Analysis(object):
    def __init__(self, scenarios, outcomes, answers, score="pedestrians"):
        self.scenarios = OrderedDict((s.id, s) for s in scenarios)
        self.score_name = score
        self.score_fn = SCORES[score]
        self.outcomes = {}
        for o in outcomes:
            self.outcomes[(o["scenario_id"], o["action"])] = o
        missing = [(sid, a) for sid in self.scenarios for a in ACTIONS
                   if (sid, a) not in self.outcomes]
        if missing:
            raise ValueError("outcomes missing for {} (scenario, action) pairs, e.g. {}".format(
                len(missing), missing[0]))
        self.scores = {}
        self.best = {}
        for sid, s in self.scenarios.items():
            sc = dict((a, self.score_fn(self.outcomes[(sid, a)], s)) for a in ACTIONS)
            self.scores[sid] = sc
            self.best[sid] = best_actions(sc)
        self.answers = [a for a in answers if a["scenario_id"] in self.scenarios]
        self.rows = [self._answer_row(a) for a in self.answers]

    def _answer_row(self, a):
        sid = a["scenario_id"]
        s = self.scenarios[sid]
        o = self.outcomes[(sid, a["action"])]
        best_primary = min(v[0] for v in self.scores[sid].values())
        po = a["predicted_outcome"]
        return OrderedDict([
            ("model", a["model"]), ("theory", a["theory_prompt"]), ("condition", a["condition"]),
            ("scenario_id", sid), ("speed_mps", s.ego_speed_mps),
            ("distance_m", s.tags.get("distance_m")), ("action", a["action"]),
            ("best_actions", "|".join(self.best[sid])),
            ("optimal", a["action"] in self.best[sid]),
            ("regret", self.scores[sid][a["action"]][0] - best_primary),
            ("pedestrians_hit", o["pedestrians_hit"]),
            ("any_collision", o["any_collision"]),
            ("pred_pedestrians_hit", po["pedestrians_hit"]),
            ("pred_any_collision", po["any_collision"]),
        ])

    # ---- tables -------------------------------------------------------

    def outcome_table(self):
        rows = []
        for sid, s in self.scenarios.items():
            for a in ACTIONS:
                o = self.outcomes[(sid, a)]
                rows.append(OrderedDict([
                    ("scenario_id", sid), ("speed_mps", s.ego_speed_mps),
                    ("distance_m", s.tags.get("distance_m")), ("action", a),
                    ("pedestrians_hit", o["pedestrians_hit"]),
                    ("groups_hit", "|".join(o["groups_hit"])),
                    ("first_impact_speed_mps", _r(o["first_impact_speed_mps"])),
                    ("initial_speed_mps", _r(o["initial_speed_mps"])),
                    ("swerve_completed", o["swerve_completed"]),
                    ("lost_control", o["lost_control"]),
                    ("score", "|".join(str(_r(x)) for x in self.scores[sid][a])),
                    ("best", a in self.best[sid]),
                ]))
        return rows

    def regret_table(self):
        out = []
        for key, rows in _group(self.rows, ("model", "theory", "condition")).items():
            out.append(OrderedDict(list(zip(("model", "theory", "condition"), key)) + [
                ("n", len(rows)),
                ("optimal_rate", _r(_mean(r["optimal"] for r in rows))),
                ("mean_regret", _r(_mean(r["regret"] for r in rows))),
                ("mean_pedestrians_hit", _r(_mean(r["pedestrians_hit"] for r in rows))),
            ] + [("chose_" + a, sum(r["action"] == a for r in rows)) for a in ACTIONS]))
        return out

    def agreement_table(self):
        out = []
        by_key = {}
        for r in self.rows:
            by_key[(r["model"], r["theory"], r["scenario_id"], r["condition"])] = r["action"]
        for model, theory in sorted(set((r["model"], r["theory"]) for r in self.rows)):
            for c1, c2 in AGREEMENT_PAIRS:
                pairs = []
                for sid in self.scenarios:
                    a1 = by_key.get((model, theory, sid, c1))
                    a2 = by_key.get((model, theory, sid, c2))
                    if a1 is not None and a2 is not None:
                        pairs.append((a1, a2))
                if not pairs:
                    continue
                out.append(OrderedDict([
                    ("model", model), ("theory", theory), ("pair", "{} vs {}".format(c1, c2)),
                    ("n", len(pairs)),
                    ("agreement", _r(_mean(a == b for a, b in pairs))),
                    ("cohen_kappa", _r(cohen_kappa(pairs))),
                ]))
        return out

    def calibration_table(self):
        out = []
        for key, rows in _group(self.rows, ("model", "theory", "condition")).items():
            out.append(OrderedDict(list(zip(("model", "theory", "condition"), key)) + [
                ("n", len(rows)),
                ("hits_exact_rate", _r(_mean(r["pred_pedestrians_hit"] == r["pedestrians_hit"]
                                             for r in rows))),
                ("hits_mae", _r(_mean(abs(r["pred_pedestrians_hit"] - r["pedestrians_hit"])
                                      for r in rows))),
                ("hits_mean_signed_error", _r(_mean(r["pred_pedestrians_hit"]
                                                    - r["pedestrians_hit"] for r in rows))),
                ("collision_accuracy", _r(_mean(r["pred_any_collision"] == r["any_collision"]
                                                for r in rows))),
            ]))
        return out

    def best_action_grid(self):
        """{sizes key: {(speed, distance): [best actions]}} and how often it changes."""
        grids = OrderedDict()
        for sid, s in self.scenarios.items():
            sizes = s.tags.get("sizes")
            key = ",".join("{}={}".format(k, v) for k, v in sorted(sizes.items())) if sizes else "-"
            grids.setdefault(key, OrderedDict())[(s.ego_speed_mps, s.tags.get("distance_m"))] = \
                self.best[sid]
        return grids

    def best_action_table(self):
        out = []
        for key, cells in self.best_action_grid().items():
            distinct = set(tuple(v) for v in cells.values())
            for (v, d), best in cells.items():
                out.append(OrderedDict([("group_sizes", key), ("speed_mps", v),
                                        ("distance_m", d), ("best_actions", "|".join(best)),
                                        ("distinct_best_in_grid", len(distinct))]))
        return out

    def write_csvs(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        tables = {
            "outcomes.csv": self.outcome_table(),
            "answers.csv": self.rows,
            "regret.csv": self.regret_table(),
            "agreement.csv": self.agreement_table(),
            "calibration.csv": self.calibration_table(),
            "best_action_grid.csv": self.best_action_table(),
        }
        for name, rows in tables.items():
            write_csv(os.path.join(out_dir, name), rows)
        return tables


def cohen_kappa(pairs):
    """Cohen's kappa for two raters over ACTIONS; None when undefined."""
    n = float(len(pairs))
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n)
             for c in ACTIONS)
    if abs(1.0 - pe) < 1e-12:
        return None
    return (po - pe) / (1.0 - pe)


def _group(rows, keys):
    out = OrderedDict()
    for r in sorted(rows, key=lambda r: tuple(r[k] for k in keys)):
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


def _mean(values):
    values = [float(v) for v in values]
    return sum(values) / len(values) if values else None


def _r(x, nd=3):
    return None if x is None else round(x, nd)


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not rows:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
