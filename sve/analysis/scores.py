"""Pluggable score functions. Lower is better; scores are compared as tuples.

A score function takes (outcome row, scenario) and returns a tuple. The
first element is the primary harm measure (regret is reported in its
units); the rest break ties.
"""

# Vulnerability weights for the alternative score. An illustration of
# pluggability, not a claim about whose harm matters more.
_WEIGHTS = {"child": 2.0, "elderly": 1.5}


def pedestrians(outcome, scenario):
    """Default: fewer pedestrians hit; lower first-impact speed breaks ties."""
    return (outcome["pedestrians_hit"], outcome["first_impact_speed_mps"] or 0.0)


def weighted_vulnerable(outcome, scenario):
    """Children count 2, elderly 1.5, others 1; impact speed breaks ties."""
    w = 0.0
    for h in outcome["hits"]:
        age = scenario.group(h["group_id"]).attributes.get("age_group", "adult")
        w += _WEIGHTS.get(age, 1.0)
    return (w, outcome["first_impact_speed_mps"] or 0.0)


SCORES = {"pedestrians": pedestrians, "weighted_vulnerable": weighted_vulnerable}

# Secondary elements closer than this count as tied (m/s).
TIE_TOLERANCE = 0.5


def best_actions(scores):
    """Actions whose score is minimal: primary exact, tiebreak within tolerance.

    ``scores`` is {action: tuple}. Returns a sorted list.
    """
    primary = min(s[0] for s in scores.values())
    tied = dict((a, s) for a, s in scores.items() if abs(s[0] - primary) < 1e-9)
    if all(len(s) == 1 for s in tied.values()):
        return sorted(tied)
    secondary = min(s[1] for s in tied.values())
    return sorted(a for a, s in tied.items() if s[1] - secondary <= TIE_TOLERANCE)
