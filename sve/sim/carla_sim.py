"""CarlaSim: run scenarios in a CARLA 0.9.13 server (Python 3.8, carla==0.9.13).

Synchronous mode, fixed_delta_seconds = 0.05. For every (scenario, action)
the scene is rebuilt from scratch: ego and stationary walkers are spawned,
left to settle for ``settle_ticks`` with the ego braked, then the ego gets
its t0 speed and the action's controller drives from the next tick.

The road frame is anchored on a straight stretch with a drivable lane on
each side (``find_section``): x along the lane, y to the right. People are
placed at the spec's offsets, with lateral offsets scaled from the spec's
lane width to the map's, so "in the left lane" stays true on any map.

Pedestrian attributes are metadata kept in a registry; the walker models
are generic (only child/adult blueprints are distinguished).
"""

import json
import math
import os
import queue

from ..scenarios.spec import person_positions
from .base import (DT, MAX_DURATION_S, PAST_MARGIN_M, TRAJECTORY_EVERY, Simulator,
                   detection, outcome_row)
from .controllers import ActionController, ControllerParams, swerve_completed
from .controllers import lost_control as is_lost

EGO_BLUEPRINT = "vehicle.tesla.model3"
OBSTACLE_BLUEPRINTS = {"barrier": "static.prop.streetbarrier", "vehicle": "vehicle.audi.a2",
                       "prop": "static.prop.trashcan01"}
CAMERA_W, CAMERA_H = 1280, 720
SAVE_EVERY = 2          # ticks between saved frames (10 fps)
STOPPED_MPS = 0.1
STOPPED_TICKS = 10


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class RoadFrame(object):
    """Maps road-frame (x forward, y right) to world coordinates and back."""

    def __init__(self, origin_xyz, yaw_deg):
        self.ox, self.oy, self.oz = origin_xyz
        self.yaw_deg = yaw_deg
        yaw = math.radians(yaw_deg)
        self.fx, self.fy = math.cos(yaw), math.sin(yaw)
        self.rx, self.ry = -math.sin(yaw), math.cos(yaw)  # CARLA is left-handed: +y is right

    def to_world(self, x, y):
        return (self.ox + self.fx * x + self.rx * y, self.oy + self.fy * x + self.ry * y)

    def to_road(self, wx, wy):
        dx, dy = wx - self.ox, wy - self.oy
        return (dx * self.fx + dy * self.fy, dx * self.rx + dy * self.ry)

    def heading(self, yaw_deg):
        return _wrap(math.radians(yaw_deg - self.yaw_deg))


def _same_direction_driving(wp, other, driving):
    return (other is not None and other.lane_type == driving
            and (other.lane_id > 0) == (wp.lane_id > 0))


def find_section(cmap, driving, length_m=80.0, step_m=2.0, want_width=3.5, max_yaw_change_deg=1.5):
    """First (in a fixed order) straight stretch with drivable lanes on both sides.

    Prefers lanes whose width is close to ``want_width``. Returns
    (waypoint, info dict) or raises RuntimeError.
    """
    candidates = []
    for wp in cmap.generate_waypoints(step_m):
        if wp.lane_type != driving or wp.is_junction:
            continue
        if not (_same_direction_driving(wp, wp.get_left_lane(), driving)
                and _same_direction_driving(wp, wp.get_right_lane(), driving)):
            continue
        candidates.append(wp)
    candidates.sort(key=lambda w: (abs(w.lane_width - want_width) > 0.3, w.road_id,
                                   w.section_id, w.lane_id, round(w.s, 1)))
    for wp in candidates:
        yaw0 = wp.transform.rotation.yaw
        cur, ok, dist = wp, True, 0.0
        while dist < length_m:
            nxt = cur.next(step_m)
            if len(nxt) != 1:
                ok = False
                break
            cur = nxt[0]
            dist += step_m
            if (cur.is_junction or abs(_wrap(math.radians(cur.transform.rotation.yaw - yaw0)))
                    > math.radians(max_yaw_change_deg)
                    or abs(cur.lane_width - wp.lane_width) > 0.2
                    or not _same_direction_driving(cur, cur.get_left_lane(), driving)
                    or not _same_direction_driving(cur, cur.get_right_lane(), driving)):
                ok = False
                break
        if ok:
            loc = wp.transform.location
            return wp, {"road_id": wp.road_id, "section_id": wp.section_id,
                        "lane_id": wp.lane_id, "s": round(wp.s, 2),
                        "lane_width_m": round(wp.lane_width, 3),
                        "origin": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
                        "yaw_deg": round(wp.transform.rotation.yaw, 3)}
    raise RuntimeError("no straight {:.0f} m stretch with lanes on both sides".format(length_m))


