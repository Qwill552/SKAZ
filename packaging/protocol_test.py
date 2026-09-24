import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("protocol_unix", Path(__file__).with_name("protocol_unix.py"))
protocol_unix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol_unix)
register_spec = importlib.util.spec_from_file_location("register_protocol", Path(__file__).with_name("register_protocol.py"))
register_protocol = importlib.util.module_from_spec(register_spec)
register_spec.loader.exec_module(register_protocol)


class ProtocolTest(unittest.TestCase):
    def test_invalid_urls_do_nothing(self):
        values = ("skaz://start%20&%20calc.exe", "skaz://start//", "skaz://setup?x=1",
                  "skaz://stop#x", "skaz://restart", "SKAZ://start", "skaz://start\" x")
        for value in values:
            with self.subTest(value=value), patch.object(sys, "argv", ["protocol_unix.py", value]), \
                 patch.object(protocol_unix, "start") as start, \
                 patch.object(protocol_unix, "stop") as stop:
                self.assertEqual(protocol_unix.main(), 0)
                start.assert_not_called()
                stop.assert_not_called()

    def test_start_and_stop_dispatch(self):
        for url in ("skaz://start", "skaz://start/"):
            with patch.object(sys, "argv", ["protocol_unix.py", url]), \
                 patch.object(protocol_unix, "start") as start:
                self.assertEqual(protocol_unix.main(), 0)
                start.assert_called_once_with()
        for url in ("skaz://stop", "skaz://stop/"):
            with patch.object(sys, "argv", ["protocol_unix.py", url]), \
                 patch.object(protocol_unix, "stop") as stop:
                self.assertEqual(protocol_unix.main(), 0)
                stop.assert_called_once_with()
        for url in ("skaz://setup", "skaz://setup/"):
            with patch.object(sys, "argv", ["protocol_unix.py", url]), \
                 patch.object(protocol_unix, "start") as start, \
                 patch.object(protocol_unix, "setup_url", return_value="http://127.0.0.1:8756/setup"), \
                 patch.object(protocol_unix.subprocess, "Popen") as open_setup:
                self.assertEqual(protocol_unix.main(), 0)
                start.assert_called_once_with()
                open_setup.assert_called_once()

    def test_desktop_registration_and_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            desktop = base / "applications/skaz.desktop"
            config = base / "config"
            config.mkdir()
            mimeapps = config / "mimeapps.list"
            mimeapps.write_text("[Default Applications]\nx-scheme-handler/skaz=skaz.desktop;other.desktop;\n", encoding="utf-8")
            with patch.object(register_protocol, "DESKTOP", desktop), \
                 patch.object(register_protocol, "CONFIG_HOME", config), \
                 patch.object(register_protocol, "update_database"), \
                 patch.object(register_protocol.subprocess, "run"):
                register_protocol.install()
                self.assertIn("%u", desktop.read_text(encoding="utf-8"))
                register_protocol.uninstall()
            self.assertFalse(desktop.exists())
            self.assertIn("x-scheme-handler/skaz=other.desktop;", mimeapps.read_text(encoding="utf-8"))

    def test_desktop_exec_escaping(self):
        argument = register_protocol.desktop_argument('a\\b"$`%')
        self.assertEqual(argument, '"a' + "\\" * 4 + 'b' + "\\" * 2 + '"' +
                         "\\" * 2 + '$' + "\\" * 2 + '`%%"')


if __name__ == "__main__":
    unittest.main()
