import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sve.scenarios import expand_grid, load_grid, scenario_from_dict  # noqa: E402

SMOKE = os.path.join(ROOT, "grids", "smoke.json")


@pytest.fixture
def smoke():
    return expand_grid(load_grid(SMOKE))


def make_scenario(speed=10.0, distance=15.0, ahead=1, left=1, right=0, obstacles=(), **attrs):
    groups = []
    for gid, n, lane, age in (("ahead", ahead, 0, "adult"), ("left", left, -1, "child"),
                              ("right", right, 1, "elderly")):
        if n:
            groups.append({"id": gid, "count": n, "distance_m": distance,
                           "lateral_m": lane * 3.5, "attributes": {"age_group": age}})
    return scenario_from_dict({"id": attrs.get("id", "s1"), "ego_speed_mps": speed,
                               "groups": groups, "obstacles": list(obstacles),
                               "tags": {"distance_m": distance, "speed_mps": speed,
                                        "sizes": {"ahead": ahead, "left": left,
                                                  "right": right}}})
