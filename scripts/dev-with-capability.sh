#!/usr/bin/env bash
set -euo pipefail

# Without this, services run in permissive mode and `require_capability` is
# a no-op. Source this script before launching the dev stack to put every
# request between the frontend and the services behind the capability gate.

if [[ -z "${BAHLILY_CAPABILITY:-}" ]]; then
  readonly BAHLILY_CAPABILITY="$(head -c 32 /dev/urandom | xxd -p)"
  export BAHLILY_CAPABILITY
fi

export NEXT_PUBLIC_BAHLILY_CAPABILITY="${BAHLILY_CAPABILITY}"
