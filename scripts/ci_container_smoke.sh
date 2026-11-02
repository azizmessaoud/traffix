#!/usr/bin/env bash
# Smoke test for the live image. A successful `docker build` only proves the Dockerfile steps ran;
# this starts the container and requires a real SUMO run to reach "running".
#
#   bash scripts/ci_container_smoke.sh traffix-live
#
# Exits non-zero (and prints the container log) on the first failed check.
set -euo pipefail

IMAGE="${1:-traffix-live}"
PORT="${PORT:-7860}"
BASE="http://localhost:${PORT}"
PYTHON="${PYTHON:-python3}"
TOKEN="$(head -c 24 /dev/urandom | base64 | tr -d '/+=\n')"
NAME="traffix-smoke-$$"

fail() {
  echo "SMOKE FAILED: $*" >&2
  echo "--- container log (tail) ---" >&2
  docker logs "$NAME" 2>&1 | tail -60 >&2 || true
  exit 1
}

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

status_of() {  # status_of <curl args...> : HTTP status code only
  curl -s -o /dev/null -w '%{http_code}' "$@" || echo 000
}

docker run -d --name "$NAME" -p "${PORT}:7860" -e TRAFFIX_OPERATOR_TOKEN="$TOKEN" "$IMAGE" >/dev/null

# 1. Health: the server, the SUMO binary, the network and the frontend bundle are all present.
code=000
for _ in $(seq 1 90); do
  code="$(status_of "$BASE/health")"
  [ "$code" = "200" ] && break
  sleep 2
done
[ "$code" = "200" ] || fail "/health returned $code"
echo "ok: /health 200"

# 2. Frontend is served.
code="$(status_of "$BASE/")"
[ "$code" = "200" ] || fail "frontend / returned $code"
echo "ok: frontend 200"

# 3. Operator endpoints need the token: no token and a wrong token are both refused.
code="$(status_of -X POST "$BASE/api/start?scenario=morning_peak&speed=4&controller=traffix_rules")"
[ "$code" = "401" ] || fail "start without token returned $code, expected 401"
code="$(status_of -X POST -H "Authorization: Bearer wrong-token" "$BASE/api/start?scenario=morning_peak&speed=4&controller=traffix_rules")"
[ "$code" = "401" ] || fail "start with wrong token returned $code, expected 401"
echo "ok: operator endpoints refuse missing and wrong tokens"

# 4. With the token, a run starts.
code="$(status_of -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/start?scenario=morning_peak&speed=4&controller=traffix_rules")"
[ "$code" = "200" ] || fail "start with token returned $code, expected 200"

# 5. SUMO must actually run: state must reach "running" with simulated time advancing.
#    A broken SUMO install leaves the state at "starting" forever, so this step fails on it.
state=""
for _ in $(seq 1 60); do
  body="$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/state" || true)"
  state="$(printf '%s' "$body" | "$PYTHON" -c 'import sys, json
try:
    d = json.load(sys.stdin); print(d.get("status", ""), d.get("t", 0))
except Exception:
    print("", 0)')"
  case "$state" in
    running\ *) t="${state#running }"; awk "BEGIN{exit !($t > 0)}" && break ;;
    error\ *|error) fail "simulation reported an error: $body" ;;
  esac
  sleep 2
done
case "$state" in
  running\ *) echo "ok: simulation running ($state)" ;;
  *) fail "simulation never reached running (last state: '$state')" ;;
esac

# 6. Stop the run cleanly.
code="$(status_of -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/stop")"
[ "$code" = "200" ] || fail "stop returned $code"
echo "ok: stop 200"
echo "SMOKE PASSED"
