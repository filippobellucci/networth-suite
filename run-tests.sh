#!/usr/bin/env bash
#
# One command to check the whole suite.
#
#   ./run-tests.sh            everything except the browser tier
#   ./run-tests.sh fast       the sub-second tiers only (unit + frontend)
#   ./run-tests.sh all        everything, browser tier included
#   ./run-tests.sh unit       one tier: unit | integration | system | e2e | frontend | lint
#
# Anything after the tier is passed through to pytest, so this works:
#   ./run-tests.sh integration -k refund -x
#
set -uo pipefail
cd "$(dirname "$0")"

TIER="${1:-default}"
shift || true

FAILED=()
run() {
    local label="$1"; shift
    printf '\n\033[1m── %s\033[0m\n' "$label"
    if "$@"; then
        printf '\033[32m   %s passed\033[0m\n' "$label"
    else
        printf '\033[31m   %s FAILED\033[0m\n' "$label"
        FAILED+=("$label")
    fi
}

case "$TIER" in
  unit)        run "unit"        python3 -m pytest -m unit "$@" ;;
  integration) run "integration" python3 -m pytest -m integration "$@" ;;
  system)      run "system"      python3 -m pytest -m system "$@" ;;
  e2e)         run "browser"     python3 -m pytest -m e2e "$@" ;;
  frontend)    run "frontend"    npm --prefix frontend test ;;
  lint)
      run "ruff"   python3 -m ruff check --select F,E9 services/ gateway/ tests/
      run "tsc"    bash -c "cd frontend && npx tsc -b"
      run "oxlint" bash -c "cd frontend && npx oxlint"
      ;;
  fast)
      run "unit"     python3 -m pytest -m unit "$@"
      run "frontend" npm --prefix frontend test
      ;;
  default|"")
      run "unit"        python3 -m pytest -m unit
      run "integration" python3 -m pytest -m integration
      run "frontend"    npm --prefix frontend test
      run "system"      python3 -m pytest -m system
      ;;
  all)
      run "unit"        python3 -m pytest -m unit
      run "integration" python3 -m pytest -m integration
      run "frontend"    npm --prefix frontend test
      run "system"      python3 -m pytest -m system
      run "browser"     python3 -m pytest -m e2e
      ;;
  *)
      echo "unknown tier '$TIER' -- use: fast | unit | integration | system | e2e | frontend | lint | all"
      exit 2
      ;;
esac

printf '\n'
if [ ${#FAILED[@]} -eq 0 ]; then
    printf '\033[32mall green\033[0m\n'
    exit 0
fi
printf '\033[31mfailed: %s\033[0m\n' "${FAILED[*]}"
exit 1
