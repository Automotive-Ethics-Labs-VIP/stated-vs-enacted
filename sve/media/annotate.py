"""Annotate captured CARLA frames, check for blank frames, build GIFs and key frames.

Input: <run>/media/frames/<scenario>_<action>/{meta.json, top/NNNN.png, chase/NNNN.png}
Output (all under <run>/media/):

    <scenario>_<action>.gif         top-down, annotated
    <scenario>_<action>_chase.gif   chase view, annotated
    keyframes/<scenario>_<action>.png   top-down at first impact, or the last frame
    frame_check.json                pixel statistics; blank frames flagged

Pedestrian attributes are drawn as labels projected from each group's 3D
position through the camera matrix. They are metadata: the walker models
don't show age.
"""

import json
import math
import os

from .. import jsonl
from ..sim.base import outcome_text
from ..text import describe_people

BLANK_STD = 2.0          # a frame whose pixel std-dev is below this is blank
GIF_WIDTHS = (640, 480, 360)
NOTE = "Attributes are metadata labels; CARLA walker models are generic."


def project(world_xyz, world_to_camera, width, height, fov_deg):
    """Pixel (u, v) of a world point, or None if it is behind the camera."""
    x, y, z = world_xyz
    m = world_to_camera
    cx = m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3]
    cy = m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3]
    cz = m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]
    if cx <= 0.1:  # CARLA camera: x forward, y right, z up
        return None
    f = width / (2.0 * math.tan(math.radians(fov_deg) / 2.0))
    return (width / 2.0 + f * cy / cx, height / 2.0 - f * cz / cx)


def frame_stats(img):
    from PIL import ImageStat
    stat = ImageStat.Stat(img.convert("L"))
    return {"mean": round(stat.mean[0], 2), "std": round(stat.stddev[0], 2)}


def _font(size):
    from PIL import ImageFont
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _group_labels(meta):
    groups = {}
    for lab in meta["labels"]:
        g = groups.setdefault(lab["group_id"], {"points": [], "attributes": lab["attributes"]})
        g["points"].append(lab["world"])
    out = []
    for gid, g in sorted(groups.items()):
        n = len(g["points"])
        centre = [sum(p[k] for p in g["points"]) / n for k in range(3)]
        centre[2] += 1.2  # above head height
        out.append((describe_people(n, g["attributes"]), centre))
    return out


def annotate_frame(img, meta, frame, camera, outcome, labels):
    from PIL import ImageDraw
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    w, h = img.size
    big, small = _font(max(14, h // 32)), _font(max(12, h // 42))
    header = "{}   action: {}   t={:.2f}s   speed {:.1f} m/s".format(
        meta["scenario_id"], meta["action"], frame["t"], frame["speed_mps"])
    d.rectangle([0, 0, w, int(h * 0.11)], fill=(11, 11, 11))
    d.text((12, 6), header, fill=(240, 239, 236), font=big)
    d.text((12, 8 + int(h * 0.045)), "outcome: " + outcome_text(outcome), fill=(195, 194, 183),
           font=small)
    matrix = frame.get(camera + "_world_to_camera")
    fov = meta["cameras"][camera]["fov"]
    if matrix:
        for text, xyz in labels:
            uv = project(xyz, matrix, w, h, fov)
            if uv is None or not (0 <= uv[0] < w and 0 <= uv[1] < h):
                continue
            label = text + " (metadata)"
            box = d.textbbox((uv[0], uv[1]), label, font=small)
            d.rectangle([box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2], fill=(252, 252, 251),
                        outline=(11, 11, 11))
            d.text((uv[0], uv[1]), label, fill=(11, 11, 11), font=small)
    d.rectangle([0, h - int(h * 0.05), w, h], fill=(11, 11, 11))
    d.text((12, h - int(h * 0.045)), NOTE, fill=(195, 194, 183), font=small)
    return img


def _save_gif(frames, path, fps, max_mb):
    """Downsample (width, then frame rate) until the GIF fits under max_mb."""
    step = 1
    for width in GIF_WIDTHS:
        for step in (1, 2, 3):
            chosen = frames[::step]
            small = [f.resize((width, int(f.size[1] * width / f.size[0]))) for f in chosen]
            small[0].save(path, save_all=True, append_images=small[1:], loop=0,
                          duration=int(1000 * step / fps), optimize=True)
            if os.path.getsize(path) <= max_mb * 1024 * 1024:
                return {"width": width, "frame_step": step, "bytes": os.path.getsize(path)}
    return {"width": GIF_WIDTHS[-1], "frame_step": step, "bytes": os.path.getsize(path),
            "over_limit": True}


def process_run(run_dir, max_gif_mb=10.0, log=print):
    from PIL import Image
    media = os.path.join(run_dir, "media")
    frames_root = os.path.join(media, "frames")
    if not os.path.isdir(frames_root):
        raise SystemExit("no captured frames in {}".format(frames_root))
    outcomes = dict(((o["scenario_id"], o["action"]), o)
                    for o in jsonl.read(os.path.join(run_dir, "outcomes.jsonl")))
    os.makedirs(os.path.join(media, "keyframes"), exist_ok=True)
    report = {"runs": {}, "blank_frames": 0, "total_frames": 0}
    for name in sorted(os.listdir(frames_root)):
        meta_path = os.path.join(frames_root, name, "meta.json")
        if not os.path.exists(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        outcome = outcomes[(meta["scenario_id"], meta["action"])]
        labels = _group_labels(meta)
        hits = [h["t"] for h in outcome["hits"] if h.get("t") is not None]
        key_t = min(hits) if hits else None
        entry = {}
        for camera in sorted(meta["cameras"]):
            annotated, stats = [], []
            for frame in meta["frames"]:
                path = os.path.join(frames_root, name, camera, "%04d.png" % frame["i"])
                img = Image.open(path)
                st = frame_stats(img)
                st["blank"] = st["std"] < BLANK_STD
                stats.append(st)
                annotated.append(annotate_frame(img, meta, frame, camera, outcome, labels))
            blank = sum(s["blank"] for s in stats)
            report["blank_frames"] += blank
            report["total_frames"] += len(stats)
            suffix = "" if camera == "top" else "_" + camera
            gif = os.path.join(media, "{}{}.gif".format(name, suffix))
            info = _save_gif(annotated, gif, meta["fps"], max_gif_mb)
            entry[camera] = {"frames": len(stats), "blank": blank,
                             "min_std": min(s["std"] for s in stats) if stats else None,
                             "gif": os.path.basename(gif), "gif_info": info}
            if camera == "top" and annotated:
                times = [f["t"] for f in meta["frames"]]
                k = (min(range(len(times)), key=lambda i: abs(times[i] - key_t))
                     if key_t is not None else len(times) - 1)
                key = annotated[k]
                key = key.resize((960, int(key.size[1] * 960 / key.size[0])))
                key.save(os.path.join(media, "keyframes", name + ".png"))
            log("{} {}: {} frames, {} blank, gif {:.1f} MB".format(
                name, camera, len(stats), blank, info["bytes"] / 1e6))
        report["runs"][name] = entry
    with open(os.path.join(media, "frame_check.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    log("frames: {} total, {} blank".format(report["total_frames"], report["blank_frames"]))
    return report
