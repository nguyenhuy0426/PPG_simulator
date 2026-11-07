"""The systemd user service that starts the simulator with the Pi's desktop session.

The installer, the desktop launcher and scripts/deploy_and_run.sh run here against
stand-ins for systemctl, ssh, pkill and the other host commands on PATH, so no test
touches the real user manager, the I2C bus or a Pi. Only the unit validity test
calls the real systemd-analyze.
"""

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
UNIT_TEMPLATE = ROOT / "packaging" / "linux" / "ppg-simulator.service.in"
INSTALLER = ROOT / "scripts" / "install_user_service.sh"
LAUNCHER = ROOT / "scripts" / "launch_ppg_simulator.sh"
DEPLOY = ROOT / "scripts" / "deploy_and_run.sh"
UNIT = "ppg-simulator.service"
# Longest SIGTERM shutdown of main.py, from the timeouts on its path: two output
# threads x 2 s (core/signal_engine.py), the Neural worker 2 s
# (ui/frames/neural_frame.py), the BLE thread 10 s (comm/ble_server.py) and the
# RX thread 2 s (hw/opt101_rx.py).
SHUTDOWN_WORST_CASE_S = 2 * 2 + 2 + 10 + 2

# Records every call. UnitFileState and ActiveState live in files so a stop or a
# start changes what the next query returns, as with the real user manager.
FAKE_SYSTEMCTL = r"""#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >>"${FAKE_DIR}/calls"
file_state="$(cat "${FAKE_DIR}/unit_file_state" 2>/dev/null)"
active_state="$(cat "${FAKE_DIR}/active_state" 2>/dev/null || echo inactive)"
case "$*" in
    "--user show-environment")
        if [ "${FAKE_GRAPHICAL:-active}" = active ]; then echo "DISPLAY=:0"; fi ;;
    "--user show --property=UnitFileState --value ppg-simulator.service")
        printf '%s\n' "${file_state}" ;;
    "--user show --property=ActiveState --value ppg-simulator.service")
        printf '%s\n' "${active_state}" ;;
    "--user is-active --quiet graphical-session.target")
        [ "${FAKE_GRAPHICAL:-active}" = active ]; exit ;;
    "--user is-active --quiet ppg-simulator.service")
        [ "${active_state}" = active ]; exit ;;
    "--user is-active ppg-simulator.service")
        echo "${active_state}"; [ "${active_state}" = active ]; exit ;;
    "--user start ppg-simulator.service")
        if [ "${FAKE_START_EXIT:-0}" != 0 ]; then exit "${FAKE_START_EXIT}"; fi
        echo active >"${FAKE_DIR}/active_state" ;;
    "--user stop ppg-simulator.service"|"--user disable --now ppg-simulator.service")
        echo inactive >"${FAKE_DIR}/active_state"
        # systemd-run --collect: a stopped transient unit is garbage-collected.
        if [ "${file_state}" = transient ]; then : >"${FAKE_DIR}/unit_file_state"; fi ;;
esac
exit 0
"""

FAKE_SYSTEMD_RUN = r"""#!/usr/bin/env bash
printf 'systemd-run %s\n' "$*" >>"${FAKE_DIR}/calls"
echo active >"${FAKE_DIR}/active_state"
"""

# Drops the ssh options and the host name, then runs the command on this machine.
FAKE_SSH = r"""#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) shift 2 ;;
        -*) shift ;;
        *) break ;;
    esac
done
shift
exec bash -c "$*"
"""

FAKE_PYTHON = r"""#!/usr/bin/env bash
printf 'python %s\n' "$*" >>"${FAKE_DIR}/calls"
"""


def recorder(name, exit_code=0):
    return f"#!/usr/bin/env bash\nprintf '{name} %s\\n' \"$*\" >>\"${{FAKE_DIR}}/calls\"\nexit {exit_code}\n"


def write_executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def parse_unit(path):
    """Section -> key -> list of values; systemd allows repeated keys."""
    sections, current = {}, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        key, separator, value = line.partition("=")
        if current is None or not separator:
            raise ValueError(f"unexpected line in {path.name}: {raw!r}")
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


