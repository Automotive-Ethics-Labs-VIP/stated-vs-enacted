import json
import os
import random

import pytest

from sve import jsonl
from sve.media.annotate import process_run, project
from sve.sim import FakeSim

from conftest import make_scenario

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def test_point_straight_ahead_projects_to_the_centre():
    assert project((10.0, 0.0, 0.0), IDENTITY, 1280, 720, 90) == (640.0, 360.0)


def test_right_and_up_map_to_right_and_up_in_the_image():
    u, v = project((10.0, 2.0, 1.0), IDENTITY, 1280, 720, 90)
    assert u > 640 and v < 360
    # 90 degree fov: f = 640, so 2 m right at 10 m is 128 px right
    assert u == pytest.approx(640 + 128)


def test_behind_the_camera_is_none():
    assert project((-5.0, 0.0, 0.0), IDENTITY, 1280, 720, 90) is None


def _fake_capture(run_dir, blank=False):
    s = make_scenario(speed=10.0, distance=15.0, ahead=1, left=1)
    o = FakeSim().run(s, "maintain")
    jsonl.write(os.path.join(run_dir, "outcomes.jsonl"), [o])
    d = os.path.join(run_dir, "media", "frames", "s1_maintain")
    frames = []
    rng = random.Random(0)
    for cam in ("top", "chase"):
        os.makedirs(os.path.join(d, cam))
    for i in range(6):
        for cam in ("top", "chase"):
            if blank:
                img = Image.new("RGB", (320, 180), (0, 0, 0))
            else:
                img = Image.new("RGB", (320, 180))
                img.putdata([(rng.randrange(256),) * 3 for _ in range(320 * 180)])
            img.save(os.path.join(d, cam, "%04d.png" % i))
        frames.append({"i": i, "t": 0.1 * (i + 1), "frame": i, "x": i, "y": 0.0,
                       "speed_mps": 10.0, "top_world_to_camera": IDENTITY,
                       "chase_world_to_camera": IDENTITY})
    meta = {"scenario_id": "s1", "action": "maintain", "fps": 10.0, "width": 320, "height": 180,
            "cameras": {"top": {"fov": 90.0}, "chase": {"fov": 90.0}},
            "labels": [{"group_id": "ahead", "person": 0, "attributes": {"age_group": "adult"},
                        "world": [15.0, 0.0, 0.0]}],
            "frames": frames}
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump(meta, f)


def test_process_run_builds_gifs_keyframes_and_checks(tmp_path):
    run = str(tmp_path)
    _fake_capture(run)
    report = process_run(run, log=lambda *_: None)
    media = os.path.join(run, "media")
    assert os.path.exists(os.path.join(media, "s1_maintain.gif"))
    assert os.path.exists(os.path.join(media, "s1_maintain_chase.gif"))
    assert os.path.exists(os.path.join(media, "keyframes", "s1_maintain.png"))
    assert report["blank_frames"] == 0 and report["total_frames"] == 12
    gif = Image.open(os.path.join(media, "s1_maintain.gif"))
    assert gif.n_frames == 6


def test_blank_frames_are_flagged(tmp_path):
    run = str(tmp_path)
    _fake_capture(run, blank=True)
    report = process_run(run, log=lambda *_: None)
    assert report["blank_frames"] == 12


def test_gif_shrinks_to_fit(tmp_path):
    run = str(tmp_path)
    _fake_capture(run)
    report = process_run(run, max_gif_mb=0.05, log=lambda *_: None)
    info = report["runs"]["s1_maintain"]["top"]["gif_info"]
    assert info["width"] < 640 or info["frame_step"] > 1
