#!/usr/bin/env bash
set -euo pipefail

fail() { printf 'Ошибка: %s\n' "$1" >&2; exit 1; }
yes_answer() { local answer; read -r -p "$1 [y/N]: " answer; [[ "$answer" == y || "$answer" == Y || "$answer" == д || "$answer" == Д ]]; }

[[ "$(id -u)" != 0 && -z "${SUDO_USER:-}" ]] || fail 'Запускайте ./uninstall.sh без sudo.'
os="$(uname -s)"
case "$os" in
  Linux)
    data_base="${XDG_DATA_HOME:-$HOME/.local/share}"
    config_base="${XDG_CONFIG_HOME:-$HOME/.config}"
    ;;
  Darwin)
    data_base="$HOME/Library/Application Support"
    config_base="$data_base"
    ;;
  *) fail 'Поддерживаются только Linux и macOS.' ;;
esac
[[ "$data_base" == /* && "$config_base" == /* ]] || fail 'XDG-пути должны быть абсолютными.'
root="$data_base/skaz"
source_dir="$(cd "$(dirname "$0")" && pwd -P)"
if [[ -f "$source_dir/.skaz-install.json" && -f "$source_dir/.config-dir" ]]; then
  root="$source_dir"
  config_base="$(dirname "$(cat "$source_dir/.config-dir")")"
fi
config_dir="$config_base/skaz"
marker="$root/.skaz-install.json"
[[ -d "$root" && ! -L "$root" && -f "$marker" ]] || fail 'Установка SKAZ не найдена.'
stored_root="$("$root/.venv/bin/python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["root"])' "$marker")"
[[ "$stored_root" == "$root" ]] || fail 'Путь установки не совпадает с маркером.'
yes_answer "Удалить SKAZ из $root?" || exit 0
delete_data=no
if yes_answer 'Удалить также ключ и пользовательский словарь?'; then delete_data=yes; fi

if [[ "$os" == Linux ]]; then
  "$root/.venv/bin/python" "$root/packaging/register_protocol.py" uninstall
  unit="$HOME/.config/systemd/user/skaz.service"
  if [[ -f "$unit" ]] && grep -Fq "$root/run.sh" "$unit"; then
    systemctl --user disable --now skaz.service || true
    rm -f "$unit"
    systemctl --user daemon-reload || true
  fi
else
  plist="$HOME/Library/LaunchAgents/com.skaz.plist"
  if [[ -f "$plist" ]] && "$root/.venv/bin/python" -c 'import plistlib,sys; p=plistlib.load(open(sys.argv[1],"rb")); assert p["ProgramArguments"][0] == sys.argv[2]' "$plist" "$root/run.sh"; then
    launchctl unload "$plist" || true
    rm -f "$plist"
  fi
fi
if [[ -f "$root/.server.pid" ]]; then
  pid="$(cat "$root/.server.pid")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && ps -p "$pid" -o command= | grep -Fq -e 'server.main' -e "$root/packaging/unix_runner.py"; then
    kill "$pid" || true
    for attempt in {1..50}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
fi

if [[ "$os" == Darwin && "$delete_data" == no ]]; then
  backup="$data_base/skaz-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup"
  for name in config.json user_dict.json; do
    [[ ! -f "$config_dir/$name" ]] || cp "$config_dir/$name" "$backup/$name"
  done
  printf 'Ключ и словарь сохранены: %s\n' "$backup"
fi
rm -rf "$root"
if [[ "$os" == Linux && "$delete_data" == yes ]]; then
  [[ ! -L "$config_dir" ]] || fail 'Каталог конфигурации — ссылка; удалите его вручную.'
  rm -rf "$config_dir"
fi
printf '%s\n' 'SKAZ удалён. Юзерскрипт удаляется отдельно в Tampermonkey.'
