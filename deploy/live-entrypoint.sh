#!/bin/sh
set -eu

if [ -z "${TRAFFIX_OPERATOR_TOKEN:-}" ]; then
  echo "TRAFFIX_OPERATOR_TOKEN must be configured as a Hugging Face Space Secret." >&2
  exit 1
fi

export TRAFFIX_REQUIRE_OPERATOR_TOKEN=1
exec uvicorn traffix.api.server:app --host 0.0.0.0 --port 7860 --workers 1
