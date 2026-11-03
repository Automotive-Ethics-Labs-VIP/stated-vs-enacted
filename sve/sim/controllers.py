"""Controllers shared by FakeSim and CarlaSim.

Everything is in the road frame: x forward, y right, heading psi in radians
(positive turns toward +y), and steer in [-1, 1] (positive steers right), as
in CARLA.
"""

import math
from dataclasses import dataclass

from .. import ACTIONS


@dataclass
class Control:
    throttle: float = 0.0
    steer: float = 0.0
    brake: float = 0.0


@dataclass
class ControllerParams:
    wheelbase_m: float = 2.9
    max_steer_rad: float = math.radians(70.0)
    lookahead_gain_s: float = 0.6   # lookahead = gain * speed, clamped below
    lookahead_min_m: float = 4.0
    lookahead_max_m: float = 15.0
    throttle_ff: float = 0.3
    speed_kp: float = 0.4
    speed_ki: float = 0.1


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def target_lateral(action, lane_width_m):
    if action not in ACTIONS:
        raise ValueError("unknown action {!r}".format(action))
    return {"swerve_left": -lane_width_m, "swerve_right": lane_width_m}.get(action, 0.0)


class ActionController(object):
    """Pure-pursuit steering toward the target lane centre, PI speed hold.

    ``brake`` brakes fully and keeps the lane. The other actions hold the
    t0 speed. Swerves steer into the adjacent lane and stay there.
    """

    def __init__(self, action, target_speed_mps, lane_width_m, params=None):
        self.action = action
        self.target_y = target_lateral(action, lane_width_m)
        self.target_speed = target_speed_mps
        self.p = params or ControllerParams()
        self._integral = 0.0

    def steer(self, y, psi, speed):
        p = self.p
        lookahead = clamp(p.lookahead_gain_s * speed, p.lookahead_min_m, p.lookahead_max_m)
        alpha = math.atan2(self.target_y - y, lookahead) - psi
        delta = math.atan2(2.0 * p.wheelbase_m * math.sin(alpha), lookahead)
        return clamp(delta / p.max_steer_rad, -1.0, 1.0)

    def __call__(self, y, psi, speed, dt):
        steer = self.steer(y, psi, speed)
        if self.action == "brake":
            return Control(throttle=0.0, steer=steer, brake=1.0)
        error = self.target_speed - speed
        self._integral = clamp(self._integral + error * dt, -5.0, 5.0)
        u = self.p.throttle_ff + self.p.speed_kp * error + self.p.speed_ki * self._integral
        if u >= 0:
            return Control(throttle=clamp(u, 0.0, 1.0), steer=steer)
        return Control(throttle=0.0, steer=steer, brake=clamp(-u, 0.0, 1.0))


LOST_HEADING_DEG = 35.0
ROAD_EDGE_MARGIN_M = 1.0


def lost_control(y, psi, lane_width_m):
    """Heading swung past 35 degrees, or the car left the 3-lane road."""
    off_road = abs(y) > 1.5 * lane_width_m + ROAD_EDGE_MARGIN_M
    return off_road or abs(math.degrees(psi)) > LOST_HEADING_DEG


def swerve_completed(action, y, psi, lane_width_m, tol_m=0.5, tol_heading_deg=5.0):
    """True once a swerve is settled in the target lane; None for other actions."""
    if action not in ("swerve_left", "swerve_right"):
        return None
    target = target_lateral(action, lane_width_m)
    return abs(y - target) < tol_m and abs(math.degrees(psi)) < tol_heading_deg
