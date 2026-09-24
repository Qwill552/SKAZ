#!/usr/bin/env bash
set -euo pipefail
umask 077

source_dir="$(cd "$(dirname "$0")" && pwd -P)"
fail() { printf 'Ошибка: %s\n' "$1" >&2; exit 1; }
yes_answer() { local answer; [[ "${SKAZ_UNATTENDED_UPDATE:-}" != 1 ]] || return 0; read -r -p "$1 [y/N]: " answer; [[ "$answer" == y || "$answer" == Y || "$answer" == д || "$answer" == Д ]]; }

[[ "$(id -u)" != 0 && -z "${SUDO_USER:-}" ]] || fail 'Запускайте ./install.sh без sudo: иначе файлы попадут в /root.'
os="$(uname -s)"
arch="$(uname -m)"
case "$os:$arch" in
  Linux:x86_64) uv_target=x86_64-unknown-linux-gnu ;;
  Linux:aarch64) uv_target=aarch64-unknown-linux-gnu ;;
  Darwin:arm64) uv_target=aarch64-apple-darwin ;;
  Darwin:x86_64) uv_target=x86_64-apple-darwin ;;
  *) fail "Неподдерживаемая система: $os $arch. Нужна Linux x86_64/aarch64 или macOS arm64/x86_64." ;;
esac
if [[ "$os" == Linux ]]; then
  libc="$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
  [[ "$libc" =~ ^glibc[[:space:]]+([0-9]+)\.([0-9]+)$ ]] || fail 'Для torch 2.14 нужен Linux с glibc 2.28 или новее.'
  libc_major="${BASH_REMATCH[1]}"
  libc_minor="${BASH_REMATCH[2]}"
  (( libc_major > 2 || (libc_major == 2 && libc_minor >= 28) )) || fail 'Для torch 2.14 нужен glibc 2.28 или новее.'
fi
if [[ "$os" == Darwin && "$arch" == arm64 ]]; then
  mac_major="$(sw_vers -productVersion)"
  mac_major="${mac_major%%.*}"
  [[ "$mac_major" =~ ^[0-9]+$ && "$mac_major" -ge 14 ]] || fail 'Для Apple Silicon нужен macOS 14 или новее: torch 2.14 не имеет колеса для старой macOS.'
fi

if [[ "$os" == Linux ]]; then
  data_base="$HOME/.local/share"
  config_base="$HOME/.config"
  [[ -z "${XDG_DATA_HOME:-}" ]] || data_base="${XDG_DATA_HOME:-}"
  [[ -z "${XDG_CONFIG_HOME:-}" ]] || config_base="${XDG_CONFIG_HOME:-}"
else
  data_base="$HOME/Library/Application Support"
  config_base="$data_base"
