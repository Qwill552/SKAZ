#!/bin/sh
set -eu
umask 077
skaz_root="$(cd "$(dirname "$0")" && pwd -P)"
skaz_config_dir="$(cat "$skaz_root/.config-dir")"
export SKAZ_CONFIG_DIR="$skaz_config_dir"
cd "$skaz_root"
exec "$skaz_root/.venv/bin/python" "$skaz_root/packaging/unix_runner.py"
