"""BLE GATT server for the PPG simulator (Android remote control).

Re-implements the historical comm/ble_server.py surface using `bless` 0.3.0
(pure-Python, dbus-next). Protocol is FROZEN to match the Android app
(com.medical.simulator, `RpiBleManager`):

    Service  12345678-1234-5678-1234-56789abcdef0
    WRITE    ...def1   app -> Pi   UTF-8 JSON command (delta merge)
    NOTIFY   ...def2   Pi  -> app  UTF-8 "%.2f" display-IR millivolts, ~50 Hz
    STATUS   ...def3   Pi  -> app  UTF-8 JSON snapshot, ~5 Hz (+ readable)

Echo/sync rule (must stay in lockstep with the Android side):
    origin "android" — the values changed because an app command was applied;
                       the phone updates its metric cards but NOT its sliders.
    origin "rpi"     — the values changed locally (GUI/engine); the phone
                       updates sliders + cards.

Threading: bless runs in a daemon thread with its own asyncio loop. Tk owns
the main thread. BLE callbacks never touch Tk — they only call thread-safe
SignalEngine methods. See docs/ble_protocol.md.
"""

import asyncio
import json
import os
import threading

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

# When a BLE client sends its first command and the simulation is still
# STOPPED, start it once so the phone immediately sees a waveform.
AUTO_START_ON_FIRST_COMMAND = True

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


class BLECommandHandler:
    """Pure command application logic (testable without BlueZ/bless)."""

    def __init__(self, engine):
        self.engine = engine

    def handle_command(self, obj):
        """Apply a decoded command dict (delta merge). Returns what was applied.

        Unknown keys are ignored; values are clamped to models.limits before
        the transactional engine wrappers run, so invalid input can never
        crash the BLE loop.
        """
        from core.signal_engine import SIG_STOPPED
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

        if "hr" in obj:
            v = HEART_RATE.clamp(_to_float(obj["hr"], HEART_RATE.default))
            self.engine.update_heart_rate(v)
            applied["hr"] = v

        if "spo2" in obj:
            v = SPO2.clamp(_to_float(obj["spo2"], SPO2.default))
            self.engine.update_spo2(v)
            applied["spo2"] = v

        if "rr" in obj:
            v = RESP_RATE.clamp(_to_float(obj["rr"], RESP_RATE.default))
            self.engine.update_resp_rate(v)
            applied["rr"] = v

        if "pi" in obj:
            v = PERFUSION_INDEX.clamp(_to_float(obj["pi"], PERFUSION_INDEX.default))
            self.engine.update_perfusion_index(v)
            applied["pi"] = v

        if "noise" in obj:
            v = NOISE_LEVEL.clamp(_to_float(obj["noise"], NOISE_LEVEL.default))
            self.engine.update_noise_level(v)
            applied["noise"] = v

        if "condition" in obj:
            v = max(0, min(5, _to_int(obj["condition"], 0)))
            self.engine.change_condition(v)
            applied["condition"] = v

        # AC/DC amplitude (mV). Absent keys pass through the current value so a
        # partial command never resets the other channel (None = derive mode).
        if "ac_ir_mv" in obj or "ac_red_mv" in obj:
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

        if "dc_ir_mv" in obj or "dc_red_mv" in obj:
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

        # Convenience: first BLE command on a stopped engine starts the sim so
        # the phone immediately receives a waveform (once per server lifetime).
        if applied and AUTO_START_ON_FIRST_COMMAND:
            try:
                if self.engine.state == SIG_STOPPED and not getattr(self, "_auto_started", False):
                    self._auto_started = True
                    log.info("[BLE] Engine stopped — auto-starting simulation for BLE client")
                    self.engine.start_simulation(self.engine.get_ppg_params().condition)
            except Exception as exc:  # never let auto-start kill the BLE loop
                log.warning(f"[BLE] Auto-start failed: {exc}")

        return applied

    def handle_raw(self, data):
        """Decode raw write bytes -> applied dict. Swallows all parse errors."""
        try:
            text = bytes(data).decode("utf-8", errors="replace").strip()
            if not text:
                return {}
            return self.handle_command(json.loads(text))
        except Exception as exc:
            log.warning(f"[BLE] Failed to parse command: {exc}")
            return {}


def build_status_json(p, origin, seq):
    """Compact status JSON for the STATUS characteristic (~5 Hz).

    Derived (None) AC setpoints are reported as their nominal values so the
    phone sliders always show what the generator actually outputs.
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
        "origin": origin,
        "seq": int(seq),
    }
    return json.dumps(payload, separators=(",", ":"))


def _param_snapshot(p):
    """Tuple of the parameters the echo rule tracks."""
    return (
        p.heart_rate, p.spo2, p.resp_rate, p.perfusion_index, p.noise_level,
        p.condition, p.ac_ir_mv, p.ac_red_mv, p.dc_ir_mv, p.dc_red_mv,
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
        self._pending_android = False
        self._last_snapshot = None
        self._last_origin = "rpi"
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
                snapshot = _param_snapshot(p)
                if self._pending_android:
                    origin, self._pending_android = "android", False
                elif snapshot != self._last_snapshot:
                    origin = "rpi"
                else:
                    origin = self._last_origin
                self._seq += 1
                self._status_payload = build_status_json(p, origin, self._seq).encode("utf-8")
                self._last_snapshot = snapshot
                self._last_origin = origin
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
            self._pending_android = True  # echo rule: phone ignores its own echo

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