fi
[[ "$data_base" == /* && "$config_base" == /* ]] || fail 'XDG-пути должны быть абсолютными.'
root="$data_base/skaz"
if [[ -f "$source_dir/.skaz-install.json" && -f "$source_dir/.config-dir" ]]; then
  root="$source_dir"
  config_base="$(dirname "$(cat "$source_dir/.config-dir")")"
fi
[[ ! -L "$root" ]] || fail 'Каталог установки не должен быть символической ссылкой.'
config_dir="$config_base/skaz"
marker="$root/.skaz-install.json"
unit="$HOME/.config/systemd/user/skaz.service"
plist="$HOME/Library/LaunchAgents/com.skaz.plist"

printf 'SKAZ: %s %s\nПриложение и модель: %s\nКонфиг и словарь: %s\n' "$os" "$arch" "$root" "$config_dir"
printf '%s\n' 'Будут загружены uv, Python 3.12, зависимости и модель. Нужно около 2 ГБ свободного места.'
if [[ -e "$marker" ]]; then
  yes_answer 'Обновить существующий SKAZ?' || exit 0
else
  [[ ! -d "$root" || -z "$(ls -A "$root")" || -f "$root/.skaz-partial" ]] || fail 'Каталог назначения занят и не содержит установленный SKAZ.'
  yes_answer 'Установить SKAZ?' || exit 0
fi

mkdir -p "$root" "$config_dir"
[[ ! -e "$root/.installing" ]] || fail 'Предыдущая установка не завершилась. Проверьте её файлы и удалите .installing перед повтором.'
printf 'SKAZ\n' > "$root/.installing"
printf 'SKAZ\n' > "$root/.skaz-partial"
trap 'rm -f "$root/.installing"' EXIT

if [[ -f "$marker" ]]; then
  if [[ "$os" == Linux && -f "$unit" ]] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop skaz.service || true
  elif [[ "$os" == Darwin && -f "$plist" ]]; then
    launchctl unload "$plist" || true
  fi
  if [[ -f "$root/.server.pid" ]]; then
    old_pid="$(cat "$root/.server.pid")"
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && ps -p "$old_pid" -o command= | grep -Fq -e 'server.main' -e "$root/packaging/unix_runner.py"; then
      kill "$old_pid" || true
      for attempt in {1..50}; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 0.1
      done
    fi
    rm -f "$root/.server.pid"
  fi
fi

if [[ "$source_dir" != "$root" ]]; then
  for name in .python-version models.json README.txt run.sh install.sh uninstall.sh; do
    cp "$source_dir/$name" "$root/$name"
  done
  for name in server userscript packaging; do
    rm -rf -- "$root/$name"
    cp -R "$source_dir/$name" "$root/$name"
  done
fi
cp "$root/packaging/pyproject-unix.toml" "$root/pyproject.toml"
cp "$root/packaging/uv-unix.lock" "$root/uv.lock"
chmod 700 "$root/run.sh"
chmod 700 "$config_dir"

if [[ "$config_dir" != "$root" ]]; then
  for name in config.json user_dict.json; do
    if [[ -L "$root/$name" ]]; then
      [[ "$(readlink "$root/$name")" == "$config_dir/$name" ]] || fail "Неожиданная ссылка $name."
      rm "$root/$name"
    elif [[ -e "$root/$name" ]]; then
      [[ ! -e "$config_dir/$name" ]] || fail "Обнаружены две копии $name; разберите их вручную."
      mv "$root/$name" "$config_dir/$name"
    fi
  done
fi
printf '%s\n' "$config_dir" > "$root/.config-dir"
export SKAZ_CONFIG_DIR="$config_dir"
mkdir -p "$root/bin"
uv="$root/bin/uv"
if [[ ! -x "$uv" ]]; then
  asset="uv-$uv_target.tar.gz"
  archive="$root/bin/$asset"
  url="https://github.com/astral-sh/uv/releases/download/0.12.17/$asset"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --progress-bar "$url" -o "$archive"
    curl -fLsS "$url.sha256" -o "$archive.sha256"
  elif command -v wget >/dev/null 2>&1; then
    wget --show-progress -O "$archive" "$url"
    wget -q -O "$archive.sha256" "$url.sha256"
  else
    fail 'Для загрузки uv нужен curl или wget.'
  fi
  expected="$(awk '{print $1; exit}' "$archive.sha256")"
  [[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || fail 'Некорректная SHA-256 сумма uv.'
  if [[ "$os" == Linux ]]; then actual="$(sha256sum "$archive")"; else actual="$(shasum -a 256 "$archive")"; fi
  [[ "$actual" == "$expected "* ]] || fail 'SHA-256 архива uv не совпала.'
  tar -xzf "$archive" -C "$root/bin" --strip-components=1 "uv-$uv_target/uv"
  rm -f "$archive" "$archive.sha256"
fi

export UV_PYTHON_INSTALL_DIR="$root/python"
export UV_CACHE_DIR="$root/.uv-cache"
export UV_PYTHON_PREFERENCE=only-managed
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="$root/.venv"
"$uv" python install 3.12 --no-bin
(
  cd "$root"
  "$uv" sync --locked --no-dev --no-editable --python 3.12
  if [[ "${SKAZ_UNATTENDED_UPDATE:-}" == 1 ]]; then
    "$root/.venv/bin/python" -m server.install_model --unattended
  else
    "$root/.venv/bin/python" -m server.install_model
  fi
  "$root/.venv/bin/python" -c 'import torch; assert torch.version.cuda is None, "CUDA wheel is not supported"'
)
chmod 600 "$config_dir/config.json" "$config_dir/user_dict.json"
while read -r model_file model_hash; do
  if [[ "$os" == Linux ]]; then actual="$(sha256sum "$root/models/$model_file")"; else actual="$(shasum -a 256 "$root/models/$model_file")"; fi
  [[ "$actual" == "$model_hash "* ]] || fail "SHA-256 модели $model_file не совпала."
done < <("$root/.venv/bin/python" -c 'import json,sys; c=json.load(open(sys.argv[1])); m=json.load(open(sys.argv[2])); print("\n".join(e["url"].rsplit("/",1)[-1]+" "+e["sha256"] for k in c.get("models",[c["model"]]) if (e:=m.get(k))))' "$config_dir/config.json" "$root/models.json")

autostart=no
if [[ "$os" == Linux ]]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    if [[ -e "$unit" ]] || { [[ "${SKAZ_UNATTENDED_UPDATE:-}" != 1 ]] && yes_answer 'Включить автозапуск через systemd при входе?'; }; then
      autostart=yes
      [[ "$root" != *'"'* && "$root" != *'$'* && "$root" != *'%'* && "$root" != *'\'* ]] || fail 'Путь установки содержит неподдерживаемый для systemd символ.'
      mkdir -p "$(dirname "$unit")"
      "$root/.venv/bin/python" -c 'import sys; from pathlib import Path; t=Path(sys.argv[1]).read_text(); Path(sys.argv[2]).write_text(t.replace("@SKAZ_RUN@", chr(34)+sys.argv[3]+chr(34)))' "$root/packaging/skaz.service" "$unit" "$root/run.sh"
      systemctl --user daemon-reload
      systemctl --user enable skaz.service
      systemctl --user restart skaz.service
    fi
  else
    printf '%s\n' 'systemd --user недоступен; автозапуск не настроен.'
  fi
else
  if [[ -e "$plist" ]] || { [[ "${SKAZ_UNATTENDED_UPDATE:-}" != 1 ]] && yes_answer 'Включить автозапуск при входе в macOS?'; }; then
    autostart=yes
    mkdir -p "$(dirname "$plist")"
    if [[ -e "$plist" ]]; then launchctl unload "$plist" 2>/dev/null || true; fi
    "$root/.venv/bin/python" -c 'import sys; from pathlib import Path; from xml.sax.saxutils import escape; p=Path(sys.argv[1]); t=Path(sys.argv[2]).read_text(); p.write_text(t.replace("@SKAZ_RUN@",escape(sys.argv[3])).replace("@SKAZ_LOG@",escape(sys.argv[4])))' "$plist" "$root/packaging/com.skaz.plist" "$root/run.sh" "$root/server.log"
    launchctl load -w "$plist"
  fi
fi

"$root/.venv/bin/python" -c 'import json,sys; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({"root":sys.argv[2],"version":1}))' "$marker" "$root"
if [[ "$os" == Linux ]]; then
  "$root/.venv/bin/python" "$root/packaging/register_protocol.py" install
fi
rm -rf "$root/.uv-cache"
rm -f "$root/.installing" "$root/.skaz-partial"
trap - EXIT
if [[ "$autostart" == no ]]; then
  nohup "$root/run.sh" > "$root/server.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$root/.server.pid"
fi
sleep 2
port="$("$root/.venv/bin/python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["port"])' "$config_dir/config.json")"
token="$("$root/.venv/bin/python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$config_dir/config.json")"
setup="http://127.0.0.1:$port/setup"
ready=no
for attempt in {1..20}; do
  if "$root/.venv/bin/python" -c 'import json,sys,urllib.request; c=json.load(open(sys.argv[1])); r=urllib.request.Request("http://127.0.0.1:%s/health"%c["port"],headers={"Authorization":"Bearer "+c["token"]}); assert urllib.request.urlopen(r,timeout=1).status == 200' "$config_dir/config.json" >/dev/null 2>&1; then
    ready=yes
    break
  fi
  sleep 0.5
done
[[ "$ready" == yes ]] || fail 'Сервер не ответил на /health. Проверьте server.log или journalctl --user -u skaz.'
printf 'SKAZ установлен. Страница настройки: %s\n' "$setup"
if [[ "${SKAZ_UNATTENDED_UPDATE:-}" == 1 ]]; then
  :
elif [[ "$os" == Darwin && -z "${SSH_CONNECTION:-}" ]]; then
  open "$setup" || true
elif [[ "$os" == Linux && ( -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ) ]] && command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$setup" || true
else
  printf 'Ключ: %s\n' "$token"
fi
printf 'Ручной запуск: %s/run.sh\n' "$root"
