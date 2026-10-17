"""Suite-wide isolation: finalize Tk garbage on the main thread.

CustomTkinter widgets sit in reference cycles and own objects whose __del__
calls Tcl (CTkFont via tkinter.font.Font, tkinter.Variable, tkinter.Image).
After a UI test those cycles wait for the next full collection, which runs on
whichever thread happens to allocate at that moment. When that is a
SignalEngine worker and no Tk mainloop is running, _tkinter waits about 1 s
per object for a mainloop before giving up (WaitForMainloop), so the worker
outlives SignalEngine._stop_thread's 2 s join and the single-writer check
fires. test_ui_performance alone leaves more than 200 such objects behind.

Collecting on the main thread whenever a Tk interpreter exists, or was created
or destroyed since the last collection, runs those finalizers where Tcl calls
are allowed, before any later test starts output threads.
"""
import gc

import pytest

_live_roots = 0
_tk_dirty = False


def _install_tk_tracking():
    import tkinter

    original_init = tkinter.Tk.__init__
    original_destroy = tkinter.Tk.destroy

    def tracked_init(self, *args, **kwargs):
        global _live_roots, _tk_dirty
        original_init(self, *args, **kwargs)
        self._suite_tracked_root = True
        _live_roots += 1
        _tk_dirty = True

    def tracked_destroy(self):
        global _live_roots, _tk_dirty
        try:
            original_destroy(self)
        finally:
            if self.__dict__.pop("_suite_tracked_root", False):
                _live_roots -= 1
            _tk_dirty = True

    tkinter.Tk.__init__ = tracked_init
    tkinter.Tk.destroy = tracked_destroy
    return lambda: (setattr(tkinter.Tk, "__init__", original_init),
                    setattr(tkinter.Tk, "destroy", original_destroy))


def _collect_tk_garbage():
    global _tk_dirty
    if _tk_dirty:
        gc.collect()
        _tk_dirty = _live_roots > 0


def pytest_configure(config):
    try:
        config._restore_tk = _install_tk_tracking()
    except ImportError:  # no Tk on this machine: nothing can leave Tk garbage
        config._restore_tk = None


def pytest_unconfigure(config):
    if getattr(config, "_restore_tk", None):
        config._restore_tk()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    _collect_tk_garbage()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    yield
    # After the item's whole teardown, including a class- or module-scoped one
    # (tearDownClass -> on_closing releases an entire window here), so the
    # next item's setUpClass or fixtures never start threads beside it.
    _collect_tk_garbage()
