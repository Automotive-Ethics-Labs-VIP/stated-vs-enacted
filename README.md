# stated-vs-enacted

Do text-based moral judgments predict behavior in simulated driving? For the same dilemma, an LLM chooses an action from a text description (**stated**) and from a structured readout of the CARLA simulation at the decision point (**enacted**). Both choices are scored against the measured outcome of every action.

This is a pilot: the goal is a working end-to-end loop, not breadth. See [PLAN.md](PLAN.md) for milestones and [docs/conditions.md](docs/conditions.md) for how the two prompt types differ.

## The loop

```
grids/*.json ──expand──▶ scenarios ──simulate (FakeSim or CARLA, all 4 actions)──▶ outcomes + t0 observations
                                                                                          │
 stated prompts ◀── text templates (spec)          enacted prompts ◀── observation renderer
        └──────────────▶ prompts/<condition>.jsonl ◀──────────────┘
                                   │  answered blind by providers/ (outside the core library)
                                   ▼
                 responses/<model>/<condition>.jsonl ──import (validated)──▶ analyze ──▶ report.md / report.html
```

The four actions are `maintain`, `brake`, `swerve_left` and `swerve_right`. LLM choices are never executed: each one is looked up in `outcomes.jsonl`, where every action was already simulated.

## Run it locally (no CARLA)

Needs Python 3.8 or newer. The analysis also needs `matplotlib` and `Pillow`.

```bash
pip install matplotlib Pillow pytest
python -m pytest                 # ~100 tests, about a minute
python -m sve dryrun             # whole loop with FakeSim and mock answers
```

The dry run writes `results/dryrun/report.html`. Open it in a browser. It is marked "pipeline test, not a result".

Step by step:

```bash
python -m sve simulate --grid grids/smoke.json --out results/local       # FakeSim
python -m sve export-prompts --run results/local                         # -> prompts/
python -m providers.mock                                                 # or claude_cli / manual
python -m sve import-responses --model mock
python -m sve analyze --run results/local                                # -> results/report.html
```

## Answering prompts

The core library never calls a model. Answers come from `providers/`:

| Provider | Use |
|---|---|
| `python -m providers.mock` | Deterministic dummy answers, for tests and dry runs |
| `python -m providers.manual write` / `collect` | Paste prompts into a chat yourself, then paste the replies back |
| `python -m providers.claude_cli --model sonnet` | Headless Claude Code, blind: empty temp dir, no tools, no CLAUDE.md, memory, skills, hooks or MCP. Uses your Claude Code login and your usage |

`claude_cli` caches answers by (model, prompt hash). It asks before more than 100 calls and refuses more than `--max` (default 400).

**Blindness rule:** whoever answers must never see outcomes, specs, this repo, or another condition's prompt. A Claude Code session working in this repo has seen all of that, so it must never answer prompts itself.

## Run it on SeaWulf (CARLA)

See [RUNBOOK.md](RUNBOOK.md). In short: log in yourself with `ssh seawulf` (password and Duo), then:

```bash
hpc/run.sh sync
hpc/run.sh submit grids/smoke.json --capture --determinism 2
hpc/run.sh status
hpc/run.sh fetch <jobid>
```

## Layout

| Path | What |
|---|---|
| `sve/scenarios` | Scenario spec and grid expansion |
| `sve/sim` | Shared controllers, FakeSim (kinematic bicycle), CarlaSim |
| `sve/text` | Stated prompts: templates over the spec |
| `sve/observe` | Enacted prompts: readout of the t0 observation |
| `sve/llm` | Prompt export, response validation and import |
| `sve/analysis` | Scores, metrics, figures, report |
| `sve/media` | Annotates captured CARLA frames; builds GIFs and key frames |
| `providers/` | Answer providers (mock, manual, claude_cli) |
| `hpc/` | Slurm job and local wrapper |
| `grids/` | `smoke.json` (4 scenarios) and `full.json` (draft, needs approval) |

Outputs (`results/`, `prompts/`, `responses/`, `manual/`, `.cache/`) are git-ignored.
