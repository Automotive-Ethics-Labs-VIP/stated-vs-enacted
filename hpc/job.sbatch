#!/usr/bin/env bash
#SBATCH --job-name=sve-sim
#SBATCH --account=pn_wosc091525s
#SBATCH --partition=a100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/sve-%j.out
#
# Usage (from /gpfs/scratch/klow/stated-vs-enacted):
#   sbatch hpc/job.sbatch grids/smoke.json [--capture] [--determinism N] [--map Town04]
#
# Starts a headless CARLA server, waits for its port, runs the harness for
# the grid, writes results/<jobid>/, always kills the server, and ends with
# a DONE or FAILED line.
set -uo pipefail

ROOT=/gpfs/scratch/klow/stated-vs-enacted
cd "$ROOT" || { echo "FAILED: no $ROOT"; exit 1; }
GRID=${1:?usage: sbatch hpc/job.sbatch GRID [ARGS]}
shift
EXTRA=("$@")
JOB=${SLURM_JOB_ID:-$$}
OUT=$ROOT/results/$JOB
mkdir -p "$OUT" logs

QUALITY=Low
for a in "${EXTRA[@]}"; do [ "$a" = "--capture" ] && QUALITY=${SVE_CAPTURE_QUALITY:-Epic}; done

PORT=$(( 2000 + (JOB % 400) * 3 ))   # spread ports so two jobs on a node don't collide
SERVER_PID=""

# shellcheck source=hpc/server.sh
source "$ROOT/hpc/server.sh"   # defines start_server PORT QUALITY LOGFILE and stop_server

cleanup() {
  stop_server
}
trap cleanup EXIT
trap 'echo "FAILED: job $JOB interrupted"; exit 1' INT TERM

echo "job $JOB on $(hostname) at $(date -Is)"
echo "grid $GRID args ${EXTRA[*]:-} port $PORT quality $QUALITY"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader || true

start_server "$PORT" "$QUALITY" "$OUT/carla_server.log" || { echo "FAILED: server did not start"; exit 1; }

echo "waiting for port $PORT"
for i in $(seq 1 90); do
  if (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then echo "port open after ${i}x2 s"; break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then echo "FAILED: server exited early"; tail -n 40 "$OUT/carla_server.log"; exit 1; fi
  sleep 2
  [ "$i" = 90 ] && { echo "FAILED: port $PORT never opened"; tail -n 40 "$OUT/carla_server.log"; exit 1; }
done
sleep 10   # the RPC port opens before the world is ready

module load anaconda/3
conda activate ael-carla
python -V

python -m sve simulate --sim carla --port "$PORT" --timeout 120 --grid "$GRID" --out "$OUT" "${EXTRA[@]}"
status=$?
if [ $status -eq 0 ] && python -c "import PIL" 2>/dev/null && [ -d "$OUT/media/frames" ]; then
  python -m sve annotate --run "$OUT" || echo "annotation failed; run it locally after fetching frames"
fi

if [ $status -eq 0 ]; then
  echo "DONE: job $JOB wrote $OUT at $(date -Is)"
else
  echo "FAILED: harness exited with $status"
fi
exit $status
