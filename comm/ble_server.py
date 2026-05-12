"""
ble_server.py — BLE Peripheral for Raspberry Pi using 'bless'
"""

import asyncio
import json
import threading
import time
from bless import (
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions
)
from comm.logger import log

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID = "12345678-1234-5678-1234-56789abcdef2"
STATUS_UUID = "12345678-1234-5678-1234-56789abcdef3"

class BleServer:
    def __init__(self, engine, display):
        self.engine = engine
        self.display = display
        self.server = None
        self.loop = None
        self.running = False
        self._thread = None
        self._last_status_time = 0

    def begin(self):
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._setup_and_run())

    async def _setup_and_run(self):
        log.info("[BLE] Starting BLE Server...")
        self.server = BlessServer(name="MedicalSimulatorRPi")
        self.server.read_request_func = self.on_read_request
        self.server.write_request_func = self.on_write_request

        try:
            await self.server.add_new_service(SERVICE_UUID)
            
            # Command Characteristic (Write)
            await self.server.add_new_characteristic(
                SERVICE_UUID,
                WRITE_UUID,
                GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
                b"",
                GATTAttributePermissions.writeable
            )

            # Waveform Characteristic (Notify)
            await self.server.add_new_characteristic(
                SERVICE_UUID,
                NOTIFY_UUID,
                GATTCharacteristicProperties.notify | GATTCharacteristicProperties.read,
                b"0.0",
                GATTAttributePermissions.readable
            )

            # Status Characteristic (Notify)
            await self.server.add_new_characteristic(
                SERVICE_UUID,
                STATUS_UUID,
                GATTCharacteristicProperties.notify | GATTCharacteristicProperties.read,
                b"{}",
                GATTAttributePermissions.readable
            )

            await self.server.start()
            log.info("[BLE] BLE Server running and advertising.")
            self.display.ble_status = "BLE: Advertising"

            while self.running:
                # 50Hz update for waveform
                ac_ir = self.engine.get_current_display_ir()
                val_str = f"{ac_ir:.2f}"
                self.server.get_characteristic(NOTIFY_UUID).value = val_str.encode("utf-8")
                self.server.update_value(SERVICE_UUID, NOTIFY_UUID)

                # 2Hz update for status
                now = time.time()
                if now - self._last_status_time >= 0.5:
                    self._last_status_time = now
                    p = self.engine.get_ppg_params()
                    status = {
                        "hr": float(p.heart_rate),
                        "pi": float(p.perfusion_index),
                        "noise": float(p.noise_level),
                        "condition": int(p.condition),
                        "spo2": int(p.spo2),
                        "rr": int(p.resp_rate)
                    }
                    status_json = json.dumps(status)
                    self.server.get_characteristic(STATUS_UUID).value = status_json.encode("utf-8")
                    self.server.update_value(SERVICE_UUID, STATUS_UUID)

                await asyncio.sleep(0.02) # 50Hz

        except Exception as e:
            log.error(f"[BLE] Error: {e}")
            self.display.ble_status = "BLE: Error"
        finally:
            if self.server:
                await self.server.stop()
            log.info("[BLE] Server stopped.")

    def on_read_request(self, characteristic):
        return characteristic.value

    def on_write_request(self, characteristic, value):
        if characteristic.uuid.lower() == WRITE_UUID.lower():
            try:
                cmd_str = value.decode("utf-8")
                log.debug(f"[BLE] Received command: {cmd_str}")
                cmd = json.loads(cmd_str)
                # Ensure the display knows we are connected if we get a write
                self.display.ble_status = "BLE: Connected"
                
                if "hr" in cmd:
                    self.engine.update_heart_rate(cmd["hr"])
                if "pi" in cmd:
                    self.engine.update_perfusion_index(cmd["pi"])
                if "noise" in cmd:
                    self.engine.update_noise_level(cmd["noise"])
                if "condition" in cmd:
                    self.engine.change_condition(cmd["condition"])
                if "spo2" in cmd:
                    self.engine.update_spo2(cmd["spo2"])
                if "rr" in cmd:
                    self.engine.update_resp_rate(cmd["rr"])
            except Exception as e:
                log.error(f"[BLE] Failed to parse command: {e}")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)
