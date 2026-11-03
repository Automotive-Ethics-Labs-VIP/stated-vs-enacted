#!/usr/bin/env bash
# Local wrapper for SeaWulf. Every call reuses your open `ssh seawulf`
# connection (ControlMaster) and fails fast instead of prompting.
#
#   hpc/run.sh check                 is the shared connection up?
#   hpc/run.sh sync                  rsync the repo to scratch (code only)
#   hpc/run.sh submit GRID [ARGS]    sbatch hpc/job.sbatch GRID ARGS, record the job id
#   hpc/run.sh status                squeue for your jobs (with start estimates)
#   hpc/run.sh logs JOBID            tail the job's log
#   hpc/run.sh fetch JOBID [--frames]  rsync results/JOBID back (frames only if asked)
#
# Set SVE_SSH to override the ssh command (default: ssh).
set -euo pipefail

HOST=${SVE_HOST:-seawulf}
REMOTE=${SVE_REMOTE:-/gpfs/scratch/klow/stated-vs-enacted}
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)
SSH=${SVE_SSH:-ssh}
HERE=$(cd "$(dirname "$0")/.." && pwd)

remote() { $SSH "${SSH_OPTS[@]}" "$HOST" "$@"; }

need_connection() {
  if ! remote hostname >/dev/null 2>&1; then
    echo "No open connection to $HOST."
    echo "Run \`ssh $HOST\` in your terminal, enter your password, type 1, approve Duo, then tell me to continue."
    exit 2
  fi
}

retry() {  # read-only Slurm queries time out sometimes; retry them
  local n
  for n in 1 2 3 4; do
    if out=$(remote "$@" 2>&1); then echo "$out"; return 0; fi
    echo "($* failed, attempt $n: ${out##*$'\n'})" >&2
    sleep $((n * 5))
  done
  return 1
}

cmd=${1:-}
shift || true
case "$cmd" in
  check)
    need_connection
    remote hostname
    ;;
  sync)
    need_connection
    remote "mkdir -p '$REMOTE'"
    rsync -az --delete \
      -e "$SSH -o BatchMode=yes -o ConnectTimeout=15" \
      --exclude .git --exclude results --exclude prompts --exclude responses \
      --exclude manual --exclude .cache --exclude __pycache__ --exclude .pytest_cache \
      --exclude hpc/last_job_id \
      "$HERE/" "$HOST:$REMOTE/"
    echo "synced to $HOST:$REMOTE"
    ;;
  submit)
    need_connection
    grid=${1:?usage: run.sh submit GRID [ARGS]}
    shift
    # Never retry sbatch blindly: it can time out and still create the job.
    if ! out=$(remote "cd '$REMOTE' && sbatch --parsable hpc/job.sbatch '$grid' $*" 2>&1); then
      echo "sbatch reported an error:"
      echo "$out"
      echo "It may still have created a job. Checking the queue instead of retrying:"
      retry squeue -u klow -o "'%.10i %.20j %.8T %.10M %R'" || true
      exit 1
    fi
    jobid=${out%%;*}
    echo "$jobid" > "$HERE/hpc/last_job_id"
    echo "submitted job $jobid ($grid $*)"
    ;;
  status)
    need_connection
    retry squeue -u klow -o "'%.10i %.20j %.8T %.10M %.20S %R'"
    retry squeue -u klow --start || true
    ;;
  logs)
    need_connection
    jobid=${1:-$(cat "$HERE/hpc/last_job_id")}
    remote "tail -n ${LINES:-80} '$REMOTE/logs/sve-$jobid.out'; echo; echo '--- server log tail ---'; tail -n 20 '$REMOTE/results/$jobid/carla_server.log' 2>/dev/null || true"
    ;;
  fetch)
    need_connection
    jobid=${1:-$(cat "$HERE/hpc/last_job_id")}
    excludes=(--exclude 'media/frames/')
    [ "${2:-}" = "--frames" ] && excludes=()
    mkdir -p "$HERE/results/$jobid"
    rsync -az -e "$SSH -o BatchMode=yes -o ConnectTimeout=15" "${excludes[@]}" \
      "$HOST:$REMOTE/results/$jobid/" "$HERE/results/$jobid/"
    echo "fetched to results/$jobid"
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
