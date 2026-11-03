"""CarlaSim against the fake carla module: wiring, not physics."""

import json
import os

import pytest

import fake_carla
from sve import ACTIONS
from sve.sim.carla_sim import RoadFrame

from conftest import make_scenario


@pytest.fixture
def sim(monkeypatch):
    fake_carla.install(monkeypatch)
    from sve.sim.carla_sim import CarlaSim
    s = CarlaSim(settle_ticks=3)
    yield s
    s.close()


def test_road_frame_round_trip_and_left_handed_right():
    f = RoadFrame((10.0, 5.0, 0.0), 90.0)
    wx, wy = f.to_world(3.0, 2.0)
    # yaw 90 faces +y; "right" in CARLA's left-handed frame is then -x
    assert (round(wx, 6), round(wy, 6)) == (8.0, 8.0)
    x, y = f.to_road(wx, wy)
    assert (round(x, 6), round(y, 6)) == (3.0, 2.0)


def test_setup_finds_middle_lane_and_sync_mode(sim):
    assert sim.info["section"]["lane_id"] == -2
    assert sim.world.settings.synchronous_mode
    assert sim.world.settings.fixed_delta_seconds == 0.05
    assert sim.world.settings.no_rendering_mode  # no capture


def test_observation_from_actor_positions(sim):
    s = make_scenario(speed=10.0, distance=20.0, ahead=2, left=1)
    obs = sim.observe(s)
    assert obs["sim"] == "carla"
    assert obs["ego"]["lane_index"] == 2 and obs["ego"]["lanes_total"] == 3
    assert obs["ego"]["left_lane_available"] and obs["ego"]["right_lane_available"]
    assert obs["ego"]["speed_mps"] == pytest.approx(10.0, abs=0.5)
    assert len(obs["detections"]) == 3
    child = [d for d in obs["detections"] if d["tags"].get("age_group") == "child"][0]
    assert child["rel_right_m"] == pytest.approx(-3.5, abs=0.1)
    assert sim.world.actors == {}  # cleaned up


def test_runs_record_hits_and_clean_up(sim):
    s = make_scenario(speed=10.0, distance=15.0, ahead=1, left=1)
    rows = dict((a, sim.run(s, a)) for a in ACTIONS)
    assert rows["maintain"]["groups_hit"] == ["ahead"]
    assert rows["maintain"]["initial_speed_mps"] == pytest.approx(10.0, abs=0.5)
    assert rows["maintain"]["first_impact_speed_mps"] > 5
    assert rows["brake"]["pedestrians_hit"] == 0
    assert rows["swerve_left"]["groups_hit"] == ["left"]
    assert rows["swerve_right"]["pedestrians_hit"] == 0
    assert rows["swerve_right"]["swerve_completed"] is True
    assert sim.world.actors == {}


def test_capture_writes_frames_and_meta(monkeypatch, tmp_path):
    fake_carla.install(monkeypatch)
    from sve.sim.carla_sim import CarlaSim
    sim = CarlaSim(settle_ticks=3, capture=True)
    try:
        assert not sim.world.settings.no_rendering_mode
        s = make_scenario(speed=10.0, distance=15.0, ahead=1, left=1)
        sim.run(s, "brake", capture_dir=str(tmp_path))
    finally:
        sim.close()
    run_dir = tmp_path / "frames" / "s1_brake"
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["fps"] == 10.0
    assert len(meta["frames"]) >= 3
    assert len(os.listdir(str(run_dir / "top"))) == len(meta["frames"])
    assert len(os.listdir(str(run_dir / "chase"))) == len(meta["frames"])
    assert len(meta["frames"][0]["top_world_to_camera"]) == 4
    assert {l["group_id"] for l in meta["labels"]} == {"ahead", "left"}
