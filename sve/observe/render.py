"""ENACTED condition: observation snapshot -> structured sensor readout.

Deliberately not the text templates. This works from what the simulator
measured at t0 (observations.jsonl), never from the scenario spec, and
writes a fixed-format readout:

- one line per detected object, never grouped into "two children"
- sensed units: range and bearing from the ego's centre, plus forward/right
  offsets, rounded to 0.1 m / 1 degree
- lanes as numbered indices, not "your lane"
- attribute tags shown as key=value metadata, the way a perception stack
  would label them
- no narrative sentences

See docs/conditions.md for the full list of differences.
"""


def _tags(tags):
    if not tags:
        return "-"
    return ",".join("{}={}".format(k, str(v).lower() if isinstance(v, bool) else v)
                    for k, v in sorted(tags.items()))


def render(observation):
    ego = observation["ego"]
    lines = [
        "SENSOR SNAPSHOT t=0.00s",
        "EGO speed={:.1f}m/s heading={:.0f}deg lane={}/{} (1=leftmost) lane_width={:.1f}m".format(
            ego["speed_mps"], ego["heading_deg"], ego["lane_index"], ego["lanes_total"],
            ego["lane_width_m"]),
        "LANES left_adjacent={} right_adjacent={}".format(
            "drivable" if ego["left_lane_available"] else "none",
            "drivable" if ego["right_lane_available"] else "none"),
        "OBJECTS n={} (range/bearing from ego centre; bearing + = right)".format(
            len(observation["detections"])),
        "id    class   range_m  bearing_deg  fwd_m  right_m  tags",
    ]
    detections = sorted(observation["detections"],
                        key=lambda d: (round(d["range_m"], 1), d["bearing_deg"], d["id"]))
    for d in detections:
        lines.append("{:<5} {:<7} {:>7.1f}  {:>11.0f}  {:>5.1f}  {:>7.1f}  {}".format(
            d["id"], d["cls"], d["range_m"], d["bearing_deg"], d["rel_forward_m"],
            d["rel_right_m"], _tags(d["tags"])))
    return "\n".join(lines)
