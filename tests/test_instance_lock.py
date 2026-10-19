"""main.py's single-instance lock, and how the launcher and the deploy script use it.

Every process here gets its own temporary XDG_STATE_HOME, so no test touches the
lock of a simulator running on this machine. main.py is run for real, but only
down the conflict path, which exits before the hardware, BLE and GUI modules load.
"""

import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import unittest

from tests.test_user_service import (DEPLOY, LAUNCHER, ROOT, UNIT, UNIT_TEMPLATE, FakeHost,
                                     parse_unit, write_executable)

sys.path.insert(0, str(ROOT))
import instance_lock  # noqa: E402

EXIT_ALREADY_RUNNING = instance_lock.EXIT_ALREADY_RUNNING
ACQUIRE = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); import instance_lock; "
           "instance_lock.acquire()")
# Takes the lock, reports it and keeps it until stdin closes.
HOLD = ACQUIRE + "; print('held', flush=True); sys.stdin.read()"


class LockHost(FakeHost):
    def setUp(self):
        super().setUp()
        self.env["PPG_DRY_RUN"] = "1"
        self.env.pop(instance_lock.LOCK_FD_ENV, None)
        self.lock_file = self.home / "state" / "ppg-simulator" / "app.lock"

    def python(self, code, **environment):
        return subprocess.run((sys.executable, "-c", code), cwd=ROOT,
                              env={**self.env, **environment}, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=60)

    def hold_lock(self):
        holder = subprocess.Popen((sys.executable, "-c", HOLD), cwd=ROOT, env=self.env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

        def release():
            holder.stdin.close()
            holder.wait(timeout=10)
            holder.stdout.close()

        self.addCleanup(release)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        return holder

    def lock_is_free(self):
        return self.python(ACQUIRE).returncode == 0


class TestMainLock(LockHost):
    def run_main(self, *arguments):
        return subprocess.run((sys.executable, str(ROOT / "main.py"), *arguments), cwd=ROOT,
                              env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=60)

    def test_second_instance_exits_with_the_dedicated_status_in_every_mode(self):
        holder = self.hold_lock()
        for arguments in ((), ("--dry-run",), ("--dry-run", "--no-ble"), ("--dry-run", "--ble-only")):
            with self.subTest(arguments=arguments):
                result = self.run_main(*arguments)
                self.assertEqual(result.returncode, EXIT_ALREADY_RUNNING, result.stderr)
                self.assertIn("already running", result.stderr)
                self.assertIn(f"process {holder.pid}", result.stderr)
                self.assertIn(str(self.lock_file), result.stderr)
                # It stopped before the logger, config and hardware modules loaded.
                self.assertNotIn("Mode:", result.stdout + result.stderr)

    def test_help_does_not_need_the_lock(self):
        self.hold_lock()
        result = self.run_main("--help")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_lock_is_taken_before_any_hardware_or_ble_module_is_imported(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        lock = source.index("instance_lock.acquire()")
        for module in ("from config import", "from core.signal_engine", "from hw.",
                       "from comm.", "from ui.", "from config_store"):
            self.assertLess(lock, source.index(module), module)

    def test_lock_is_released_when_the_holder_is_killed(self):
        holder = subprocess.Popen((sys.executable, "-c", HOLD), cwd=ROOT, env=self.env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.stdin.close)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        self.assertFalse(self.lock_is_free())
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        self.assertTrue(self.lock_is_free())

    def test_a_child_process_does_not_keep_the_lock_after_a_crash(self):
        # Both ways in: a fresh descriptor, and the launcher's inheritable fd 9.
        # The real sleep: FakeHost puts a stand-in that exits at once on PATH.
        crash = ACQUIRE + ("; import subprocess, os; "
                           f"child = subprocess.Popen([{shutil.which('sleep')!r}, '30'], "
                           "close_fds=False, stdout=subprocess.DEVNULL); "
                           "print(child.pid, flush=True); os._exit(1)")
        for prefix in ("", f'exec 9<>"{self.lock_file}"; export {instance_lock.LOCK_FD_ENV}=9; '):
            with self.subTest(inherited=bool(prefix)):
                self.lock_file.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(("bash", "-c", f'{prefix}exec "$0" -c "$1"',
                                         sys.executable, crash), cwd=ROOT, env=self.env,
                                        stdout=subprocess.PIPE, text=True, timeout=60)
                child = int(result.stdout.split()[0])
                self.addCleanup(os.kill, child, signal.SIGKILL)
                self.assertEqual(result.returncode, 1)
                # The child still runs, and must not hold the lock.
                os.kill(child, 0)
                self.assertTrue(self.lock_is_free())


class TestInheritedDescriptor(LockHost):
    """flock locks belong to an open file description, not to the file."""

    def run_with_fd_9(self, code, **environment):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        script = f'exec 9<>"{self.lock_file}"; flock -n 9 || exit 99; exec "$0" -c "$1"'
        return subprocess.run(("bash", "-c", script, sys.executable, code), cwd=ROOT,
                              env={**self.env, **environment}, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=60)

    @unittest.skipUnless(shutil.which("flock"), "flock(1) not installed")
    def test_the_launchers_locked_descriptor_is_reused(self):
        report = ACQUIRE + "; import os; print(os.environ.get('PPG_APP_LOCK_FD'))"
        result = self.run_with_fd_9(report, **{instance_lock.LOCK_FD_ENV: "9"})
        self.assertEqual(result.returncode, 0, result.stderr)
        # Removed, so a child process cannot claim the descriptor.
        self.assertEqual(result.stdout.strip(), "None")

    @unittest.skipUnless(shutil.which("flock"), "flock(1) not installed")
    def test_opening_the_file_again_would_conflict_with_the_launchers_own_lock(self):
        result = self.run_with_fd_9(ACQUIRE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AlreadyRunning", result.stderr)

    def test_a_descriptor_on_another_file_is_ignored(self):
        other = self.home / "other"
        other.write_text("", encoding="utf-8")
        script = f'exec 9<>"{other}"; exec "$0" -c "$1"'
        result = subprocess.run(("bash", "-c", script, sys.executable, ACQUIRE), cwd=ROOT,
                                env={**self.env, instance_lock.LOCK_FD_ENV: "9"},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(other.read_text(encoding="utf-8"), "")
        self.assertTrue(self.lock_file.read_text(encoding="ascii").strip().isdigit())

    def test_a_bogus_descriptor_number_is_ignored(self):
        for value in ("not-a-number", "250"):
            with self.subTest(value=value):
                result = self.python(ACQUIRE, **{instance_lock.LOCK_FD_ENV: value})
                self.assertEqual(result.returncode, 0, result.stderr)


# Locks with the real instance_lock module, then records that it ran.
LOCKING_PYTHON = r"""#!/usr/bin/env bash
if "%(python)s" -c "%(acquire)s" ; then
    printf 'python %%s\n' "$*" >>"${FAKE_DIR}/calls"
else
    printf 'python-refused %%s\n' "$*" >>"${FAKE_DIR}/calls"
fi
"""

# On start, records whether this launcher's lock is still held.
LOCK_PROBE = r"""
lock="${XDG_STATE_HOME}/ppg-simulator/app.lock"
if [ "$*" = "--user start ppg-simulator.service" ] && ! flock -n "${lock}" true; then
    printf 'lock-held-during-start\n' >>"${FAKE_DIR}/calls"
fi
"""


@unittest.skipUnless(shutil.which("flock"), "flock(1) not installed")
class TestLauncherLock(LockHost):
    def setUp(self):
        super().setUp()
        self.project = self.home / "project"
        self.launcher = self.project / "scripts" / LAUNCHER.name
        self.launcher.parent.mkdir(parents=True)
        shutil.copy2(LAUNCHER, self.launcher)
        write_executable(self.project / ".venv" / "bin" / "python", LOCKING_PYTHON % {
            "python": sys.executable, "acquire": ACQUIRE.replace('"', '\\"')})
        systemctl = self.home / "bin" / "systemctl"
        body = systemctl.read_text(encoding="utf-8")
        systemctl.write_text(body.replace("\n", "\n" + LOCK_PROBE, 1), encoding="utf-8")

    def test_launched_app_takes_the_lock_through_the_inherited_descriptor(self):
        self.set_unit()
        result = self.run_script(self.launcher)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call for call in self.calls() if call.startswith("python")],
                         [f"python {self.project}/main.py"])

    def test_a_copy_started_by_hand_blocks_the_desktop_icon(self):
        self.set_unit()
        self.hold_lock()
        result = self.run_script(self.launcher)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertTrue(any(call.startswith("notify-send ") for call in calls))
        self.assertFalse(any(call.startswith("python") for call in calls))

    def test_lock_is_released_before_the_service_is_started(self):
        self.set_unit(file_state="enabled")
        result = self.run_script(self.launcher)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertIn(f"systemctl --user start {UNIT}", calls)
        self.assertNotIn("lock-held-during-start", calls)

    def test_launcher_keeps_the_running_instances_pid_in_the_lock_file(self):
        holder = self.hold_lock()
        self.set_unit()
        self.run_script(self.launcher)
        self.assertEqual(self.lock_file.read_text(encoding="ascii").strip(), str(holder.pid))


class TestServiceDoesNotRetryAConflict(unittest.TestCase):
    def test_lock_conflict_status_prevents_a_restart(self):
        unit = parse_unit(UNIT_TEMPLATE)
        self.assertEqual(unit["Service"]["RestartPreventExitStatus"], [str(EXIT_ALREADY_RUNNING)])
        self.assertEqual(unit["Service"]["Restart"], ["on-failure"])
        # Not a status that a Python crash, argparse or systemd itself uses.
        self.assertNotIn(EXIT_ALREADY_RUNNING, (0, 1, 2, 3))
        self.assertLess(EXIT_ALREADY_RUNNING, 200)


class TestDeployStrayPattern(FakeHost):
    """Step 5 of deploy_and_run.sh stops strays that run main.py, and nothing else."""

    def setUp(self):
        super().setUp()
        self.pi_project = self.home / "pi-project"
        write_executable(self.pi_project / ".venv" / "bin" / "python", "#!/bin/sh\nexit 0\n")
        self.env.update({"PI_HOST": "fake-pi", "PI_DIR": "pi-project"})

    def deploy(self, **environment):
        return self.run_script(DEPLOY, "--pi-only", **environment)

    def pkill_pattern(self):
        call = next(call for call in self.calls() if call.startswith("pkill "))
        return call.split(" -f ", 1)[1]

    def test_pattern_matches_the_app_but_not_an_editor_on_main_py(self):
        self.set_unit()
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        call = next(call for call in self.calls() if call.startswith("pkill "))
        self.assertIn(f"-u {os.getuid()} ", call)
        pattern = re.compile(self.pkill_pattern())
        main = f"{self.pi_project}/main.py"
        for command in (f"{self.pi_project}/.venv/bin/python {main}",
                        f"{self.pi_project}/.venv/bin/python3.12 {main} --dry-run",
                        f"/usr/bin/python3 {main} --no-ble"):
            self.assertTrue(pattern.search(command), command)
        for command in (f"tail -f {main}", f"nano {main}", f"vim {main}",
                        f"less {main}.orig", f"{self.pi_project}/.venv/bin/python {main}x",
                        f"bash -c python {main}"):
            self.assertFalse(pattern.search(command), command)

    def test_waits_for_a_stray_to_exit_before_starting(self):
        self.set_unit()
        write_executable(self.home / "bin" / "pkill",
                         "#!/usr/bin/env bash\nprintf 'pkill %s\\n' \"$*\" >>\"${FAKE_DIR}/calls\"\n")
        # pgrep sees the stray twice, then it is gone.
        write_executable(self.home / "bin" / "pgrep", r"""#!/usr/bin/env bash
printf 'pgrep %s\n' "$*" >>"${FAKE_DIR}/calls"
count=$(cat "${FAKE_DIR}/pgrep_count" 2>/dev/null || echo 0)
echo $((count + 1)) >"${FAKE_DIR}/pgrep_count"
[ "${count}" -lt 2 ]
""")
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        start = next(index for index, call in enumerate(calls) if call.startswith("systemd-run "))
        last_pgrep = max(index for index, call in enumerate(calls) if call.startswith("pgrep "))
        self.assertLess(last_pgrep, start)

    def test_a_stray_that_does_not_exit_stops_the_deploy(self):
        self.set_unit(file_state="enabled")
        write_executable(self.home / "bin" / "pkill",
                         "#!/usr/bin/env bash\nprintf 'pkill %s\\n' \"$*\" >>\"${FAKE_DIR}/calls\"\n")
        write_executable(self.home / "bin" / "pgrep", "#!/bin/sh\nexit 0\n")
        result = self.deploy()
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("did not exit", result.stdout)
        calls = self.calls()
        self.assertNotIn(f"systemctl --user start {UNIT}", calls)
        self.assertFalse(any(call.startswith("systemd-run ") for call in calls))


if __name__ == "__main__":
    unittest.main()
