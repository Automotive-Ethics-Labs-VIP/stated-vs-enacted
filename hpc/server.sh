# Sourced by hpc/job.sbatch. Defines start_server PORT QUALITY LOGFILE (sets
# SERVER_PID) and stop_server.
#
# NOT FILLED IN YET: the launch logic must be copied from the working
# reference /gpfs/scratch/klow/carla/run_carla_headless.sh (LD_LIBRARY_PATH
# fix and preflight included). Until then the job fails here on purpose
# instead of guessing how to start CARLA.

CARLA_REF=/gpfs/scratch/klow/carla

start_server() {
  echo "hpc/server.sh: launch logic not copied from $CARLA_REF/run_carla_headless.sh yet" >&2
  return 1
}

stop_server() {
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "stopping server $SERVER_PID"
    kill "$SERVER_PID" 2>/dev/null
    for _ in 1 2 3 4 5; do kill -0 "$SERVER_PID" 2>/dev/null || return 0; sleep 2; done
    kill -9 "$SERVER_PID" 2>/dev/null
  fi
  # CarlaUE4 forks; make sure no child of this job keeps the GPU
  pkill -u "$(id -u)" -f "CarlaUE4.*carla-rpc-port=${PORT:-none}" 2>/dev/null || true
}
