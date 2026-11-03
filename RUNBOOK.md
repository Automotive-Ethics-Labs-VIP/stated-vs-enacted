# Runbook: SeaWulf

## Connecting

1. **You** log in: run `ssh seawulf`, enter your password, type `1` at the Duo prompt, and approve the push. Keep that terminal open.
2. Every scripted call reuses that connection (ControlMaster) with `-o BatchMode=yes -o ConnectTimeout=15`, so it fails at once instead of prompting.
3. Check it: `hpc/run.sh check`. If it fails, log in again (step 1).
4. Submitted jobs keep running when the connection drops. After reconnecting, run `hpc/run.sh status` before doing anything else.

Passwords are never written anywhere: not in files, scripts, environment variables or git.

## Where things are

| Path | What |
|---|---|
| `/gpfs/scratch/klow/stated-vs-enacted/` | This repo (synced) plus `results/<jobid>/` and `logs/`. The only place we write |
| `/gpfs/scratch/klow/carla/` | **Read-only reference.** `carla_rootfs/`, `run_carla_headless.sh` |
| conda env `ael-carla` | Python 3.8 + carla 0.9.13: `module load anaconda/3 && conda activate ael-carla` |

## Commands

```bash
hpc/run.sh sync                                   # code only; results are never pushed up
hpc/run.sh submit grids/smoke.json --capture --determinism 2
hpc/run.sh status                                 # squeue, plus --start estimates
hpc/run.sh logs <jobid>                           # job log plus the server log tail
hpc/run.sh fetch <jobid>                          # results and GIFs; add --frames for raw PNGs
python -m sve annotate --run results/<jobid>      # if Pillow wasn't available on the node
```

Job resources (`hpc/job.sbatch`): `-A pn_wosc091525s -p a100 --gres=gpu:1 -c 8 --mem=32G -t 02:00:00`. Jobs are named `sve-sim`. The job ends with a line starting `DONE:` or `FAILED:`.

## Gotchas

- **`sbatch` can print "Socket timed out" and still create the job.** Never retry blindly: `hpc/run.sh submit` checks `squeue` instead. Never loop sbatch.
- **a100 allows 2 jobs per user**, and the queue can take hours. Check `squeue -u klow --start`.
- **`squeue`/`sacct` can time out.** They're read-only, so `run.sh` retries them a few times.
- **Only cancel your own `sve-` jobs.**
- **Compute nodes have no internet.** No pip installs in jobs, and no LLM calls on the cluster.
- **The RPC port opens before the world is ready**, so the job waits 10 s more after the port opens.
- **`--capture` renders**, so it turns off `no_rendering_mode` and uses `-quality-level=Epic`. Use it on the smoke grid and chosen scenarios only, never on the full grid without approval.
