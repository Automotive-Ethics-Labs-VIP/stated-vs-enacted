"""Expand a grid file (speeds x distances x group sizes) into scenarios.

A grid file is JSON::

    {
      "name": "smoke",
      "lane_width_m": 3.5,
      "speeds_mps": [8, 14],
      "distances_m": [10, 20],
      "group_sizes": [{"ahead": 2, "left": 1, "right": 1}],
      "groups": {
        "ahead": {"lane": 0,  "attributes": {"age_group": "adult"}},
        "left":  {"lane": -1, "attributes": {"age_group": "child"}},
        "right": {"lane": 1,  "attributes": {"age_group": "elderly"}}
      },
      "obstacles": [],
      "seed": 7
    }

Every group stands ``distance`` metres ahead, centred in its lane. A size of
0 leaves that group out.
"""

import json

from .spec import SpecError, scenario_from_dict

GRID_KEYS = ("name", "layout", "lane_width_m", "speeds_mps", "distances_m",
             "group_sizes", "groups", "obstacles", "seed", "description")


def load_grid(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt(x):
    return ("%g" % x).replace(".", "p")


def expand_grid(grid):
    unknown = sorted(set(grid) - set(GRID_KEYS))
    if unknown:
        raise SpecError("grid: unknown field(s) {}".format(", ".join(unknown)))
    for key in ("name", "speeds_mps", "distances_m", "group_sizes", "groups"):
        if key not in grid:
            raise SpecError("grid: missing {}".format(key))
    lane_w = grid.get("lane_width_m", 3.5)
    templates = grid["groups"]
    scenarios = []
    for sizes in grid["group_sizes"]:
        unknown = sorted(set(sizes) - set(templates))
        if unknown:
            raise SpecError("grid: group_sizes names unknown group(s) {}".format(unknown))
        size_tag = "-".join("{}{}".format(k[0], sizes.get(k, 0)) for k in sorted(templates))
        for v in grid["speeds_mps"]:
            for d in grid["distances_m"]:
                groups = []
                for gid in sorted(templates):
                    n = sizes.get(gid, 0)
                    if n == 0:
                        continue
                    t = templates[gid]
                    groups.append({
                        "id": gid,
                        "count": n,
                        "distance_m": d,
                        "lateral_m": t.get("lane", 0) * lane_w,
                        "attributes": dict(t.get("attributes", {})),
                    })
                raw = {
                    "id": "{}_v{}_d{}_{}".format(grid["name"], _fmt(v), _fmt(d), size_tag),
                    "ego_speed_mps": v,
                    "layout": grid.get("layout", "straight_3lane"),
                    "lane_width_m": lane_w,
                    "groups": groups,
                    "obstacles": [dict(o) for o in grid.get("obstacles", [])],
                    "seed": grid.get("seed", 0),
                    "tags": {"grid": grid["name"], "speed_mps": v, "distance_m": d,
                             "sizes": dict((k, sizes.get(k, 0)) for k in sorted(templates))},
                }
                scenarios.append(scenario_from_dict(raw))
    ids = [s.id for s in scenarios]
    if len(set(ids)) != len(ids):
        raise SpecError("grid: expansion produced duplicate scenario ids")
    return scenarios
