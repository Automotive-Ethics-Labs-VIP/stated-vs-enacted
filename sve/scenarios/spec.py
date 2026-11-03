"""Scenario spec: one dilemma frozen at the decision moment.

Positions are in the road frame of the ego at t0: ``distance_m`` is metres
ahead of the ego's centre, ``lateral_m`` metres to the right (negative is
left). This matches CARLA's left-handed frame, so no sign flips are needed.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# Layouts the sims know how to build. The ego starts in the middle lane.
LAYOUTS = {"straight_3lane": {"lanes": 3, "ego_lane": 1}}

GROUP_ATTRIBUTES = {
    "age_group": ("child", "teen", "adult", "elderly"),
    "disability": ("none", "wheelchair", "cane", "blind"),
    "pregnant": (True, False),
}
OBSTACLE_TYPES = ("barrier", "vehicle", "prop")

# Spacing between people standing side by side in a group, metres.
PERSON_SPACING_M = 0.7


class SpecError(ValueError):
    pass


@dataclass
class Group:
    id: str
    count: int
    distance_m: float
    lateral_m: float
    attributes: Dict[str, object] = field(default_factory=dict)


@dataclass
class Obstacle:
    id: str
    type: str
    distance_m: float
    lateral_m: float


@dataclass
class Scenario:
    id: str
    ego_speed_mps: float
    layout: str = "straight_3lane"
    lane_width_m: float = 3.5
    groups: List[Group] = field(default_factory=list)
    obstacles: List[Obstacle] = field(default_factory=list)
    seed: int = 0
    tags: Dict[str, object] = field(default_factory=dict)

    def group(self, group_id):
        for g in self.groups:
            if g.id == group_id:
                return g
        raise KeyError(group_id)

    @property
    def total_people(self):
        return sum(g.count for g in self.groups)


def person_positions(group):
    """(distance_m, lateral_m) of each person, side by side, centred on the group."""
    n = group.count
    return [
        (group.distance_m, group.lateral_m + (i - (n - 1) / 2.0) * PERSON_SPACING_M)
        for i in range(n)
    ]


def _number(raw, key, where, positive=False):
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError("{}: {} must be a number".format(where, key))
    if positive and value <= 0:
        raise SpecError("{}: {} must be > 0".format(where, key))
    return float(value)


def _check_keys(raw, allowed, where):
    if not isinstance(raw, dict):
        raise SpecError("{}: expected an object".format(where))
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise SpecError("{}: unknown field(s) {}".format(where, ", ".join(unknown)))


def _group(raw, where):
    _check_keys(raw, ("id", "count", "distance_m", "lateral_m", "attributes"), where)
    gid = raw.get("id")
    if not isinstance(gid, str) or not gid:
        raise SpecError("{}: id must be a non-empty string".format(where))
    count = raw.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise SpecError("{}: count must be an integer >= 1".format(where))
    attrs = raw.get("attributes", {})
    _check_keys(attrs, GROUP_ATTRIBUTES, where + ".attributes")
    for key, value in attrs.items():
        if value not in GROUP_ATTRIBUTES[key] or (isinstance(value, bool) != (key == "pregnant")):
            raise SpecError("{}: {}={!r} is not one of {}".format(
                where, key, value, GROUP_ATTRIBUTES[key]))
    return Group(gid, count, _number(raw, "distance_m", where, positive=True),
                 _number(raw, "lateral_m", where), dict(attrs))


def _obstacle(raw, where):
    _check_keys(raw, ("id", "type", "distance_m", "lateral_m"), where)
    oid = raw.get("id")
    if not isinstance(oid, str) or not oid:
        raise SpecError("{}: id must be a non-empty string".format(where))
    if raw.get("type") not in OBSTACLE_TYPES:
        raise SpecError("{}: type must be one of {}".format(where, OBSTACLE_TYPES))
    return Obstacle(oid, raw["type"], _number(raw, "distance_m", where, positive=True),
                    _number(raw, "lateral_m", where))


def scenario_from_dict(raw):
    _check_keys(raw, ("id", "ego_speed_mps", "layout", "lane_width_m", "groups",
                      "obstacles", "seed", "tags"), "scenario")
    sid = raw.get("id")
    if not isinstance(sid, str) or not sid:
        raise SpecError("scenario: id must be a non-empty string")
    where = "scenario " + sid
    layout = raw.get("layout", "straight_3lane")
    if layout not in LAYOUTS:
        raise SpecError("{}: layout must be one of {}".format(where, sorted(LAYOUTS)))
    groups = [_group(g, "{}.groups[{}]".format(where, i))
              for i, g in enumerate(raw.get("groups", []))]
    obstacles = [_obstacle(o, "{}.obstacles[{}]".format(where, i))
                 for i, o in enumerate(raw.get("obstacles", []))]
    ids = [g.id for g in groups] + [o.id for o in obstacles]
    if len(set(ids)) != len(ids):
        raise SpecError("{}: group and obstacle ids must be unique".format(where))
    seed = raw.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SpecError("{}: seed must be an integer".format(where))
    return Scenario(
        id=sid,
        ego_speed_mps=_number(raw, "ego_speed_mps", where, positive=True),
        layout=layout,
        lane_width_m=_number(dict(raw, lane_width_m=raw.get("lane_width_m", 3.5)),
                             "lane_width_m", where, positive=True),
        groups=groups,
        obstacles=obstacles,
        seed=seed,
        tags=dict(raw.get("tags", {})),
    )


def scenario_to_dict(s):
    return {
        "id": s.id,
        "ego_speed_mps": s.ego_speed_mps,
        "layout": s.layout,
        "lane_width_m": s.lane_width_m,
        "groups": [{"id": g.id, "count": g.count, "distance_m": g.distance_m,
                    "lateral_m": g.lateral_m, "attributes": dict(g.attributes)}
                   for g in s.groups],
        "obstacles": [{"id": o.id, "type": o.type, "distance_m": o.distance_m,
                       "lateral_m": o.lateral_m} for o in s.obstacles],
        "seed": s.seed,
        "tags": dict(s.tags),
    }


def lane_of(lateral_m, lane_width_m):
    """-1 left lane, 0 ego lane, +1 right lane (beyond +-1 clamps to the road edge)."""
    return max(-1, min(1, int(round(lateral_m / lane_width_m))))


def lane_name(index):
    return {-1: "left", 0: "ego", 1: "right"}[index]


def extent(s):
    # type: (Scenario) -> Tuple[float, float]
    """Nearest and farthest actor distance."""
    d = [g.distance_m for g in s.groups] + [o.distance_m for o in s.obstacles]
    return (min(d), max(d)) if d else (0.0, 0.0)
