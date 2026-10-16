#!/bin/sh
# Replay the synthetic league in examples/synthetic and print a short summary.
#
# Usage, from any directory:  sh scripts/quickstart.sh [output-directory]
#
# It needs only Python 3.11 or later; nothing is installed. Outputs go to
# data/local/quickstart/ by default, which Git ignores. To use a different
# interpreter, set PYTHON, for example: PYTHON=python3.12 sh scripts/quickstart.sh
set -eu

python=${PYTHON:-python3}
out=${1:-}
case $out in
    "" | /*) ;;
    *) out="$PWD/$out" ;;  # A relative path you pass is relative to where you run the script.
esac

cd "$(dirname "$0")/.."
root=$PWD
out=${out:-$root/data/local/quickstart}

if ! command -v "$python" > /dev/null 2>&1; then
    echo "The quickstart needs Python 3.11 or later, and '$python' was not found." >&2
    echo "To pick another interpreter, run: PYTHON=python3.12 sh scripts/quickstart.sh" >&2
    exit 2
fi
if ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "The quickstart needs Python 3.11 or later. '$python' is $("$python" -V 2>&1)." >&2
    echo "To pick another interpreter, run: PYTHON=python3.12 sh scripts/quickstart.sh" >&2
    exit 2
fi

mkdir -p "$out"

# The replay prints a one-line JSON summary and exits 0 (complete), 1 (incomplete),
# or 2 (input or output error, already reported on stderr).
status=0
PYTHONPATH="$root/src" "$python" -B -m auction_replay.replay_auction \
    --auction examples/synthetic/auction.csv \
    --input-dir examples/synthetic \
    --report "$out/report.md" \
    --csv "$out/decisions.csv" \
    --work-limit 2000 > "$out/summary.json" || status=$?
if [ "$status" -eq 2 ]; then
    exit 2
fi

"$python" -B scripts/quickstart_summary.py examples/synthetic "$out" "$status"
exit "$status"