class CarlaSim(Simulator):
    name = "carla"

    def __init__(self, host="localhost", port=2000, map_name=None, capture=False,
                 timeout_s=60.0, settle_ticks=30, section_length_m=80.0, controller_params=None):
        import carla  # only needed here, so the rest of the package works without it
        self.carla = carla
        self.capture = capture
        self.settle_ticks = settle_ticks
        self.client = carla.Client(host, port)
        self.client.set_timeout(timeout_s)
        world = self.client.get_world()
        if map_name and not world.get_map().name.endswith(map_name):
            world = self.client.load_world(map_name)
        self.world = world
        self._original_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = DT
        settings.no_rendering_mode = not capture
        world.apply_settings(settings)
        world.tick()
        self.map = world.get_map()
        self.section_wp, section = find_section(self.map, carla.LaneType.Driving,
                                                     section_length_m)
        loc = self.section_wp.transform.location
        self.frame = RoadFrame((loc.x, loc.y, loc.z), self.section_wp.transform.rotation.yaw)
        self.lane_width = self.section_wp.lane_width
        self.cp = controller_params
        self._actors = []
        self.info = {"map": self.map.name, "section": section,
                     "server_version": self.client.get_server_version(),
                     "client_version": self.client.get_client_version(),
                     "settle_ticks": settle_ticks, "capture": capture}

    # ---- scene ----------------------------------------------------------

    def _blueprint(self, pattern, age=None):
        bps = sorted(self.world.get_blueprint_library().filter(pattern), key=lambda b: b.id)
        if age is not None:
            matching = [b for b in bps if b.has_attribute("age")
                        and b.get_attribute("age").as_str() == age]
            bps = matching or bps
        if not bps:
            raise RuntimeError("no blueprint matches {}".format(pattern))
        bp = bps[0]
        if bp.has_attribute("is_invincible"):
            bp.set_attribute("is_invincible", "false")
        if bp.has_attribute("role_name"):
            bp.set_attribute("role_name", "sve")
        return bp

    def _transform(self, x, y, z_up, yaw_offset=0.0):
        carla = self.carla
        wx, wy = self.frame.to_world(x, y)
        return carla.Transform(carla.Location(x=wx, y=wy, z=self.frame.oz + z_up),
                               carla.Rotation(yaw=self.frame.yaw_deg + yaw_offset))

    def _spawn(self, bp, x, y, z_up, attach_to=None):
        for extra in (0.0, 0.3, 0.6, 1.0):
            actor = self.world.try_spawn_actor(bp, self._transform(x, y, z_up + extra))
            if actor is not None:
                self._actors.append(actor)
                return actor
        raise RuntimeError("could not spawn {} at x={:.1f} y={:.1f}".format(bp.id, x, y))

    def _scale_y(self, scenario, y):
        return y * self.lane_width / scenario.lane_width_m

    def _setup(self, scenario):
        """Spawn ego, walkers and obstacles; settle. Returns the scene dict."""
        carla = self.carla
        self._destroy()
        ego = self._spawn(self._blueprint(EGO_BLUEPRINT), 0.0, 0.0, 0.5)
        walkers = {}
        for g in scenario.groups:
            age = "child" if g.attributes.get("age_group") == "child" else "adult"
            bp_w = self._blueprint("walker.pedestrian.*", age=age)
            for i, (px, py) in enumerate(person_positions(g)):
                w = self._spawn(bp_w, px, self._scale_y(scenario, py), 1.0)
                walkers[w.id] = (g.id, i, g.attributes)
        obstacles = {}
        for o in scenario.obstacles:
            a = self._spawn(self._blueprint(OBSTACLE_BLUEPRINTS[o.type]), o.distance_m,
                            self._scale_y(scenario, o.lateral_m), 0.3)
            obstacles[a.id] = o
        for _ in range(self.settle_ticks):
            ego.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
            self.world.tick()
        return {"ego": ego, "walkers": walkers, "obstacles": obstacles}

    def _destroy(self):
        if not self._actors:
            return
        sensors = [a for a in self._actors if a.type_id.startswith("sensor.")]
        for s in sensors:
            try:
                s.stop()
            except RuntimeError:
                pass
        cmds = [self.carla.command.DestroyActor(a) for a in sensors + [
            a for a in self._actors if not a.type_id.startswith("sensor.")]]
        self.client.apply_batch_sync(cmds, True)
        self._actors = []

    def _launch(self, ego, speed):
        """Give the ego its t0 velocity along the lane and release the brakes."""
        carla = self.carla
        ego.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, 0.0))
        ego.set_target_velocity(carla.Vector3D(self.frame.fx * speed, self.frame.fy * speed, 0.0))
        ego.apply_control(carla.VehicleControl(throttle=0.0, brake=0.0, hand_brake=False))

    def _state(self, ego):
        tf = ego.get_transform()
        vel = ego.get_velocity()
        x, y = self.frame.to_road(tf.location.x, tf.location.y)
        return x, y, self.frame.heading(tf.rotation.yaw), math.hypot(vel.x, vel.y)

    def _controller_params(self, ego):
        if self.cp is not None:
            return self.cp
        phys = ego.get_physics_control()
        wheels = phys.wheels
        # wheel positions are world coordinates in centimetres in 0.9.13
        wheelbase = math.hypot(wheels[0].position.x - wheels[2].position.x,
                               wheels[0].position.y - wheels[2].position.y) / 100.0
        return ControllerParams(wheelbase_m=wheelbase or 2.9,
                                max_steer_rad=math.radians(wheels[0].max_steer_angle))

    # ---- observation ----------------------------------------------------

    def observe(self, scenario):
        scene = self._setup(scenario)
        ego = scene["ego"]
        self._launch(ego, scenario.ego_speed_mps)
        self.world.tick()
        tf = ego.get_transform()
        vel = ego.get_velocity()
        yaw = math.radians(tf.rotation.yaw)
        fx, fy, rx, ry = math.cos(yaw), math.sin(yaw), -math.sin(yaw), math.cos(yaw)

        def rel(actor):
            loc = actor.get_location()
            dx, dy = loc.x - tf.location.x, loc.y - tf.location.y
            return dx * fx + dy * fy, dx * rx + dy * ry

        people = []
        for aid, (_, _, attrs) in scene["walkers"].items():
            f, r = rel(self.world.get_actor(aid))
            people.append((f, r, attrs))
        detections = [detection("w%d" % (i + 1), "walker", f, r, attrs)
                      for i, (f, r, attrs) in enumerate(sorted(people, key=lambda p: (p[0], p[1])))]
        for i, (aid, o) in enumerate(sorted(scene["obstacles"].items())):
            f, r = rel(self.world.get_actor(aid))
            detections.append(detection("o%d" % (i + 1), "static", f, r, {"type": o.type}))
        wp = self.map.get_waypoint(tf.location)
        left = right = 0
        cur = wp
        driving = self.carla.LaneType.Driving
        while _same_direction_driving(wp, cur.get_left_lane(), driving):
            cur = cur.get_left_lane()
            left += 1
        cur = wp
        while _same_direction_driving(wp, cur.get_right_lane(), driving):
            cur = cur.get_right_lane()
            right += 1
        obs = {
            "scenario_id": scenario.id,
            "sim": self.name,
            "ego": {"speed_mps": math.hypot(vel.x, vel.y),
                    "heading_deg": math.degrees(self.frame.heading(tf.rotation.yaw)),
                    "lane_index": left + 1, "lanes_total": left + right + 1,
                    "lane_width_m": wp.lane_width,
                    "left_lane_available": left > 0, "right_lane_available": right > 0},
            "detections": detections,
        }
        self._destroy()
        return obs

    # ---- one run --------------------------------------------------------

    def _cameras(self, ego, scenario, run_dir):
        carla = self.carla
        far = max([g.distance_m for g in scenario.groups]
                  + [o.distance_m for o in scenario.obstacles] + [10.0])
        cams = {}
        lib = self.world.get_blueprint_library()

        def bp(fov):
            b = lib.find("sensor.camera.rgb")
            b.set_attribute("image_size_x", str(CAMERA_W))
            b.set_attribute("image_size_y", str(CAMERA_H))
            b.set_attribute("fov", str(fov))
            return b

        # Top-down, fixed in the world: image right = road forward, image up = road left.
        cx = far / 2.0 + 4.0
        wx, wy = self.frame.to_world(cx, 0.0)
        top_tf = carla.Transform(carla.Location(x=wx, y=wy, z=self.frame.oz + 40.0),
                                 carla.Rotation(pitch=-90.0, yaw=self.frame.yaw_deg - 90.0))
        top = self.world.spawn_actor(bp(90), top_tf)
        self._actors.append(top)
        chase = self.world.spawn_actor(
            bp(90), carla.Transform(carla.Location(x=-8.0, z=4.0), carla.Rotation(pitch=-15.0)),
            attach_to=ego, attachment_type=carla.AttachmentType.Rigid)
        self._actors.append(chase)
        for name, cam in (("top", top), ("chase", chase)):
            q = queue.Queue()
            cam.listen(q.put)
            os.makedirs(os.path.join(run_dir, name), exist_ok=True)
            cams[name] = {"actor": cam, "queue": q, "fov": 90.0}
        return cams

    @staticmethod
    def _frame_from(q, frame_id, timeout=10.0):
        while True:
            image = q.get(timeout=timeout)
            if image.frame == frame_id:
                return image
            if image.frame > frame_id:
                raise RuntimeError("camera skipped frame {}".format(frame_id))

    def run(self, scenario, action, capture_dir=None):
        carla = self.carla
        scene = self._setup(scenario)
        ego = scene["ego"]
        events = []
        col_bp = self.world.get_blueprint_library().find("sensor.other.collision")
        col = self.world.spawn_actor(col_bp, carla.Transform(), attach_to=ego)
        self._actors.append(col)
        col.listen(lambda e: events.append((e.frame, e.other_actor.id, e.other_actor.type_id)))

        capture = self.capture and capture_dir is not None
        run_dir = os.path.join(capture_dir, "frames", "{}_{}".format(scenario.id, action)) \
            if capture else None
        cams = self._cameras(ego, scenario, run_dir) if capture else {}
        meta_frames = []

        lane_w = self.lane_width
        ctrl = ActionController(action, scenario.ego_speed_mps, lane_w,
                                self._controller_params(ego))
        far = max([g.distance_m for g in scenario.groups]
                  + [o.distance_m for o in scenario.obstacles] + [0.0])
        self._launch(ego, scenario.ego_speed_mps)
        speeds = {}
        trajectory = []
        swerve_done = swerve_completed(action, 0.0, 0.0, lane_w)
        lost = False
        stopped = 0
        initial_speed = None
        t, tick = 0.0, 0
        while t < MAX_DURATION_S - 1e-9:
            frame_id = self.world.tick()
            t += DT
            tick += 1
            x, y, psi, v = self._state(ego)
            speeds[frame_id] = v
            if initial_speed is None:
                initial_speed = v
                trajectory.append([0.0, x, y, v])
            if tick % TRAJECTORY_EVERY == 0:
                trajectory.append([round(t, 3), x, y, v])
            if capture and tick % SAVE_EVERY == 0:
                idx = len(meta_frames)
                entry = {"i": idx, "t": round(t, 3), "frame": frame_id, "x": x, "y": y,
                         "speed_mps": v}
                for name, cam in cams.items():
                    image = self._frame_from(cam["queue"], frame_id)
                    image.save_to_disk(os.path.join(run_dir, name, "%04d.png" % idx))
                    entry[name + "_world_to_camera"] = [
                        list(r) for r in cam["actor"].get_transform().get_inverse_matrix()]
                meta_frames.append(entry)
            elif capture:
                for cam in cams.values():  # drain unsaved frames
                    self._frame_from(cam["queue"], frame_id)
            lost = lost or is_lost(y, psi, lane_w)
            if swerve_done is False and swerve_completed(action, y, psi, lane_w):
                swerve_done = True
            stopped = stopped + 1 if v < STOPPED_MPS else 0
            if stopped >= STOPPED_TICKS or x > far + PAST_MARGIN_M:
                break
            u = ctrl(y, psi, v, DT)
            ego.apply_control(carla.VehicleControl(throttle=u.throttle, steer=u.steer,
                                                   brake=u.brake))
        x, y, psi, v = self._state(ego)
        if trajectory[-1][0] != round(t, 3):
            trajectory.append([round(t, 3), x, y, v])
        col.stop()

        hits, obstacles_hit, seen = [], [], set()
        frames_sorted = sorted(speeds)
        for frame_id, other_id, type_id in sorted(events):
            if other_id in seen:
                continue
            seen.add(other_id)
            before = [f for f in frames_sorted if f <= frame_id] or frames_sorted[:1]
            impact = speeds[before[-1]] if before else None
            hit_t = round((frames_sorted.index(before[-1]) + 1) * DT, 3) if before else None
            if other_id in scene["walkers"]:
                gid, i, _ = scene["walkers"][other_id]
                hits.append({"group_id": gid, "person": i, "t": hit_t,
                             "impact_speed_mps": impact})
            elif other_id in scene["obstacles"]:
                obstacles_hit.append(scene["obstacles"][other_id].id)
            else:
                obstacles_hit.append("env:" + type_id)

        if capture:
            labels = []
            for aid, (gid, i, attrs) in scene["walkers"].items():
                loc = self.world.get_actor(aid).get_location()
                labels.append({"group_id": gid, "person": i, "attributes": attrs,
                               "world": [loc.x, loc.y, loc.z]})
            with open(os.path.join(run_dir, "meta.json"), "w") as f:
                json.dump({"scenario_id": scenario.id, "action": action, "fps": 1.0 / (DT * SAVE_EVERY),
                           "width": CAMERA_W, "height": CAMERA_H,
                           "cameras": dict((n, {"fov": c["fov"]}) for n, c in cams.items()),
                           "labels": labels, "frames": meta_frames}, f)
        self._destroy()
        final = {"x": x, "y": y, "heading_deg": math.degrees(psi), "speed_mps": v}
        return outcome_row(scenario, action, self.name, initial_speed, hits, obstacles_hit,
                           swerve_done, lost, final, round(t, 3), trajectory)

    def close(self):
        try:
            self._destroy()
        finally:
            self.world.apply_settings(self._original_settings)
