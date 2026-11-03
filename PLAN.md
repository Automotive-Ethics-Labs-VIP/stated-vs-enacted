# Plan

Pilot: do text-based moral judgments (STATED) predict choices made from simulated observations (ENACTED)? Both are scored against the physical outcome of every action, measured in simulation. A working end-to-end loop matters more than breadth.

## Milestones and acceptance checks

| # | Milestone | Done when |
|---|---|---|
| M1 | FakeSim, scenario grid, text and observation renderers, prompt export/import, mock provider, analysis, report | `pytest` passes; `python -m sve dryrun` runs grid → FakeSim → prompts → mock answers → import → analysis → `report.md`/`report.html` with figures |
| M2 | CarlaSim on SeaWulf, smoke grid | Smoke job prints DONE. Braking from 12–14 m/s stops in roughly v²/2a (a ≈ 7–9 m/s²). A pedestrian in the path registers a collision. Swerves are completed or honestly reported as unstable. Determinism: 3 repeats agree. `--capture` gives non-blank (pixel variance check), annotated images for ≥2 scenarios × 4 actions, and I have looked at them |
| M3 | Real answers | Prompts exported for the smoke grid with the count reported. **User approves** before `claude_cli` runs. Responses import cleanly; analysis runs |
| M4 | Report | `results/report.md` + `report.html` from smoke results, with an honest summary of what it shows and what it doesn't |
| M5 | Full grid proposal | Grid size, expected queue time and prompt count proposed; **wait for approval** before submitting |

## Design decisions

- **One package, `sve/`**, with subpackages `scenarios`, `sim`, `text`, `observe`, `llm`, `analysis`, `media`. The answer providers live outside it in `providers/`, so the core library never calls a model.
- **Shared road frame.** Both sims report positions as `x` metres forward and `y` metres right of the ego's start. This is CARLA's left-handed convention, so it needs no sign flips.
- **One controller, two plants.** The steering (pure pursuit) and speed (PI) controllers in `sve/sim/controllers.py` drive both FakeSim (a kinematic bicycle model) and CarlaSim. That lets the controller be developed and tested locally before any HPC time.
- **Decision moment = t0.** Each run spawns everything fresh, lets it settle with the brake on, then gives the ego its speed and applies the action from the first tick. The 4 actions start from the same initial state.
- **Stdlib only on the CARLA side.** Simulation needs only `carla`. Frames are saved with CARLA's own PNG writer. Pillow and matplotlib are needed only for annotation and figures, which can run locally.
- **JSON everywhere** (no YAML), so the HPC conda env needs nothing extra.

## Risks

| Risk | Mitigation |
|---|---|
| Swerve controller unstable in CARLA | Tune on the smoke grid. Record `lost_control` and `swerve_completed`, and report them honestly |
| Speed not exactly v at t0 (spawn settling, physics) | Record the measured initial speed in every outcome row and check it |
| Walkers don't register collisions or fall over on spawn | Spawn slightly above ground, settle for 1 s, and check the collision sensor on the smoke grid |
| Queue waits on a100 (2 jobs max) | Small smoke grid; check `squeue --start`; never loop sbatch |
| Frame volume with `--capture` | Save every 2nd tick (10 fps), capture only on the smoke grid, fetch GIFs and key frames by default |
| No Pillow in the HPC env | Annotate and build GIFs locally after fetching frames |
| LLM answers contaminated | Headless `claude -p` in an empty temp dir with tools disabled; this session never answers prompts |
