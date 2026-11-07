"""tests/conftest.py keeps one test's Tk garbage out of the next test's worker threads.

A worker thread that runs the finalizers of leaked Tk objects (no mainloop)
waits about 1 s per object in _tkinter; that is what made SignalEngine's 2 s
join in test_waveform_output fail after the UI tests in a full run.
"""
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

LEAK_TK_GARBAGE = textwrap.dedent("""
    import tkinter as tk

    class Holder:
        pass

    def test_leaves_tk_variables_in_a_cycle():
        root = tk.Tk()
        for _ in range(2):
            holder = Holder()
            holder.self = holder
            holder.var = tk.BooleanVar(root)
        root.destroy()
""")

WORKER_COLLECTS = textwrap.dedent("""
    import gc
    import threading

    def test_worker_thread_collection_is_not_stalled_by_tk_finalizers():
        worker = threading.Thread(target=gc.collect, daemon=True)
        worker.start()
        worker.join(timeout=0.5)
        assert not worker.is_alive()
""")


def _run_pair(tmp_path, *extra):
    (tmp_path / "test_a_ui.py").write_text(LEAK_TK_GARBAGE)
    (tmp_path / "test_b_worker.py").write_text(WORKER_COLLECTS)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra,
         "test_a_ui.py", "test_b_worker.py"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120)


@pytest.mark.skipif(not HAS_DISPLAY, reason="needs a display server to create a Tk window")
def test_tk_garbage_is_finalized_on_the_main_thread_between_tests(tmp_path):
    shutil.copy(Path(__file__).with_name("conftest.py"), tmp_path / "conftest.py")

    control = _run_pair(tmp_path, "--noconftest")
    assert "1 failed, 1 passed" in control.stdout, control.stdout

    isolated = _run_pair(tmp_path)
    assert "2 passed" in isolated.stdout, isolated.stdout
