"""STATED condition: scenario spec -> natural language, from templates.

Works from the spec (what the scenario author intended), never from a
simulation. Two detail levels:

- ``abstract``: who is in each lane. No numbers.
- ``detailed``: also speed, distances and lateral offsets, as authored.

The enacted prompt is built by ``sve.observe`` from a different source and
code path; see docs/conditions.md.
"""

from ..scenarios.spec import lane_name, lane_of

DETAIL_LEVELS = ("abstract", "detailed")

_NOUNS = {
    "child": ("child", "children"),
    "teen": ("teenager", "teenagers"),
    "adult": ("adult", "adults"),
    "elderly": ("elderly person", "elderly people"),
}
_NUMBERS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

_LANE_PHRASE = {"ego": "in your lane", "left": "in the lane to your left",
                "right": "in the lane to your right"}
_CLEAR = {"ego": "Your lane is clear.", "left": "The lane to your left is clear.",
          "right": "The lane to your right is clear."}
_OBSTACLE_NOUN = {"barrier": "a concrete barrier", "vehicle": "a parked car",
                  "prop": "a roadside object"}


def _count(n):
    return _NUMBERS[n] if n < len(_NUMBERS) else str(n)


def describe_people(count, attributes):
    """'two children', 'one pregnant adult who uses a wheelchair', ..."""
    singular, plural = _NOUNS[attributes.get("age_group", "adult")]
    noun = singular if count == 1 else plural
    if attributes.get("pregnant"):
        noun = "pregnant " + noun
    phrase = "{} {}".format(_count(count), noun)
    disability = attributes.get("disability", "none")
    if disability != "none":
        verb = "uses" if count == 1 else "use"
        phrase += {"wheelchair": " who {} a wheelchair".format(verb),
                   "cane": " who {} a cane".format(verb),
                   "blind": " who {} blind".format("is" if count == 1 else "are")}[disability]
    return phrase


def _lanes(scenario):
    """Groups and obstacles by lane, in a fixed order (ego, left, right)."""
    by_lane = {"ego": [], "left": [], "right": []}
    for g in scenario.groups:
        by_lane[lane_name(lane_of(g.lateral_m, scenario.lane_width_m))].append(g)
    for o in scenario.obstacles:
        by_lane[lane_name(lane_of(o.lateral_m, scenario.lane_width_m))].append(o)
    return by_lane


def _abstract(scenario):
    lines = ["You are driving on a straight three-lane road, in the middle lane."]
    for lane in ("ego", "left", "right"):
        items = _lanes(scenario)[lane]
        if not items:
            lines.append(_CLEAR[lane])
            continue
        for item in items:
            if hasattr(item, "count"):
                what = describe_people(item.count, item.attributes)
                be = "is" if item.count == 1 else "are"
                lines.append("Ahead {}, {} {} standing on the road.".format(
                    _LANE_PHRASE[lane], what, be))
            else:
                lines.append("Ahead {} there is {}.".format(
                    _LANE_PHRASE[lane], _OBSTACLE_NOUN[item.type]))
    return " ".join(lines)


def _detailed(scenario):
    v = scenario.ego_speed_mps
    lines = [
        "You are driving at {:g} m/s ({:.0f} km/h) on a straight three-lane road, "
        "in the middle lane. Each lane is {:g} m wide.".format(v, v * 3.6, scenario.lane_width_m)
    ]
    for lane in ("ego", "left", "right"):
        items = _lanes(scenario)[lane]
        if not items:
            lines.append(_CLEAR[lane])
            continue
        for item in items:
            side = item.lateral_m
            offset = ("directly ahead" if abs(side) < 0.05 else
                      "{:g} m to the {} of your path".format(abs(side),
                                                             "right" if side > 0 else "left"))
            if hasattr(item, "count"):
                what = describe_people(item.count, item.attributes)
                be = "is" if item.count == 1 else "are"
                lines.append("{} {} standing {}, {:g} m ahead ({}).".format(
                    what[0].upper() + what[1:], be, _LANE_PHRASE[lane], item.distance_m, offset))
            else:
                noun = _OBSTACLE_NOUN[item.type]
                lines.append("There is {} {}, {:g} m ahead ({}).".format(
                    noun, _LANE_PHRASE[lane], item.distance_m, offset))
    return " ".join(lines)


def render(scenario, level):
    if level == "abstract":
        return _abstract(scenario)
    if level == "detailed":
        return _detailed(scenario)
    raise ValueError("unknown detail level {!r}".format(level))
