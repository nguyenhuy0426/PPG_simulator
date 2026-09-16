import configparser
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "icons" / "ppg-simulator.svg"
DESKTOP_TEMPLATE = ROOT / "packaging" / "linux" / "ppg-simulator.desktop.in"
LAUNCHER = ROOT / "scripts" / "launch_ppg_simulator.sh"
INSTALLER = ROOT / "scripts" / "install_desktop_launcher.sh"


class TestDesktopLauncher(unittest.TestCase):
    def test_icon_matches_android_adaptive_icon(self):
        root = ET.parse(ICON).getroot()
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        rectangle = root.find("svg:rect", namespace)
        circle = root.find("svg:circle", namespace)
        path = root.find("svg:path", namespace)
        self.assertIsNotNone(rectangle)
        self.assertIsNotNone(circle)
        self.assertIsNotNone(path)
        self.assertEqual(rectangle.attrib["fill"].upper(), "#0B1117")
        self.assertEqual(circle.attrib["fill"].upper(), "#00FF88")
        self.assertEqual(path.attrib["stroke"].upper(), "#00FF88")
        self.assertIn("M12 54", path.attrib["d"])
        self.assertIn("L96 54", path.attrib["d"])

    def test_desktop_entry_is_safe_and_matches_window_class(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read(DESKTOP_TEMPLATE, encoding="utf-8")
        entry = parser["Desktop Entry"]
        self.assertEqual(entry["Type"], "Application")
        self.assertEqual(entry["Terminal"], "false")
        self.assertEqual(entry["Icon"], "ppg-simulator")
        # Tk normalizes the className constructor value to this WM_CLASS.
        self.assertEqual(entry["StartupWMClass"], "Ppgsimulator")
        self.assertNotIn("sh -c", entry["Exec"])
        self.assertTrue(entry["Exec"].endswith("/scripts/launch_ppg_simulator.sh"))
        self.assertIn('className="PPGSimulator"',
                      (ROOT / "ui" / "ctk_app.py").read_text(encoding="utf-8"))

    def test_shell_scripts_pass_bash_syntax_check(self):
        for script in (LAUNCHER, INSTALLER):
            subprocess.run(("bash", "-n", str(script)), check=True)

    def test_installer_builds_launchers_in_isolated_home(self):
        with tempfile.TemporaryDirectory(prefix="ppg-launcher-test-") as temporary:
            temporary_path = Path(temporary)
            data_home = temporary_path / "share"
            desktop_dir = temporary_path / "Desktop"
            environment = os.environ.copy()
            environment.update({
                "HOME": temporary,
                "XDG_DATA_HOME": str(data_home),
                "PPG_DESKTOP_DIR": str(desktop_dir),
            })
            subprocess.run((str(INSTALLER),), cwd=ROOT, env=environment,
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True)

            application = data_home / "applications" / "ppg-simulator.desktop"
            desktop = desktop_dir / "ppg-simulator.desktop"
            icon = data_home / "icons" / "hicolor" / "scalable" / "apps" / "ppg-simulator.svg"
            self.assertTrue(application.is_file())
            self.assertTrue(desktop.is_file())
            self.assertTrue(icon.is_file())
            self.assertNotIn("@PROJECT_ROOT@", application.read_text(encoding="utf-8"))
            self.assertTrue(desktop.stat().st_mode & stat.S_IXUSR)

    def test_launcher_reports_missing_virtual_environment(self):
        with tempfile.TemporaryDirectory(prefix="ppg-launcher-missing-venv-") as temporary:
            project = Path(temporary) / "project"
            script_dir = project / "scripts"
            state_home = Path(temporary) / "state"
            script_dir.mkdir(parents=True)
            copied_launcher = script_dir / LAUNCHER.name
            shutil.copy2(LAUNCHER, copied_launcher)
            environment = os.environ.copy()
            environment.update({
                "HOME": temporary,
                "XDG_STATE_HOME": str(state_home),
                "DISPLAY": "",
                "DBUS_SESSION_BUS_ADDRESS": "",
            })
            result = subprocess.run((str(copied_launcher),), env=environment,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True)
            self.assertEqual(result.returncode, 1)
            log = state_home / "ppg-simulator" / "launcher.log"
            self.assertIn("Python environment is missing", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
