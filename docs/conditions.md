# How the STATED and ENACTED prompts differ

Every prompt shares one wrapper: the task line, the action menu, the optional theory line, and the answer format. Only the `SITUATION:` block differs. This page lists every difference in that block, so a gap between conditions can be traced to its cause.

| | STATED (`stated-abstract`, `stated-detailed`) | ENACTED (`enacted`) |
|---|---|---|
| Source | The scenario spec: what the author intended | The simulator's t0 snapshot (`observations.jsonl`): what was measured |
| Code path | `sve/text/render.py` (templates) | `sve/observe/render.py` (fixed-format readout) |
| Form | English sentences | A table, one line per object; no sentences |
| People | Grouped: "two adults are standing in your lane" | One line per person, e.g. `w2 walker 15.0 -1 15.0 -0.3 age_group=adult` |
| Attributes | Words: "child", "elderly person", "who uses a wheelchair" | Tags: `age_group=child`, `disability=wheelchair` |
| Position | By lane ("in the lane to your left"); detailed adds distance and offset from your path | Range and bearing from the ego's centre, plus forward/right offsets; no lane names for objects |
| Numbers | Abstract: none. Detailed: speed (m/s and km/h), distance, lateral offset, lane width, as authored | Speed, heading, lane index (`2/3`, 1 = leftmost), lane width; positions rounded to 0.1 m and 1° |
| Precision | Exact, as authored (e.g. 3.5 m) | As measured. In CARLA: offsets are scaled to the map's lane width, people settle after spawning, and the ego has already moved for one tick (0.05 s) |
| Empty lanes | Said explicitly ("The lane to your right is clear.") | Only implied by the absence of objects; the lane is listed as `drivable` |
| Ego lane | "in the middle lane" | `lane=2/3` |

With FakeSim, the enacted positions equal the spec exactly, so only the form differs. With CarlaSim, the measurement differences above also apply.

What the conditions deliberately share: the action names and their one-line meanings, the theory line, and the answer format. None of them mentions outcomes, collisions, or which action is best.
