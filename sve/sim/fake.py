"""FakeSim: a kinematic bicycle model with simple collision boxes. No CARLA.

Good enough to exercise the whole pipeline and the shared controllers. Not a
physics reference: tyres saturate at a fixed friction limit, people are
circles that don't move, and hitting a person doesn't slow the car.
"""

import math
from dataclasses import dataclass

from ..scenarios.spec import person_positions
from .base import (DT, MAX_DURATION_S, PAST_MARGIN_M, TRAJECTORY_EVERY, Simulator,
                   detection, outcome_row)
from .controllers import ActionController, ControllerParams, swerve_completed
from .controllers import lost_control as is_lost

# Half extents (along x, along y) of fixed obstacles, metres.
OBSTACLE_HALF = {"barrier": (0.3, 1.5), "vehicle": (2.3, 0.95), "prop": (0.4, 0.4)}


@dataclass
class FakeParams:
    length_m: float = 4.7
    width_m: float = 1.9
    person_radius_m: float = 0.3
    max_accel_mps2: float = 5.0
    resistance_mps2: float = 1.2
    max_brake_mps2: float = 8.0
    friction_mps2: float = 8.8      # mu * g
    steer_tau_s: float = 0.15       # first-order lag on steering


def _corners(cx, cy, hx, hy, psi):
    c, s = math.cos(psi), math.sin(psi)
    return [(cx + c * ax - s * ay, cy + s * ax + c * ay)
            for ax, ay in ((hx, hy), (hx, -hy), (-hx, -hy), (-hx, hy))]


def _boxes_overlap(a, b):
    """Separating-axis test for two convex quads given as corner lists."""
    for quad in (a, b):
        for i in range(4):
            x1, y1 = quad[i]
            x2, y2 = quad[(i + 1) % 4]
            nx, ny = y2 - y1, x1 - x2
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def _circle_hits_box(px, py, r, cx, cy, hx, hy, psi):
    c, s = math.cos(psi), math.sin(psi)
    dx, dy = px - cx, py - cy
    lx, ly = c * dx + s * dy, -s * dx + c * dy
    qx = max(-hx, min(hx, lx))
    qy = max(-hy, min(hy, ly))
    return (lx - qx) ** 2 + (ly - qy) ** 2 <= r * r


class FakeSim(Simulator):
    name = "fake"

    def __init__(self, params=None, controller_params=None):
        self.p = params or FakeParams()
        self.cp = controller_params or ControllerParams()

    def observe(self, scenario):
        detections = []
        people = []
        for g in scenario.groups:
            for x, y in person_positions(g):
                people.append((x, y, g.attributes))
        for i, (x, y, attrs) in enumerate(sorted(people, key=lambda p: (p[0], p[1]))):
            detections.append(detection("w%d" % (i + 1), "walker", x, y, attrs))
        for i, o in enumerate(scenario.obstacles):
            detections.append(detection("o%d" % (i + 1), "static", o.distance_m, o.lateral_m,
                                        {"type": o.type}))
        return {
            "scenario_id": scenario.id,
            "sim": self.name,
            "ego": {"speed_mps": scenario.ego_speed_mps, "heading_deg": 0.0,
                    "lane_index": 2, "lanes_total": 3, "lane_width_m": scenario.lane_width_m,
                    "left_lane_available": True, "right_lane_available": True},
            "detections": detections,
        }

    def run(self, scenario, action, capture_dir=None):
        p = self.p
        ctrl = ActionController(action, scenario.ego_speed_mps, scenario.lane_width_m, self.cp)
        x = y = psi = delta = 0.0
        v = scenario.ego_speed_mps
        hx, hy = p.length_m / 2.0, p.width_m / 2.0
        people = [(g.id, i, px, py) for g in scenario.groups
                  for i, (px, py) in enumerate(person_positions(g))]
        hit_people = set()
        hits, obstacles_hit = [], []
        swerve_done = swerve_completed(action, y, psi, scenario.lane_width_m)
        lost = False
        far = max([g.distance_m for g in scenario.groups]
                  + [o.distance_m for o in scenario.obstacles] + [0.0])
        trajectory = [[0.0, 0.0, 0.0, v]]
        t, tick = 0.0, 0
        while t < MAX_DURATION_S - 1e-9:
            u = ctrl(y, psi, v, DT)
            # Plant: steering lag, longitudinal accel, kinematic bicycle.
            delta += (u.steer * self.cp.max_steer_rad - delta) * min(1.0, DT / p.steer_tau_s)
            a = u.throttle * p.max_accel_mps2 - u.brake * p.max_brake_mps2
            a -= p.resistance_mps2 if v > 0 else 0.0
            yaw_rate = v * math.tan(delta) / self.cp.wheelbase_m
            limit = p.friction_mps2 / max(v, 0.1)
            if abs(yaw_rate) > limit:  # tyres saturate: the car turns no tighter
                yaw_rate = math.copysign(limit, yaw_rate)
            psi += yaw_rate * DT
            x += v * math.cos(psi) * DT
            y += v * math.sin(psi) * DT
            v = max(0.0, v + a * DT)
            t += DT
            tick += 1

            for gid, i, px, py in people:
                if (gid, i) not in hit_people and _circle_hits_box(
                        px, py, p.person_radius_m, x, y, hx, hy, psi):
                    hit_people.add((gid, i))
                    hits.append({"group_id": gid, "person": i, "t": round(t, 3),
                                 "impact_speed_mps": v})
            car = _corners(x, y, hx, hy, psi)
            crashed = False
            for o in scenario.obstacles:
                if o.id in obstacles_hit:
                    continue
                ox, oy = OBSTACLE_HALF[o.type]
                if _boxes_overlap(car, _corners(o.distance_m, o.lateral_m, ox, oy, 0.0)):
                    obstacles_hit.append(o.id)
                    crashed = True
            if crashed:
                v = 0.0
            lost = lost or is_lost(y, psi, scenario.lane_width_m)
            if swerve_done is False and swerve_completed(action, y, psi, scenario.lane_width_m):
                swerve_done = True
            if tick % TRAJECTORY_EVERY == 0:
                trajectory.append([round(t, 3), x, y, v])
            if v <= 0.05 or x > far + PAST_MARGIN_M:
                break
        if trajectory[-1][0] != round(t, 3):
            trajectory.append([round(t, 3), x, y, v])
        final = {"x": x, "y": y, "heading_deg": math.degrees(psi), "speed_mps": v}
        return outcome_row(scenario, action, self.name, scenario.ego_speed_mps, hits,
                           obstacles_hit, swerve_done, lost, final, round(t, 3),
                           trajectory)
