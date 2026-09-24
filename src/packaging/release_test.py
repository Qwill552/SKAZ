import json
from pathlib import Path
import tarfile
import tempfile
import tomllib
import unittest
import zipfile

from build_release import ROOT, build, sha256
from server.version import VERSION


class ReleaseTest(unittest.TestCase):
    def test_project_versions_match(self):
        script = (ROOT / "userscript/skaz.user.js").read_text(encoding="utf-8")
        self.assertIn(f"// @version      {VERSION}", script)
        self.assertIn(f"const SCRIPT_VERSION = '{VERSION}'", script)
        for name in ("pyproject.toml", "packaging/pyproject-unix.toml"):
            project = tomllib.loads((ROOT / name).read_text(encoding="utf-8"))
            self.assertEqual(project["project"]["version"], VERSION)
        for name in ("uv.lock", "packaging/uv-unix.lock"):
            locked = tomllib.loads((ROOT / name).read_text(encoding="utf-8"))
            package = next(item for item in locked["package"] if item["name"] == "skaz-server")
            self.assertEqual(package["version"], VERSION)

    def test_platform_archives_and_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            archives = build(destination)
            manifest = json.loads((destination / "version.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], VERSION)
            for path in (*archives.values(), destination / "skaz.user.js"):
                self.assertEqual(manifest["assets"][path.name], sha256(path))
            notes = (destination / "release-notes.md").read_text(encoding="utf-8")
            for path in archives.values():
                self.assertIn(f"{sha256(path)}  {path.name}", notes)
            with zipfile.ZipFile(archives["windows"]) as archive:
                names = set(archive.namelist())
                self.assertIn("_internal/packaging/update.ps1", names)
                self.assertIn("_internal/server/version.py", names)
                self.assertEqual(archive.read("README.txt"), (ROOT / "README.txt").read_bytes())
                self.assertNotIn("config.json", names)
            for platform in ("linux", "macos"):
                with tarfile.open(archives[platform], "r:gz") as archive:
                    names = set(archive.getnames())
                    self.assertIn("packaging/update.sh", names)
                    self.assertIn("server/version.py", names)
                    self.assertIn("install.sh", names)
                    self.assertEqual(archive.extractfile("README.txt").read(),
                                     (ROOT / f"packaging/README-{platform}.txt").read_bytes())
                    self.assertFalse(any(name.startswith("models/") for name in names))


if __name__ == "__main__":
    unittest.main()
