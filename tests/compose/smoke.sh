#!/usr/bin/env bash
#
# Builds and starts the real docker-compose.yml, the only documented way to
# install this app, and checks it actually comes up -- not just that Python
# can import each service's modules, which is all the rest of the suite
# does (see tests/README.md, "Known gaps", and DESIGN_NOTES.md under
# shared/backup_retention.py for the deploy this would have caught).
#
# No real data, credentials or external services: every environment
# variable docker-compose.yml reads has a safe default, and bank-sync is
# documented to run with nothing configured ("safe to leave running
# unconfigured; it just has nothing to do").
set -euo pipefail
cd "$(dirname "$0")/../.."

cleanup() {
    status=$?
    echo "--- service logs ---"
    docker compose logs --no-color || true
    echo "--- tearing down ---"
    docker compose down --volumes --remove-orphans || true
    exit "$status"
}
trap cleanup EXIT

echo "--- building all six images with docker-compose.yml's own build context ---"
docker compose build

echo "--- starting the stack ---"
docker compose up -d

echo "--- waiting for the gateway to report every module healthy ---"
python3 tests/compose/wait_for_stack.py
