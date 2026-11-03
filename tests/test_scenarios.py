import copy

import pytest

from sve.scenarios import (SpecError, expand_grid, load_grid, person_positions,
                           scenario_from_dict, scenario_to_dict)
from sve.scenarios.spec import lane_of

from conftest import SMOKE


def test_smoke_grid_is_2_speeds_by_2_distances():
    scenarios = expand_grid(load_grid(SMOKE))
    assert len(scenarios) == 4
    assert sorted(set(s.ego_speed_mps for s in scenarios)) == [8, 14]
    assert sorted(set(s.tags["distance_m"] for s in scenarios)) == [10, 20]
    assert len(set(s.id for s in scenarios)) == 4


def test_groups_sit_in_their_lane_at_the_grid_distance(smoke):
    s = smoke[0]
    lanes = dict((g.id, lane_of(g.lateral_m, s.lane_width_m)) for g in s.groups)
    assert lanes == {"ahead": 0, "left": -1, "right": 1}
    assert all(g.distance_m == s.tags["distance_m"] for g in s.groups)
    assert s.group("ahead").count == 2


def test_size_zero_leaves_the_group_out():
    grid = load_grid(SMOKE)
    grid["group_sizes"] = [{"ahead": 1, "left": 0, "right": 2}]
    s = expand_grid(grid)[0]
    assert sorted(g.id for g in s.groups) == ["ahead", "right"]


def test_grid_product_size():
    grid = load_grid(SMOKE)
    grid["speeds_mps"] = [6, 10, 14]
    grid["group_sizes"] = [{"ahead": 1, "left": 1}, {"ahead": 3, "right": 1}]
    assert len(expand_grid(grid)) == 3 * 2 * 2


@pytest.mark.parametrize("change, message", [
    (lambda g: g.update(bogus=1), "unknown field"),
    (lambda g: g.pop("speeds_mps"), "missing speeds_mps"),
    (lambda g: g["group_sizes"].append({"middle": 1}), "unknown group"),
    (lambda g: g["groups"]["left"]["attributes"].update(age_group="toddler"), "age_group"),
])
def test_grid_errors(change, message):
    grid = copy.deepcopy(load_grid(SMOKE))
    change(grid)
    with pytest.raises(SpecError, match=message):
        expand_grid(grid)


def test_round_trip(smoke):
    for s in smoke:
        assert scenario_from_dict(scenario_to_dict(s)) == s


BASE = {"id": "x", "ego_speed_mps": 10,
        "groups": [{"id": "g", "count": 1, "distance_m": 10, "lateral_m": 0}]}


@pytest.mark.parametrize("patch, message", [
    ({"ego_speed_mps": 0}, "must be > 0"),
    ({"ego_speed_mps": True}, "must be a number"),
    ({"layout": "roundabout"}, "layout"),
    ({"extra": 1}, "unknown field"),
    ({"groups": [{"id": "g", "count": 0, "distance_m": 10, "lateral_m": 0}]}, "count"),
    ({"groups": [{"id": "g", "count": True, "distance_m": 10, "lateral_m": 0}]}, "count"),
    ({"groups": [{"id": "g", "count": 1, "distance_m": -1, "lateral_m": 0}]}, "distance_m"),
    ({"groups": [{"id": "g", "count": 1, "distance_m": 5, "lateral_m": 0,
                  "attributes": {"pregnant": "yes"}}]}, "pregnant"),
    ({"groups": [{"id": "g", "count": 1, "distance_m": 5, "lateral_m": 0,
                  "attributes": {"age_group": True}}]}, "age_group"),
    ({"obstacles": [{"id": "g", "type": "barrier", "distance_m": 5, "lateral_m": 3}]}, "unique"),
    ({"obstacles": [{"id": "o", "type": "tree", "distance_m": 5, "lateral_m": 3}]}, "type"),
])
def test_spec_errors(patch, message):
    raw = dict(BASE, **patch)
    with pytest.raises(SpecError, match=message):
        scenario_from_dict(raw)


def test_people_stand_side_by_side_centred_on_the_group():
    s = scenario_from_dict(dict(BASE, groups=[
        {"id": "g", "count": 3, "distance_m": 12, "lateral_m": 3.5}]))
    pos = person_positions(s.groups[0])
    assert [x for x, _ in pos] == [12, 12, 12]
    ys = [y for _, y in pos]
    assert ys == sorted(ys)
    assert sum(ys) / 3 == pytest.approx(3.5)
    assert ys[1] - ys[0] == pytest.approx(0.7)