class TestUnitTemplate(unittest.TestCase):
    def setUp(self):
        self.unit = parse_unit(UNIT_TEMPLATE)

    def value(self, section, key):
        values = self.unit[section][key]
        self.assertEqual(len(values), 1, f"{section}.{key} set more than once")
        return values[0]

    def test_runs_the_hardware_app_from_the_checkout_venv(self):
        self.assertEqual(self.value("Service", "Type"), "exec")
        self.assertEqual(self.value("Service", "ExecStart"),
                         "@PROJECT_ROOT@/.venv/bin/python @PROJECT_ROOT@/main.py")
        self.assertEqual(self.value("Service", "WorkingDirectory"), "@PROJECT_ROOT@")
        # A user unit runs as the user who owns the manager; it must not switch users.
        self.assertNotIn("User", self.unit["Service"])
        self.assertNotIn("Group", self.unit["Service"])

    def test_is_tied_to_the_graphical_session(self):
        for key in ("PartOf", "After", "Requisite"):
            self.assertEqual(self.value("Unit", key), "graphical-session.target")
        self.assertEqual(self.value("Install", "WantedBy"), "graphical-session.target")

    def test_crash_restarts_are_rate_limited(self):
        self.assertEqual(self.value("Service", "Restart"), "on-failure")
        restart_s = int(self.value("Service", "RestartSec"))
        interval_s = int(self.value("Unit", "StartLimitIntervalSec"))
        burst = int(self.value("Unit", "StartLimitBurst"))
        self.assertGreaterEqual(burst, 2)
        # Starts are at least RestartSec apart. The limit can only trip if a burst
        # of starts fits inside the interval (systemd's default 10 s never would).
        self.assertLess((burst - 1) * restart_s, interval_s)

    def test_stops_through_the_sigterm_shutdown_path_with_time_to_finish(self):
        self.assertEqual(self.value("Service", "KillSignal"), "SIGTERM")
        self.assertGreater(int(self.value("Service", "TimeoutStopSec")), SHUTDOWN_WORST_CASE_S)
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("signal.signal(signal.SIGTERM, request_gui_shutdown)", main)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze not installed")
    @unittest.skipUnless(os.access(ROOT / ".venv" / "bin" / "python", os.X_OK), "no .venv in this checkout")
    def test_rendered_unit_passes_systemd_analyze_verify(self):
        with tempfile.TemporaryDirectory(prefix="ppg-unit-verify-") as temporary:
            rendered = Path(temporary) / UNIT
            rendered.write_text(UNIT_TEMPLATE.read_text(encoding="utf-8")
                                .replace("@PROJECT_ROOT@", str(ROOT)), encoding="utf-8")
            result = subprocess.run(("systemd-analyze", "--user", "verify", str(rendered)),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    timeout=60)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        # verify exits 0 on an unknown key; it still names the file in a warning.
        self.assertNotIn(UNIT, output)


