import json
import re
import urllib.request

from .version import REPOSITORY, VERSION


MANIFEST_URL = f"https://github.com/{REPOSITORY}/releases/latest/download/version.json"


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value))
    if not match:
        raise ValueError("Некорректная версия релиза")
    return tuple(map(int, match.groups()))


def latest_manifest():
    request = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "SKAZ-Updater"})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)
    version_tuple(data["version"])
    if not isinstance(data.get("assets"), dict):
        raise ValueError("В релизе отсутствуют суммы файлов")
    return data


def newer(value):
    return version_tuple(value) > version_tuple(VERSION)
