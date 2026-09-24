#!/usr/bin/env bash
set -euo pipefail

root="$1"
cd "$root"
exec >> "$root/server.log" 2>&1
lock="$root/.update.lock"
mkdir "$lock" || exit 0
work="$(mktemp -d)"
trap 'rm -rf -- "$work"; rmdir "$lock"' EXIT

base='https://github.com/Qwill552/SKAZ/releases/latest/download'
if [[ "$(uname -s)" == Linux ]]; then asset='skaz-linux.tar.gz'; else asset='skaz-macos.tar.gz'; fi
if command -v curl >/dev/null 2>&1; then
  curl -fLsS "$base/version.json" -o "$work/version.json"
else
  wget -q -O "$work/version.json" "$base/version.json"
fi
read -r target expected < <("$root/.venv/bin/python" -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["version"],m["assets"][sys.argv[2]])' "$work/version.json" "$asset")
"$root/.venv/bin/python" -c 'import re,sys; from server.version import VERSION; a=sys.argv[1]; assert re.fullmatch(r"\d+\.\d+\.\d+",a); assert tuple(map(int,a.split(".")))>tuple(map(int,VERSION.split(".")))' "$target" || exit 0
[[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || exit 1
if command -v curl >/dev/null 2>&1; then
  curl -fLsS "$base/$asset" -o "$work/$asset"
else
  wget -q -O "$work/$asset" "$base/$asset"
fi
if [[ "$(uname -s)" == Linux ]]; then actual="$(sha256sum "$work/$asset")"; else actual="$(shasum -a 256 "$work/$asset")"; fi
[[ "${actual%% *}" == "$expected" ]] || { printf '%s\n' 'SKAZ update checksum mismatch'; exit 1; }
while IFS= read -r name; do
  case "$name" in /*|../*|*/../*|*/..) exit 1 ;; esac
done < <(tar -tzf "$work/$asset")
mkdir "$work/archive"
tar -xzf "$work/$asset" -C "$work/archive"
SKAZ_UNATTENDED_UPDATE=1 bash "$work/archive/install.sh"
printf 'SKAZ updated to %s\n' "$target"
