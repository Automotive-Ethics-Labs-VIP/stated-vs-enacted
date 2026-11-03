import math

import pytest

from sve import ACTIONS
from sve.sim import FakeSim, determinism_report, run_all
from sve.sim.controllers import ActionController, lost_control, swerve_completed, target_lateral
from sve.sim.fake import FakeParams

from conftest import make_scenario


def test_braking_distance_matches_kinematics():
    p = FakeParams()
    decel = p.max_brake_mps2 + p.resistance_mps2
    for v in (8.0, 12.0, 14.0):
        s = make_scenario(speed=v, distance=60.0, ahead=1, left=0)
        o = FakeSim().run(s, "brake")
        expected = v * v / (2 * decel)
        assert o["final"]["speed_mps"] == 0.0
        assert o["final"]["x"] == pytest.approx(expected, rel=0.08)
        assert o["pedestrians_hit"] == 0


def test_maintain_hits_everyone_ahead_at_speed():
    s = make_scenario(speed=12.0, distance=15.0, ahead=3, left=1)
    o = FakeSim().run(s, "maintain")
    assert o["pedestrians_hit"] == 3
    assert o["groups_hit"] == ["ahead"]
    assert o["first_impact_speed_mps"] == pytest.approx(12.0, abs=0.5)
    assert o["any_collision"]


def test_brake_too_late_still_hits_but_slower():
    s = make_scenario(speed=14.0, distance=9.0, ahead=1, left=0)
    o = FakeSim().run(s, "brake")
    assert o["pedestrians_hit"] == 1
    assert 0 < o["first_impact_speed_mps"] < 14.0


@pytest.mark.parametrize("action, side", [("swerve_left", -1), ("swerve_right", 1)])
def test_swerve_reaches_and_settles_in_the_target_lane(action, side):
    s = make_scenario(speed=10.0, distance=40.0, ahead=1, left=0)
    o = FakeSim().run(s, action)
    assert o["swerve_completed"] is True
    assert o["lost_control"] is False
    assert o["final"]["y"] == pytest.approx(side * 3.5, abs=0.3)
    assert o["pedestrians_hit"] == 0  # the ahead group is passed in the other lane


def test_swerve_into_the_left_group_hits_it():
    s = make_scenario(speed=10.0, distance=25.0, ahead=1, left=2)
    o = FakeSim().run(s, "swerve_left")
    assert o["groups_hit"] == ["left"]
    assert o["pedestrians_hit"] == 2


def test_obstacle_stops_the_car():
    s = make_scenario(speed=10.0, distance=30.0, ahead=0, left=0, obstacles=[
        {"id": "wall", "type": "barrier", "distance_m": 15.0, "lateral_m": 0.0}])
    o = FakeSim().run(s, "maintain")
    assert o["obstacles_hit"] == ["wall"]
    assert o["final"]["speed_mps"] == 0.0
    assert o["final"]["x"] < 15.0
    assert o["any_collision"] and o["pedestrians_hit"] == 0


def test_non_swerves_report_no_swerve_status():
    s = make_scenario()
    for action in ("maintain", "brake"):
        assert FakeSim().run(s, action)["swerve_completed"] is None


def test_trajectory_is_time_ordered_and_starts_at_origin():
    o = FakeSim().run(make_scenario(), "swerve_right")
    t = [p[0] for p in o["trajectory"]]
    assert t == sorted(t)
    assert o["trajectory"][0] == [0.0, 0.0, 0.0, 10.0]
    assert t[-1] == o["duration_s"]


def test_determinism_report_is_exact_for_fakesim():
    rows = determinism_report(FakeSim(), [make_scenario()], repeats=3)
    assert len(rows) == 4
    assert all(r["discrete_identical"] for r in rows)
    assert all(r["final_x_range_m"] == 0 for r in rows)


def test_run_all_covers_every_action(smoke):
    outcomes, observations = run_all(FakeSim(), smoke, log=lambda *_: None)
    assert len(outcomes) == len(smoke) * 4
    assert len(observations) == len(smoke)
    assert set((o["scenario_id"], o["action"]) for o in outcomes) == set(
        (s.id, a) for s in smoke for a in ACTIONS)


def test_observation_lists_each_person_with_bearing():
    s = make_scenario(distance=20.0, ahead=2, left=1)
    obs = FakeSim().observe(s)
    assert len(obs["detections"]) == 3
    left = [d for d in obs["detections"] if d["tags"]["age_group"] == "child"][0]
    assert left["rel_right_m"] == pytest.approx(-3.5)
    assert left["bearing_deg"] == pytest.approx(math.degrees(math.atan2(-3.5, 20.0)))
    assert left["range_m"] == pytest.approx(math.hypot(20.0, 3.5))
    assert obs["ego"]["speed_mps"] == 10.0


# ---- controllers -------------------------------------------------------

def test_target_lateral():
    assert target_lateral("swerve_left", 3.5) == -3.5
    assert target_lateral("swerve_right", 3.5) == 3.5
    assert target_lateral("brake", 3.5) == 0.0
    with pytest.raises(ValueError):
        target_lateral("reverse", 3.5)


def test_steer_sign_points_at_the_target_lane():
    right = ActionController("swerve_right", 10.0, 3.5)
    left = ActionController("swerve_left", 10.0, 3.5)
    assert right(0.0, 0.0, 10.0, 0.05).steer > 0
    assert left(0.0, 0.0, 10.0, 0.05).steer < 0
    keep = ActionController("maintain", 10.0, 3.5)
    assert keep(0.0, 0.0, 10.0, 0.05).steer == pytest.approx(0.0)
    assert keep(0.5, 0.0, 10.0, 0.05).steer < 0  # drifted right: steer back left


def test_brake_is_full_brake_no_throttle():
    u = ActionController("brake", 10.0, 3.5)(0.0, 0.0, 10.0, 0.05)
    assert (u.throttle, u.brake) == (0.0, 1.0)


def test_speed_hold_throttles_when_slow_and_brakes_when_fast():
    c = ActionController("maintain", 10.0, 3.5)
    assert c(0.0, 0.0, 8.0, 0.05).throttle > 0.3
    c = ActionController("maintain", 10.0, 3.5)
    assert c(0.0, 0.0, 14.0, 0.05).brake > 0


def test_lost_control_and_swerve_completion_rules():
    assert lost_control(0.0, math.radians(40), 3.5)
    assert lost_control(7.0, 0.0, 3.5)
    assert not lost_control(3.5, math.radians(10), 3.5)
    assert swerve_completed("swerve_left", -3.4, 0.0, 3.5) is True
    assert swerve_completed("swerve_left", -3.4, math.radians(8), 3.5) is False
    assert swerve_completed("maintain", 0.0, 0.0, 3.5) is None