class FakeHost(unittest.TestCase):
    """Temporary HOME with stand-ins for every command that could touch this host."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ppg-user-service-test-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.fake_dir = self.home / "fake"
        self.fake_dir.mkdir()
        bin_dir = self.home / "bin"
        fakes = {
            "systemctl": FAKE_SYSTEMCTL,
            "systemd-run": FAKE_SYSTEMD_RUN,
            "ssh": FAKE_SSH,
            "systemd-analyze": recorder("systemd-analyze"),
            "rsync": recorder("rsync"),
            "pkill": recorder("pkill", 1),
            "pgrep": recorder("pgrep", 1),
            "i2cdetect": recorder("i2cdetect", 1),
            "journalctl": recorder("journalctl"),
            "notify-send": recorder("notify-send"),
            "sleep": "#!/bin/sh\nexit 0\n",
        }
        for name, body in fakes.items():
            write_executable(bin_dir / name, body)
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "PATH": f"{bin_dir}{os.pathsep}{self.env['PATH']}",
            "FAKE_DIR": str(self.fake_dir),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_STATE_HOME": str(self.home / "state"),
            "PPG_UNIT_DIR": str(self.home / "units"),
            "DBUS_SESSION_BUS_ADDRESS": "",
        })
        self.unit_path = self.home / "units" / UNIT

    def set_unit(self, file_state="", active_state="inactive"):
        (self.fake_dir / "unit_file_state").write_text(file_state, encoding="utf-8")
        (self.fake_dir / "active_state").write_text(active_state, encoding="utf-8")
        (self.fake_dir / "calls").unlink(missing_ok=True)

    def calls(self):
        log = self.fake_dir / "calls"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def run_script(self, script, *arguments, **environment):
        return subprocess.run((str(script), *arguments), cwd=ROOT, env={**self.env, **environment},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)


class TestInstaller(FakeHost):
    def test_installs_and_enables_without_starting(self):
        result = self.run_script(INSTALLER)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.unit_path.read_text(encoding="utf-8")
        self.assertNotIn("@PROJECT_ROOT@", text)
        self.assertIn(f"\nExecStart={ROOT}/.venv/bin/python {ROOT}/main.py\n", text)
        self.assertEqual(stat.S_IMODE(self.unit_path.stat().st_mode), 0o644)
        calls = self.calls()
        self.assertTrue(any(call.startswith("systemd-analyze --user verify ") for call in calls))
        self.assertLess(calls.index("systemctl --user daemon-reload"),
                        calls.index(f"systemctl --user enable {UNIT}"))
        self.assertNotIn(f"systemctl --user start {UNIT}", calls)

    def test_now_stops_any_other_instance_before_starting_the_unit(self):
        result = self.run_script(INSTALLER, "--now")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        enable = calls.index(f"systemctl --user enable {UNIT}")
        stop = calls.index(f"systemctl --user stop {UNIT}")
        pkill = next(index for index, call in enumerate(calls) if call.startswith("pkill -TERM "))
        self.assertIn(f"python[0-9.]* {ROOT}/main\\.py", calls[pkill])
        self.assertLess(enable, stop)
        self.assertLess(stop, pkill)
        self.assertEqual(calls[-1], f"systemctl --user start {UNIT}")

    def test_now_without_a_desktop_session_leaves_the_start_to_the_next_login(self):
        result = self.run_script(INSTALLER, "--now", FAKE_GRAPHICAL="inactive")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("next login", result.stdout)
        self.assertIn(f"systemctl --user enable {UNIT}", self.calls())
        self.assertNotIn(f"systemctl --user start {UNIT}", self.calls())

    def test_takes_over_from_the_transient_unit_of_deploy_and_run(self):
        self.set_unit(file_state="transient", active_state="active")
        result = self.run_script(INSTALLER)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        # systemd refuses to enable a name that a transient unit holds.
        self.assertLess(calls.index(f"systemctl --user stop {UNIT}"),
                        calls.index(f"systemctl --user enable {UNIT}"))
        self.assertEqual(calls[-1], f"systemctl --user start {UNIT}")

    def test_rejects_a_checkout_path_that_a_unit_file_cannot_hold(self):
        project = self.home / "my project"
        for source, directory in ((INSTALLER, project / "scripts"),
                                  (UNIT_TEMPLATE, project / "packaging" / "linux")):
            directory.mkdir(parents=True)
            shutil.copy2(source, directory)
        write_executable(project / ".venv" / "bin" / "python", "#!/bin/sh\nexit 0\n")
        result = self.run_script(project / "scripts" / INSTALLER.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot hold unquoted", result.stderr)
        self.assertFalse(self.unit_path.exists())
        self.assertNotIn(f"systemctl --user enable {UNIT}", self.calls())

    def test_uninstall_stops_disables_and_removes_the_unit(self):
        self.unit_path.parent.mkdir(parents=True)
        self.unit_path.write_text("[Unit]\n", encoding="utf-8")
        (self.unit_path.parent / f"{UNIT}.d").mkdir()
        self.set_unit(file_state="enabled", active_state="active")
        result = self.run_script(INSTALLER, "--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.unit_path.exists())
        calls = self.calls()
        self.assertLess(calls.index(f"systemctl --user disable --now {UNIT}"),
                        calls.index("systemctl --user daemon-reload"))
        self.assertIn("Kept local overrides", result.stdout)

    def test_uninstall_without_a_unit_does_nothing(self):
        result = self.run_script(INSTALLER, "--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Nothing to remove", result.stdout)
        self.assertNotIn(f"systemctl --user disable --now {UNIT}", self.calls())


class TestLauncherHandOff(FakeHost):
    def setUp(self):
        super().setUp()
        self.project = self.home / "project"
        self.launcher = self.project / "scripts" / LAUNCHER.name
        self.launcher.parent.mkdir(parents=True)
        shutil.copy2(LAUNCHER, self.launcher)
        write_executable(self.project / ".venv" / "bin" / "python", FAKE_PYTHON)

    def python_calls(self):
        return [call for call in self.calls() if call.startswith("python ")]

    def test_installed_service_is_started_instead_of_a_second_process(self):
        self.set_unit(file_state="enabled")
        result = self.run_script(self.launcher)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertLess(calls.index(f"systemctl --user reset-failed {UNIT}"),
                        calls.index(f"systemctl --user start {UNIT}"))
        self.assertEqual(self.python_calls(), [])

    def test_instance_under_systemd_blocks_a_new_launch(self):
        for file_state in ("enabled", "transient"):
            for active_state in ("active", "activating", "deactivating"):
                with self.subTest(file_state=file_state, active_state=active_state):
                    self.set_unit(file_state, active_state)
                    result = self.run_script(self.launcher)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = self.calls()
                    self.assertTrue(any(call.startswith("notify-send ") for call in calls))
                    self.assertNotIn(f"systemctl --user start {UNIT}", calls)
                    self.assertEqual(self.python_calls(), [])

    def test_without_the_service_the_launcher_runs_the_app_itself(self):
        self.set_unit()
        result = self.run_script(self.launcher)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.python_calls(), [f"python {self.project}/main.py"])
        self.assertNotIn(f"systemctl --user start {UNIT}", self.calls())

    def test_diagnostic_arguments_bypass_the_service(self):
        self.set_unit(file_state="enabled")
        self.run_script(self.launcher, "--no-ble")
        self.assertEqual(self.python_calls(), [f"python {self.project}/main.py --no-ble"])
        self.assertNotIn(f"systemctl --user start {UNIT}", self.calls())

    def test_failed_service_start_is_reported(self):
        self.set_unit(file_state="enabled")
        result = self.run_script(self.launcher, FAKE_START_EXIT="1")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any(call.startswith("notify-send ") for call in self.calls()))
        self.assertEqual(self.python_calls(), [])


class TestDeployRestart(FakeHost):
    """Step 5 of deploy_and_run.sh, with the 'Pi' being this temporary HOME."""

    def setUp(self):
        super().setUp()
        write_executable(self.home / "pi-project" / ".venv" / "bin" / "python", FAKE_PYTHON)
        self.env.update({"PI_HOST": "fake-pi", "PI_DIR": "pi-project"})

    def deploy(self, **environment):
        return self.run_script(DEPLOY, "--pi-only", **environment)

    def test_installed_unit_is_restarted_instead_of_a_second_instance(self):
        for file_state in ("enabled", "disabled"):
            with self.subTest(file_state=file_state):
                self.set_unit(file_state=file_state, active_state="active")
                result = self.deploy()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = self.calls()
                self.assertLess(calls.index(f"systemctl --user stop {UNIT}"),
                                calls.index(f"systemctl --user start {UNIT}"))
                self.assertFalse(any(call.startswith("systemd-run ") for call in calls))

    def test_without_an_installed_unit_a_transient_unit_is_started(self):
        for file_state in ("", "transient"):
            with self.subTest(file_state=file_state):
                self.set_unit(file_state=file_state)
                result = self.deploy()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = self.calls()
                self.assertTrue(any(call.startswith("systemd-run --user --unit=ppg-simulator ")
                                    for call in calls))
                self.assertNotIn(f"systemctl --user start {UNIT}", calls)

    def test_without_a_desktop_session_the_app_is_left_alone(self):
        self.set_unit(file_state="enabled", active_state="active")
        result = self.deploy(FAKE_GRAPHICAL="inactive")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        calls = self.calls()
        self.assertNotIn(f"systemctl --user stop {UNIT}", calls)
        self.assertNotIn(f"systemctl --user start {UNIT}", calls)
        self.assertFalse(any(call.startswith("systemd-run ") for call in calls))


class TestScriptSyntax(unittest.TestCase):
    def test_shell_scripts_pass_bash_syntax_check(self):
        for script in (INSTALLER, DEPLOY):
            subprocess.run(("bash", "-n", str(script)), check=True)


if __name__ == "__main__":
    unittest.main()
