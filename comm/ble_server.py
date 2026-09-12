"""BLE GATT server for the PPG simulator (Android remote control).

Re-implements the historical comm/ble_server.py surface using `bless` 0.3.0
(pure-Python, dbus-next). Protocol is FROZEN to match the Android app
(com.medical.simulator, `RpiBleManager`):

    Service  12345678-1234-5678-1234-56789abcdef0
    WRITE    ...def1   app -> Pi   UTF-8 JSON command (delta merge)
    NOTIFY   ...def2   Pi  -> app  UTF-8 "%.2f" display-IR millivolts, ~50 Hz
    STATUS   ...def3   Pi  -> app  UTF-8 JSON snapshot, ~5 Hz (+ readable)

Protocol v2 command keys additionally drive simulation run state, CSV
recording and CSV playback ("run", "record", "pb", "pb_file"); the status
frame additionally reports them ("running", "recording", "pb", "pb_file").

Echo/sync rule (must stay in lockstep with the Android side):
    origin "android" — within ANDROID_GRACE_S after an applied Bluetooth
                       command; the phone updates its metric cards but NOT
                       its sliders (survives the 250 ms-debounced burst).
    origin "rpi"     — everything else. The status frame is the source of
                       truth, so after the grace window the phone always
                       re-syncs sliders + cards against actual Pi state.

Threading: bless runs in a daemon thread with its own asyncio loop. Tk owns
the main thread. BLE callbacks never touch Tk — they only call thread-safe
SignalEngine methods (playback commands are queued for the Tk loop).
See docs/ble_protocol.md.
"""

import asyncio
import json
import os
import threading
import time

from comm.logger import log
from config import DAC_FULLSCALE_MV, DAC_MAX_VALUE

# ─── Frozen protocol constants (do NOT change without the Android app) ──────
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID = "12345678-1234-5678-1234-56789abcdef2"
STATUS_UUID = "12345678-1234-5678-1234-56789abcdef3"
ADVERTISED_NAME = "MedicalSimulatorRPi"

# Rates (Hz) — overridable for weak adapters: PPG_BLE_WAVEFORM_RATE / PPG_BLE_STATUS_RATE
WAVEFORM_RATE_HZ = max(1.0, float(os.environ.get("PPG_BLE_WAVEFORM_RATE", "50")))
STATUS_RATE_HZ = max(0.5, float(os.environ.get("PPG_BLE_STATUS_RATE", "5")))

# After an applied Bluetooth command the status echo keeps the label
# origin=="android" for a window of this many seconds, so the phone is not
# fought during its 250 ms-debounced send bursts. Outside the window the echo
# is always "rpi": the status frame is the source of truth and the phone
# re-syncs against actual Pi state.
ANDROID_GRACE_S = 1.0

# "pb_file" is echoed back in the status JSON; the name is truncated to this
# many characters so the frame has a worst case of 247 bytes even with all
# amplitudes at their 4-digit maxima and a 9-digit seq. Notifications cap at
# MTU-3, so the client's negotiated MTU must be >= 250 (the Android app
# requests 256). See docs/ble_protocol.md.
PB_FILE_MAX_CHARS = 14

# Protocol v2 playback actions accepted on the "pb" command key.
PB_ACTIONS = ("start", "stop", "pause", "resume")

# Optional debug/testing hook: if PPG_BLE_CMD_FILE points to a JSON file, any
# rewrite of that file is applied as a LOCAL (origin "rpi") parameter change —
# used to exercise the Pi→phone sync direction in headless/CI runs.
CMD_FILE_PATH = os.environ.get("PPG_BLE_CMD_FILE")


