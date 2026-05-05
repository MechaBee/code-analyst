#!/bin/sh
set -eu

until /usr/bin/mc alias set local http://minio:9000 minioadmin minioadmin >/dev/null 2>&1; do
  sleep 1
done

/usr/bin/mc mb --ignore-existing local/code-analyst-dev

