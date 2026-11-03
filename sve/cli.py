"""python -m sve <command>

  grid GRID                     list the scenarios a grid expands to
  simulate --grid G --out DIR   run every scenario x action (FakeSim or CARLA)
  export-prompts --run DIR      write prompts/<condition>.jsonl
  import-responses --model M    validate responses/<model>/*.jsonl
  analyze --run DIR             tables, figures, report.md/report.html
  annotate --run DIR            label captured frames, build GIFs and key frames
  dryrun                        the whole loop with FakeSim and mock answers
"""

import argparse
import os
import shutil
import sys

from .llm import CONDITIONS, THEORIES, import_responses, load_prompts


def _sim(args):
    if args.sim == "fake":
        from .sim import FakeSim
        return FakeSim()
    from .sim.carla_sim import CarlaSim
    return CarlaSim(host=args.host, port=args.port, map_name=args.map, capture=args.capture,
                    timeout_s=args.timeout)


def cmd_grid(args):
    from .scenarios import expand_grid, load_grid
    for s in expand_grid(load_grid(args.grid)):
        print(s.id)


def cmd_simulate(args):
    from . import pipeline
    sim = _sim(args)
    try:
        pipeline.simulate(sim, args.grid, args.out, capture=args.capture,
                          determinism=args.determinism, repeats=args.repeats,
                          only=args.only.split(",") if args.only else None)
    finally:
        sim.close()
    print("wrote", args.out)


def cmd_export(args):
    from . import pipeline
    prompts = pipeline.export(args.run, args.out, args.conditions.split(","),
                              args.theories.split(","))
    total = sum(len(v) for v in prompts.values())
    for c, rows in prompts.items():
        print("{:<16} {:>4} prompts -> {}".format(c, len(rows), os.path.join(args.out, c + ".jsonl")))
    print("total", total)
    if total > 400:
        print("note: over 400 prompts; claude_cli refuses more than --max (default 400) per run")


def cmd_import(args):
    prompts = load_prompts(args.prompts)
    report = import_responses(prompts, args.responses, args.model)
    print(report.summary())
    if not report.ok and not args.allow_partial:
        print("import incomplete; fix the rows above or pass --allow-partial")
        return 1
    return 0


def cmd_analyze(args):
    from . import pipeline
    (md, html), _ = pipeline.analyze(args.run, args.responses, args.out, score=args.score)
    print("wrote", md)
    print("wrote", html)


def cmd_annotate(args):
    from .media import annotate
    annotate.process_run(args.run, max_gif_mb=args.max_gif_mb)


def cmd_dryrun(args):
    from . import pipeline
    from providers import mock
    from .sim import FakeSim
    out = args.out
    if os.path.isdir(out):
        shutil.rmtree(out)
    run_dir = os.path.join(out, "run")
    prompt_dir = os.path.join(out, "prompts")
    responses_dir = os.path.join(out, "responses")
    print("1/5 simulate (FakeSim)")
    pipeline.simulate(FakeSim(), args.grid, run_dir, determinism=2, log=lambda *_: None)
    print("2/5 export prompts")
    prompts = pipeline.export(run_dir, prompt_dir, CONDITIONS, args.theories.split(","))
    print("    {} prompts".format(sum(len(v) for v in prompts.values())))
    print("3/5 mock answers")
    mock.run(prompt_dir, responses_dir)
    print("4/5 import")
    report = import_responses(prompts, responses_dir, "mock")
    print("    " + report.summary())
    if not report.ok:
        return 1
    print("5/5 analyze")
    (md, html), _ = pipeline.analyze(run_dir, responses_dir, out)
    print("wrote", md)
    print("wrote", html)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m sve", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("grid")
    p.add_argument("grid")
    p.set_defaults(fn=cmd_grid)

    p = sub.add_parser("simulate")
    p.add_argument("--grid", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sim", choices=("fake", "carla"), default="fake")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--map", default=None, help="CARLA map; default: keep the loaded one")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--capture", action="store_true", help="save camera frames (CARLA only)")
    p.add_argument("--determinism", type=int, default=0,
                   help="re-run the first N scenarios --repeats times")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--only", help="comma-separated scenario ids")
    p.set_defaults(fn=cmd_simulate)

    p = sub.add_parser("export-prompts")
    p.add_argument("--run", required=True)
    p.add_argument("--out", default="prompts")
    p.add_argument("--conditions", default=",".join(CONDITIONS))
    p.add_argument("--theories", default="neutral",
                   help="comma-separated from: " + ", ".join(THEORIES))
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("import-responses")
    p.add_argument("--model", required=True)
    p.add_argument("--prompts", default="prompts")
    p.add_argument("--responses", default="responses")
    p.add_argument("--allow-partial", action="store_true")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("analyze")
    p.add_argument("--run", required=True)
    p.add_argument("--responses", default="responses")
    p.add_argument("--out", default="results")
    p.add_argument("--score", default="pedestrians")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("annotate")
    p.add_argument("--run", required=True)
    p.add_argument("--max-gif-mb", type=float, default=10.0)
    p.set_defaults(fn=cmd_annotate)

    p = sub.add_parser("dryrun")
    p.add_argument("--grid", default=os.path.join("grids", "smoke.json"))
    p.add_argument("--out", default=os.path.join("results", "dryrun"))
    p.add_argument("--theories", default="neutral")
    p.set_defaults(fn=cmd_dryrun)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