def _to_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _to_bool(value, default=False):
    """Tolerant JSON-ish boolean. Never raises."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        t = value.strip().lower()
        if t in ("1", "true", "yes", "on"):
            return True
        if t in ("0", "false", "no", "off", ""):
            return False
    return default


def origin_for_tick(now, android_grace_until):
    """Pure origin decision for one status tick (unit-testable).

    "android" only inside the grace window opened by an applied Bluetooth
    command; every other tick (including command-file / local changes) is
    "rpi" so the phone always learns the actual Pi truth.
    """
    return "android" if now < android_grace_until else "rpi"


class BLECommandHandler:
    """Pure command application logic (testable without BlueZ/bless)."""

    def __init__(self, engine):
        self.engine = engine

    def handle_command(self, obj):
        """Apply a decoded command dict (delta merge). Returns what was applied.

        Unknown keys are ignored ("origin"/"seq" included); values are clamped
        to models.limits before the transactional engine wrappers run. Every
        key applies inside its own guard, so one raising value is logged and
        skipped — it can never abort the remaining keys of the same command.
        """
        from models.limits import (
            AC_LEVEL_MV,
            DC_LEVEL_MV,
            HEART_RATE,
            NOISE_LEVEL,
            PERFUSION_INDEX,
            RESP_RATE,
            SPO2,
        )

        if not isinstance(obj, dict):
            return {}

        applied = {}

        def guarded(name, fn):
            try:
                fn()
            except Exception:
                log.exception(f"[BLE] Command key '{name}' failed — remaining keys still applied")

        # Scalar setpoints.
        for key, limit, setter in (
            ("hr", HEART_RATE, self.engine.update_heart_rate),
            ("spo2", SPO2, self.engine.update_spo2),
            ("rr", RESP_RATE, self.engine.update_resp_rate),
            ("noise", NOISE_LEVEL, self.engine.update_noise_level),
        ):
            if key in obj:
                def apply_scalar(key=key, limit=limit, setter=setter):
                    v = limit.clamp(_to_float(obj[key], limit.default))
                    setter(v)
                    applied[key] = v
                guarded(key, apply_scalar)

        if "condition" in obj:
            def apply_condition():
                v = max(0, min(5, _to_int(obj["condition"], 0)))
                self.engine.change_condition(v)
                applied["condition"] = v
            guarded("condition", apply_condition)

        # AC/DC amplitude (mV). A command may contain a full snapshot with
        # PI+AC+DC, or a one-field delta from a slider. Apply in a deliberate
        # order so explicit physical amplitudes are never overwritten by a
        # stale PI value:
        #   * explicit AC + explicit DC: DC first, AC last; PI is derived from
        #     the resulting AC/DC pair;
        #   * PI without explicit AC: PI first, then explicit DC (DC derives AC
        #     from that PI);
        #   * AC only / DC only retain the model's normal coupling semantics.
        has_ac = "ac_ir_mv" in obj or "ac_red_mv" in obj
        has_explicit_ac_ir = "ac_ir_mv" in obj
        has_dc = "dc_ir_mv" in obj or "dc_red_mv" in obj

        if "pi" in obj and not has_explicit_ac_ir:
            def apply_pi():
                v = PERFUSION_INDEX.clamp(_to_float(obj["pi"], PERFUSION_INDEX.default))
                if getattr(self.engine, "ac_dc_locked", False):
                    # With both rails locked, PI is represented by AC IR.
                    p = self.engine.get_ppg_params()
                    ac_ir = AC_LEVEL_MV.clamp(v / 100.0 * p.dc_ir_mv)
                    self.engine.update_ac_levels(ac_ir, p.ac_red_mv)
                else:
                    self.engine.update_perfusion_index(v)
                applied["pi"] = v
            guarded("pi", apply_pi)
        elif "pi" in obj:
            # Keep the requested key visible in diagnostics, but the explicit
            # AC value is authoritative and the model will derive actual PI.
            applied["pi"] = PERFUSION_INDEX.clamp(
                _to_float(obj["pi"], PERFUSION_INDEX.default))

        if has_dc:
            def apply_dc():
                p = self.engine.get_ppg_params()
                dc_ir = p.dc_ir_mv
                dc_red = p.dc_red_mv
                if "dc_ir_mv" in obj:
                    dc_ir = DC_LEVEL_MV.clamp(_to_float(obj["dc_ir_mv"], DC_LEVEL_MV.default))
                if "dc_red_mv" in obj:
                    dc_red = DC_LEVEL_MV.clamp(_to_float(obj["dc_red_mv"], DC_LEVEL_MV.default))
                self.engine.update_dc_levels(dc_ir, dc_red)
                applied["dc_ir_mv"] = dc_ir
                applied["dc_red_mv"] = dc_red
            guarded("dc_levels", apply_dc)

        if has_ac:
            def apply_ac():
                p = self.engine.get_ppg_params()
                ac_ir = p.ac_ir_mv
                ac_red = p.ac_red_mv
                if "ac_ir_mv" in obj:
                    ac_ir = AC_LEVEL_MV.clamp(_to_float(obj["ac_ir_mv"], AC_LEVEL_MV.default))
                if "ac_red_mv" in obj:
                    ac_red = AC_LEVEL_MV.clamp(_to_float(obj["ac_red_mv"], AC_LEVEL_MV.default))
                self.engine.update_ac_levels(ac_ir, ac_red)
                applied["ac_ir_mv"] = ac_ir
                applied["ac_red_mv"] = ac_red
            guarded("ac_levels", apply_ac)

        # ─── Protocol v2: explicit run / record / playback control ───────────
        # Each is idempotent: the engine action only runs on an actual change.
        if "run" in obj:
            def apply_run():
                want = _to_bool(obj["run"])
                running = self._is_running()
                if want and not running:
                    self.engine.start_simulation(self.engine.get_ppg_params().condition)
                elif running and not want:
                    # A stopped generator cannot produce a meaningful CSV;
                    # keep the remote record state coherent with the GUI Run
                    # button instead of leaving the phone recording forever.
                    if bool(getattr(self.engine, "recording", False)):
                        self.engine.stop_recording()
                    self.engine.stop_simulation()
                applied["run"] = self._is_running()
            guarded("run", apply_run)

        if "record" in obj:
            def apply_record():
                want = _to_bool(obj["record"])
                recording = bool(getattr(self.engine, "recording", False))
                if want and not recording:
                    requested = str(obj.get("record_file", "") or "")
                    # Keep compatibility with small test doubles and older
                    # engines that do not yet accept a shared file name.
                    try:
                        self.engine.start_recording(requested or None)
                    except TypeError:
                        self.engine.start_recording()
                elif recording and not want:
                    self.engine.stop_recording()
                applied["record"] = bool(getattr(self.engine, "recording", False))
                if applied["record"]:
                    record_file = str(getattr(self.engine, "record_file", "") or "")
                    if record_file:
                        applied["record_file"] = record_file
            guarded("record", apply_record)

        if "pb" in obj:
            def apply_pb():
                action = str(obj["pb"]).strip().lower()
                if action not in PB_ACTIONS:
                    log.warning(f"[BLE] Ignored unknown pb action: {action!r}")
                    return
                filename = str(obj.get("pb_file", "") or "")
                queue = getattr(self.engine, "request_playback", None)
                if not callable(queue):
                    log.warning("[BLE] Playback command has no engine dispatcher — ignored")
                    return
                queue(action, filename)
                applied["pb"] = action
                if filename:
                    applied["pb_file"] = filename
            guarded("pb", apply_pb)

        # "origin" and "seq" (and any unknown key) are deliberately ignored:
        # origin/echo bookkeeping is server-side only (T4 grace window).
        return applied

    def _is_running(self):
        """Simulation running predicate that works on any engine double."""
        running = getattr(self.engine, "_running", None)
        if running is not None:
            return bool(running)
        from core.signal_engine import SIG_STOPPED
        state = getattr(self.engine, "state", None)
        return state is not None and state != SIG_STOPPED

    def handle_raw(self, data):
        """Decode raw write bytes -> applied dict. Swallows parse errors only;
        per-key failures are logged and isolated inside handle_command."""
        try:
            text = bytes(data).decode("utf-8", errors="replace").strip()
            if not text:
                return {}
            return self.handle_command(json.loads(text))
        except Exception as exc:
            log.warning(f"[BLE] Failed to parse command: {exc}")
            return {}


def _engine_state(engine):
    """(running, recording, record_file, pb, pb_file) read defensively."""
    running = bool(getattr(engine, "_running", False))
    recording = bool(getattr(engine, "recording", False))
    record_file = str(getattr(engine, "record_file", "") or "")
    getter = getattr(engine, "get_playback_state", None)
    if callable(getter):
        active, state, filename = getter()
        pb = 2 if (active and state == "paused") else (1 if active else 0)
    else:
        pb, filename = 0, ""
    return running, recording, record_file, int(pb), str(filename)


def build_status_json(p, origin, seq, running=False, recording=False,
                      record_file="", pb=0, pb_file=""):
    """Compact status JSON for the STATUS characteristic (~5 Hz).

    Derived (None) AC setpoints are reported as their nominal values so the
    phone sliders always show what the generator actually outputs. Protocol
    v2 adds the control state: running / recording / pb (0 inactive, 1
    playing, 2 paused); "pb_file" is present only while playback is active
    and truncated to PB_FILE_MAX_CHARS so the frame keeps a worst case of
    247 bytes (notifications cap at MTU-3: negotiated MTU must be >= 250).
    """
    dc_ir = p.dc_ir_mv
    ac_ir = p.ac_ir_mv if p.ac_ir_mv is not None else p.perfusion_index / 100.0 * dc_ir
    ac_red = p.ac_red_mv
    if ac_red is None:
        b = p.spo2_coeff_b if p.spo2_coeff_b else 1.0
        ratio = max(0.0, (p.spo2_coeff_a - p.spo2) / b)
        ac_red = ratio * ac_ir * (p.dc_red_mv / dc_ir) if dc_ir else 0.0

    payload = {
        "hr": round(p.heart_rate, 1),
        "spo2": round(p.spo2, 1),
        "rr": round(p.resp_rate, 1),
        "pi": round(p.perfusion_index, 2),
        "noise": round(p.noise_level, 2),
        "condition": int(p.condition),
        "ac_ir_mv": round(ac_ir, 1),
        "ac_red_mv": round(ac_red, 1),
        "dc_ir_mv": round(p.dc_ir_mv, 1),
        "dc_red_mv": round(p.dc_red_mv, 1),
        "running": bool(running),
        "recording": bool(recording),
        "pb": int(pb),
        "origin": origin,
        "seq": int(seq),
    }
    if int(pb) > 0:
        payload["pb_file"] = str(pb_file)[:PB_FILE_MAX_CHARS]
    # Keep the normal status frame inside the negotiated MTU. Recording and
    # playback are mutually exclusive user flows, so omit the recording name
    # while a playback file is being announced.
    if bool(recording) and int(pb) == 0 and record_file:
        payload["record_file"] = str(record_file)[:PB_FILE_MAX_CHARS]
    return json.dumps(payload, separators=(",", ":"))


def _param_snapshot(p, running=False, recording=False, record_file="", pb=0, pb_file=""):
    """Tuple of the parameters the status echo tracks (state included so a
    local Pi-side start/stop is visible as a change; origin labelling itself
    is grace-window based — see origin_for_tick)."""
    return (
        p.heart_rate, p.spo2, p.resp_rate, p.perfusion_index, p.noise_level,
        p.condition, p.ac_ir_mv, p.ac_red_mv, p.dc_ir_mv, p.dc_red_mv,
        bool(running), bool(recording), str(record_file), int(pb), str(pb_file),
    )


class _SimulatorBlessServer:
    """bless BlessServer subclass wired to a BleServer owner (created lazily)."""

    @staticmethod
    def build(owner, name, loop):
        from bless import BlessServer

        # bless 0.3.0 (BlueZ backend): WriteValue/ReadValue dispatch these
        # handlers synchronously (characteristic.py calls f(self, value) and
        # never awaits), so they MUST be plain sync functions — async overrides
        # produce never-awaited coroutines and every command is dropped.
        class Server(BlessServer):
            def read(self, char, **kwargs):
                if str(char.UUID).lower() == STATUS_UUID:
                    return owner.status_bytes()
                return bytes(char.value or b"")

            def write(self, char, value: bytes, **kwargs):
                char.value = bytearray(value)
                owner.on_write(value)
                return len(value)

        return Server(name, loop=loop)


class BleServer:
    """Thread-safe wrapper: start()/stop() from the Tk thread, bless inside."""

    def __init__(self, engine):
        self.engine = engine
        self.handler = BLECommandHandler(engine)
        self._thread = None
        self._loop = None
        self._shutdown_evt = None
        self._server = None
        self._seq = 0
        self._android_grace_until = 0.0
        self._android_echo_snapshot = None
        self._last_snapshot = None
        self._status_payload = b"{}"

    # ─── Lifecycle (Tk thread) ───────────────────────────────────────────────

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="ble-server")
        self._thread.start()

    def stop(self):
        loop, evt, thread = self._loop, self._shutdown_evt, self._thread
        if loop is not None and evt is not None:
            loop.call_soon_threadsafe(evt.set)
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
        self._thread = None
        self._loop = None
        self._shutdown_evt = None
        self._server = None

    def _thread_main(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            log.error(f"[BLE] Server thread died: {exc}")

    # ─── asyncio side ─────────────────────────────────────────────────────────

    async def _run(self):
        from bless.backends.attribute import GATTAttributePermissions
        from bless.backends.characteristic import GATTCharacteristicProperties

        loop = asyncio.get_running_loop()
        self._loop = loop
        self._shutdown_evt = asyncio.Event()

        server = _SimulatorBlessServer.build(self, ADVERTISED_NAME, loop)
        await server.add_new_service(SERVICE_UUID)
        await server.add_new_characteristic(
            SERVICE_UUID, WRITE_UUID,
            GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
            None,
            GATTAttributePermissions.readable | GATTAttributePermissions.writeable,
        )
        await server.add_new_characteristic(
            SERVICE_UUID, NOTIFY_UUID,
            GATTCharacteristicProperties.notify,
            bytearray(b"0.00"),
            GATTAttributePermissions.readable,
        )
        await server.add_new_characteristic(
            SERVICE_UUID, STATUS_UUID,
            GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
            None,
            GATTAttributePermissions.readable,
        )

        if not await server.start():
            log.error("[BLE] server.start() returned False — advertising failed")
        self._server = server
        log.info(
            "[BLE] Server running and advertising as '%s' (service %s, "
            f"waveform {WAVEFORM_RATE_HZ:g} Hz, status {STATUS_RATE_HZ:g} Hz)",
            ADVERTISED_NAME, SERVICE_UUID,
        )

        wave_task = asyncio.create_task(self._waveform_loop())
        status_task = asyncio.create_task(self._status_loop())
        cmd_file_task = None
        if CMD_FILE_PATH:
            cmd_file_task = asyncio.create_task(self._cmd_file_loop())
            log.info(f"[BLE] Watching command file (origin 'rpi'): {CMD_FILE_PATH}")
        try:
            await self._shutdown_evt.wait()
        finally:
            wave_task.cancel()
            status_task.cancel()
            if cmd_file_task is not None:
                cmd_file_task.cancel()
            try:
                await asyncio.gather(wave_task, status_task, return_exceptions=True)
            except Exception:
                pass
            try:
                await server.stop()
                log.info("[BLE] Server stopped, advertising released")
            except Exception as exc:
                log.warning(f"[BLE] server.stop() error: {exc}")

    async def _push(self, char_uuid, payload):
        """Set characteristic value and notify subscribers (callers handle errors)."""
        char = self._server.get_characteristic(char_uuid)
        if char is None:
            return
        char.value = bytearray(payload)
        result = self._server.update_value(SERVICE_UUID, char_uuid)
        if asyncio.iscoroutine(result):  # bless <0.3 shipped this as a coroutine
            await result

    async def _waveform_loop(self):
        interval = 1.0 / WAVEFORM_RATE_HZ
        errors = 0
        # Frozen protocol: "%.2f" of the display-IR signal in MILLIVOLTS along
        # the DAC path (DC + AC + noise, e.g. "1520.43"). get_current_raw_ir()
        # is the 12-bit DAC code of exactly that signal; convert to mV.
        mv_per_count = DAC_FULLSCALE_MV / DAC_MAX_VALUE
        while not self._shutdown_evt.is_set():
            try:
                value = self.engine.get_current_raw_ir() * mv_per_count
                await self._push(NOTIFY_UUID, f"{value:.2f}".encode("ascii"))
                if errors:
                    errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors += 1
                if errors <= 3 or errors % 100 == 0:
                    log.warning(f"[BLE] Waveform notify error x{errors}: {exc}")
            await asyncio.sleep(interval)

    async def _status_loop(self):
        interval = 1.0 / STATUS_RATE_HZ
        while not self._shutdown_evt.is_set():
            try:
                p = self.engine.get_ppg_params()
                running, recording, record_file, pb, pb_file = _engine_state(self.engine)
                snapshot = _param_snapshot(p, running, recording, record_file, pb, pb_file)
                origin = origin_for_tick(time.monotonic(), self._android_grace_until)
                # If the Pi GUI changes a value during the phone grace window,
                # publish that packet as an RPi-originated truth immediately;
                # the phone must not wait for the one-second grace to expire.
                if origin == "android" and self._android_echo_snapshot is not None \
                        and snapshot != self._android_echo_snapshot:
                    origin = "rpi"
                self._seq += 1
                self._status_payload = build_status_json(
                    p, origin, self._seq,
                    running=running, recording=recording, record_file=record_file,
                    pb=pb, pb_file=pb_file,
                ).encode("utf-8")
                if snapshot != self._last_snapshot:
                    log.debug(f"[BLE] Status changed ({origin}): {self._status_payload.decode()}")
                    self._last_snapshot = snapshot
                await self._push(STATUS_UUID, self._status_payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(f"[BLE] Status notify error: {exc}")
            await asyncio.sleep(interval)

    # ─── Called from the bless loop (write/read handlers) ────────────────────

    def on_write(self, value):
        applied = self.handler.handle_raw(value)
        if applied:
            log.info(f"[BLE] Command applied: {applied}")
            # Echo rule (T4): the phone gets ANDROID_GRACE_S of "android"
            # status so its own echoes never move its sliders mid-burst; after
            # the window the status is "rpi" again = actual Pi truth.
            self._android_grace_until = time.monotonic() + ANDROID_GRACE_S
            try:
                p = self.engine.get_ppg_params()
                running, recording, record_file, pb, pb_file = _engine_state(self.engine)
                self._android_echo_snapshot = _param_snapshot(
                    p, running, recording, record_file, pb, pb_file)
            except Exception:
                self._android_echo_snapshot = None

    async def _cmd_file_loop(self):
        """Apply rewrites of PPG_BLE_CMD_FILE as local (origin 'rpi') changes."""
        if os.path.exists(CMD_FILE_PATH):
            last_mtime = os.path.getmtime(CMD_FILE_PATH)  # ignore pre-existing content
        else:
            last_mtime = None  # file created after start is a real command
        while not self._shutdown_evt.is_set():
            try:
                if os.path.exists(CMD_FILE_PATH):
                    mtime = os.path.getmtime(CMD_FILE_PATH)
                    if last_mtime is None or mtime != last_mtime:
                        last_mtime = mtime
                        with open(CMD_FILE_PATH, "r", encoding="utf-8") as fh:
                            obj = json.load(fh)
                        applied = self.handler.handle_command(obj)
                        if applied:
                            log.info(f"[BLE] File command applied: {applied}")
            except Exception as exc:
                log.warning(f"[BLE] Command-file error: {exc}")
            await asyncio.sleep(0.5)

    def status_bytes(self):
        return self._status_payload
