#!/bin/sh
# Run a command in a throwaway container that sees this workspace.
# The Jenkins agent talks to the host Docker daemon (DooD), so -v "$PWD" would point at a host path that
# doesn't exist; reuse the agent container's mounts when we are inside one.
# Usage: sh scripts/ci-run.sh IMAGE COMMAND [ARGS...]
set -eu
image=$1
shift
if docker inspect "$(hostname)" >/dev/null 2>&1; then
  set -- --volumes-from "$(hostname)" -w "$PWD" "$image" "$@"
else
  set -- -v "$PWD":/app -w /app "$image" "$@"
fi
exec docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e GITEA_TOKEN -e GITEA_URL -e GITEA_REPO -e GIT_COMMIT "$@"
