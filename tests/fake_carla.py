"""A tiny stand-in for the ``carla`` module: enough API for CarlaSim's code paths.

A straight 3-lane road along +x (lanes -1, -2, -3 from left to right, 3.5 m
wide, all one direction). Vehicles move with a crude kinematic model; the
collision sensor fires when the ego comes within 1.2 m of another actor.
This checks wiring (calls, frames, bookkeeping), not physics.
"""

import math
import os
import types

DT = 0.05
LANE_W = 3.5
ROAD_LEN = 200.0


class Vector3D(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class Location(Vector3D):
    pass


class Rotation(object):
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch, self.yaw, self.roll = pitch, yaw, roll


class Transform(object):
    def __init__(self, location=None, rotation=None):
        self.location = location or Location()
        self.rotation = rotation or Rotation()

    def get_inverse_matrix(self):
        return [[1.0, 0.0, 0.0, -self.location.x], [0.0, 1.0, 0.0, -self.location.y],
                [0.0, 0.0, 1.0, -self.location.z], [0.0, 0.0, 0.0, 1.0]]


class VehicleControl(object):
    def __init__(self, throttle=0.0, steer=0.0, brake=0.0, hand_brake=False):
        self.throttle, self.steer, self.brake, self.hand_brake = throttle, steer, brake, hand_brake


class LaneType(object):
    Driving = "Driving"
    Shoulder = "Shoulder"


class AttachmentType(object):
    Rigid = "Rigid"


class _Destroy(object):
    def __init__(self, actor):
        self.actor = actor


command = types.SimpleNamespace(DestroyActor=_Destroy)


class _Attr(object):
    def __init__(self, v):
        self.v = v

    def as_str(self):
        return self.v


class Blueprint(object):
    def __init__(self, bp_id, attrs=None):
        self.id = bp_id
        self.attrs = dict(attrs or {})

    def has_attribute(self, k):
        return k in self.attrs

    def get_attribute(self, k):
        return _Attr(self.attrs[k])

    def set_attribute(self, k, v):
        self.attrs[k] = v


class Library(object):
    def __init__(self):
        self.bps = [Blueprint("vehicle.tesla.model3", {"role_name": ""}),
                    Blueprint("vehicle.audi.a2", {"role_name": ""}),
                    Blueprint("walker.pedestrian.0001", {"age": "adult", "is_invincible": "true"}),
                    Blueprint("walker.pedestrian.0010", {"age": "child", "is_invincible": "true"}),
                    Blueprint("static.prop.streetbarrier"),
                    Blueprint("static.prop.trashcan01"),
                    Blueprint("sensor.other.collision"),
                    Blueprint("sensor.camera.rgb", {"image_size_x": "", "image_size_y": "",
                                                    "fov": ""})]

    def filter(self, pattern):
        prefix = pattern.rstrip("*")
        return [Blueprint(b.id, b.attrs) for b in self.bps if b.id.startswith(prefix)]

    def find(self, bp_id):
        return [Blueprint(b.id, b.attrs) for b in self.bps if b.id == bp_id][0]


class Waypoint(object):
    def __init__(self, lane_id, s):
        self.lane_id = lane_id
        self.s = s
        self.road_id = 1
        self.section_id = 0
        self.is_junction = False
        self.lane_width = LANE_W
        self.lane_type = LaneType.Driving if lane_id in (-1, -2, -3) else LaneType.Shoulder
        y = (-lane_id - 2) * LANE_W  # lane -2 is centred on y = 0
        self.transform = Transform(Location(s, y, 0.0), Rotation(yaw=0.0))

    def get_left_lane(self):
        return Waypoint(self.lane_id + 1, self.s) if self.lane_id < -1 else None

    def get_right_lane(self):
        return Waypoint(self.lane_id - 1, self.s) if self.lane_id > -4 else None

    def next(self, step):
        return [Waypoint(self.lane_id, self.s + step)] if self.s + step <= ROAD_LEN else []


class Map(object):
    name = "Carla/Maps/FakeTown"

    def generate_waypoints(self, step):
        return [Waypoint(lane, k * step) for lane in (-1, -2, -3, -4)
                for k in range(int(ROAD_LEN / step))]

    def get_waypoint(self, loc):
        lane = -2 - int(round(loc.y / LANE_W))
        return Waypoint(max(-3, min(-1, lane)), max(0.0, loc.x))


class _Wheel(object):
    def __init__(self, x, y):
        self.position = Vector3D(x * 100, y * 100, 0)
        self.max_steer_angle = 70.0


class Actor(object):
    _next_id = 100

    def __init__(self, world, bp, transform, parent=None, rel=None):
        Actor._next_id += 1
        self.id = Actor._next_id
        self.type_id = bp.id
        self.attributes = dict(bp.attrs)
        self.world = world
        self.tf = Transform(Location(transform.location.x, transform.location.y,
                                     transform.location.z),
                            Rotation(transform.rotation.pitch, transform.rotation.yaw))
        self.v = Vector3D()
        self.control = VehicleControl()
        self.parent = parent
        self.rel = rel
        self.callback = None
        self.alive = True

    def get_transform(self):
        if self.parent is not None:
            p = self.parent.tf
            return Transform(Location(p.location.x + self.rel.location.x,
                                      p.location.y + self.rel.location.y,
                                      p.location.z + self.rel.location.z), p.rotation)
        return self.tf

    def get_location(self):
        return self.get_transform().location

    def get_velocity(self):
        return self.v

    def apply_control(self, c):
        self.control = c

    def set_target_velocity(self, v):
        self.v = Vector3D(v.x, v.y, v.z)

    def set_target_angular_velocity(self, v):
        pass

    def get_physics_control(self):
        return types.SimpleNamespace(wheels=[_Wheel(1.45, -0.8), _Wheel(1.45, 0.8),
                                             _Wheel(-1.45, -0.8), _Wheel(-1.45, 0.8)])

    def listen(self, cb):
        self.callback = cb

    def stop(self):
        self.callback = None

    def step(self):
        if not self.type_id.startswith("vehicle.") or self.parent is not None:
            return
        c = self.control
        speed = math.hypot(self.v.x, self.v.y)
        if c.hand_brake:
            speed = 0.0
        speed = max(0.0, speed + (4.0 * c.throttle - 1.0 - 8.0 * c.brake) * DT)
        yaw = math.radians(self.tf.rotation.yaw)
        delta = c.steer * math.radians(70.0)
        yaw_rate = speed * math.tan(delta) / 2.9
        cap = 8.8 / max(speed, 0.1)
        yaw += max(-cap, min(cap, yaw_rate)) * DT
        self.tf.rotation.yaw = math.degrees(yaw)
        self.v = Vector3D(speed * math.cos(yaw), speed * math.sin(yaw), 0.0)
        self.tf.location.x += self.v.x * DT
        self.tf.location.y += self.v.y * DT


class _Image(object):
    def __init__(self, frame):
        self.frame = frame

    def save_to_disk(self, path):
        with open(path, "wb") as f:
            f.write(b"\x89PNG fake")


class Settings(object):
    synchronous_mode = False
    fixed_delta_seconds = None
    no_rendering_mode = False


class World(object):
    def __init__(self):
        self.actors = {}
        self.frame = 1000
        self.settings = Settings()
        self.map = Map()
        self.lib = Library()

    def get_map(self):
        return self.map

    def get_settings(self):
        s = Settings()
        s.__dict__.update(self.settings.__dict__)
        return s

    def apply_settings(self, s):
        self.settings = s

    def get_blueprint_library(self):
        return self.lib

    def try_spawn_actor(self, bp, tf):
        a = Actor(self, bp, tf)
        self.actors[a.id] = a
        return a

    def spawn_actor(self, bp, tf, attach_to=None, attachment_type=None):
        a = Actor(self, bp, tf, parent=attach_to, rel=tf if attach_to else None)
        self.actors[a.id] = a
        return a

    def get_actor(self, aid):
        return self.actors.get(aid)

    def tick(self):
        assert self.settings.synchronous_mode and self.settings.fixed_delta_seconds == DT
        self.frame += 1
        for a in list(self.actors.values()):
            a.step()
        egos = [a for a in self.actors.values() if a.type_id == "vehicle.tesla.model3"]
        for a in list(self.actors.values()):
            if a.callback is None:
                continue
            if a.type_id == "sensor.camera.rgb":
                a.callback(_Image(self.frame))
            elif a.type_id == "sensor.other.collision":
                ego = a.parent
                for other in list(self.actors.values()):
                    if other is ego or other.parent is not None or other in egos:
                        continue
                    if other.type_id.startswith("sensor."):
                        continue
                    d = math.hypot(other.tf.location.x - ego.tf.location.x,
                                   other.tf.location.y - ego.tf.location.y)
                    if d < 1.2:
                        a.callback(types.SimpleNamespace(frame=self.frame, other_actor=other))
        return self.frame


class Client(object):
    world = None

    def __init__(self, host, port):
        if Client.world is None:
            Client.world = World()

    def set_timeout(self, t):
        pass

    def get_world(self):
        return Client.world

    def load_world(self, name):
        return Client.world

    def get_server_version(self):
        return "0.9.13-fake"

    def get_client_version(self):
        return "0.9.13-fake"

    def apply_batch_sync(self, cmds, do_tick=False):
        for c in cmds:
            Client.world.actors.pop(c.actor.id, None)
        if do_tick:
            Client.world.tick()
        return []


def install(monkeypatch):
    import sys
    Client.world = None
    monkeypatch.setitem(sys.modules, "carla", sys.modules[__name__])


__all__ = ["install", "os"]
