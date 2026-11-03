import re

from sve import observe, text
from sve.llm import build_prompts
from sve.scenarios import scenario_from_dict
from sve.sim import FakeSim

from conftest import make_scenario


def test_abstract_has_people_but_no_numbers():
    s = make_scenario(speed=12, distance=15, ahead=2, left=1, right=1)
    t = text.render(s, "abstract")
    assert "two adults" in t and "one child" in t and "one elderly person" in t
    assert not re.search(r"\d", t)


def test_detailed_adds_speed_distance_and_offsets():
    s = make_scenario(speed=12, distance=15, ahead=2, left=1)
    t = text.render(s, "detailed")
    assert "12 m/s (43 km/h)" in t
    assert "15 m ahead" in t
    assert "3.5 m to the left of your path" in t
    assert "Two adults are standing in your lane" in t
    assert "The lane to your right is clear." in t


def test_people_descriptions():
    assert text.describe_people(1, {"age_group": "child"}) == "one child"
    assert text.describe_people(3, {"age_group": "elderly"}) == "three elderly people"
    assert text.describe_people(1, {"pregnant": True}) == "one pregnant adult"
    assert (text.describe_people(2, {"age_group": "adult", "disability": "wheelchair"})
            == "two adults who use a wheelchair")
    assert text.describe_people(12, {}) == "12 adults"


def test_obstacles_are_described():
    s = scenario_from_dict({"id": "o", "ego_speed_mps": 10, "obstacles": [
        {"id": "w", "type": "barrier", "distance_m": 12, "lateral_m": 3.5}]})
    assert "concrete barrier in the lane to your right, 12 m ahead" in text.render(s, "detailed")


def test_enacted_readout_is_structured_and_per_person():
    s = make_scenario(speed=12, distance=15, ahead=2, left=1)
    r = observe.render(FakeSim().observe(s))
    lines = r.splitlines()
    assert lines[0] == "SENSOR SNAPSHOT t=0.00s"
    assert "speed=12.0m/s" in r and "lane=2/3" in r
    walkers = [l for l in lines if " walker " in l]
    assert len(walkers) == 3  # one line per person, never grouped
    assert sum("age_group=adult" in l for l in walkers) == 2
    # sensed values, rounded
    assert any("15.4" in l and "-13" in l and "-3.5" in l for l in walkers)


def test_conditions_are_not_trivially_identical():
    s = make_scenario(speed=12, distance=15, ahead=2, left=1)
    stated = text.render(s, "detailed")
    enacted = observe.render(FakeSim().observe(s))
    for phrase in ("your lane", "standing", "Two adults", "directly ahead"):
        assert phrase in stated
        assert phrase not in enacted


def test_prompts_never_leak_scenario_ids_or_outcomes(smoke):
    sim = FakeSim()
    prompts = build_prompts(smoke, [sim.observe(s) for s in smoke])
    for rows in prompts.values():
        for p in rows:
            assert "smoke_" not in p["text"]
            for word in ("hit", "collision sensor", "outcome", "best"):
                body = p["text"].split("SITUATION:")[1].split("Reply with")[0]
                assert word not in body.lower()
