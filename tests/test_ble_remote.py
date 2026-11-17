"""BLE protocol v3 helpers (comm/ble_remote.py) and the command handler's page-request queue."""
import json
import os
import unittest

os.environ.setdefault("PPG_DRY_RUN", "1")

from comm import ble_remote as R
from comm.ble_server import BLECommandHandler, BleServer


class FakeEngine:
    def __init__(self):
        self.calls = []

    def update_heart_rate(self, value):
        self.calls.append(("hr", value))

    update_spo2 = update_resp_rate = update_noise_level = lambda self, value: None


class RemoteRequestTest(unittest.TestCase):
    def test_page_keys_are_kept_and_bad_shapes_dropped(self):
        request = R.remote_request({"view": "calibration", "cal": {"run": True, "ir": 900}, "nn": [],
                                    "rec": "x", "beep": "yes", "gauss": 1, "hr": 80})
        self.assertEqual(request, {"view": "calibration", "cal": {"run": True, "ir": 900}})
        self.assertEqual(R.remote_request({"view": "settings"}), {})
        self.assertEqual(R.remote_request({"beep": False, "gauss": True}), {"beep": False, "gauss": True})

    def test_number_accepts_only_finite_json_numbers(self):
        self.assertEqual(R.number(3), 3.0)
        self.assertIsNone(R.number(True))
        self.assertIsNone(R.number("5"))
        self.assertIsNone(R.number(float("nan")))

    def test_handler_queues_page_keys_and_still_applies_setpoints(self):
        engine, queued = FakeEngine(), []
        handler = BLECommandHandler(engine, remote_queue=queued.append)
        applied = handler.handle_command({"hr": 90, "view": "neural", "nn": {"gen": True}})
        self.assertEqual(engine.calls, [("hr", 90.0)])
        self.assertEqual(queued, [{"view": "neural", "nn": {"gen": True}}])
        self.assertEqual(applied["view"], "neural")

    def test_handler_without_queue_ignores_page_keys(self):
        self.assertEqual(BLECommandHandler(FakeEngine()).handle_command({"view": "neural"}), {})


class PartTest(unittest.TestCase):
    def test_long_text_is_shortened_to_the_byte_limit(self):
        data = R.fit_part("calst", {"s": "Hiệu chuẩn SpO₂ thu: điểm 2/4 " * 20, "c": "accent", "n": 12.5})
        self.assertLessEqual(len(data), R.UI_PART_MAX_BYTES)
        obj = json.loads(data)
        self.assertEqual((obj["k"], obj["c"], obj["n"]), ("calst", "accent", 12.5))
        self.assertTrue(obj["s"].endswith("…"))

    def test_fields_may_name_their_own_kind(self):
        self.assertEqual(json.loads(R.fit_part("ls1", {"k": "ls", "c": 1}))["k"], "ls")

    def test_preview_chunks_rebuild_each_lane(self):
        lane = [(i / 40, 1500 + (i % 40)) for i in range(320)]
        parts = R.preview_parts([lane, lane])
        self.assertEqual(len(parts), 8)
        for _name, fields in parts:
            self.assertLessEqual(len(R.fit_part("pv", fields)), R.UI_PART_MAX_BYTES)
        values = [v for _n, f in parts if f["l"] == 0 for v in f["v"]]
        self.assertEqual(len(values), 160)
        self.assertEqual((min(values), max(values)), (0, 999))
        self.assertEqual(len({f["id"] for _n, f in parts}), 1)


class StreamTest(unittest.TestCase):
    def test_frame_fits_and_takes_both_sides(self):
        tx = [R.pair(1520.4 + i, 1510.2) for i in range(40)]
        rx = [R.pair(470.1, None) for _ in range(40)]
        frame, used_tx, used_rx = R.pack_stream(tx, rx)
        self.assertLessEqual(len(frame), R.STREAM_MAX_BYTES)
        text = frame.decode()
        self.assertTrue(text.startswith("T1520.4,1510.2;"))
        self.assertIn("|R470.1,;", text)
        self.assertGreater(used_tx, 3)
        self.assertGreater(used_rx, 3)
        self.assertEqual(R.pack_stream([], [])[0], b"T|R")

    def test_decimate_keeps_one_row_per_step_and_follows_a_restart(self):
        rows = [(i / 100, i) for i in range(300)]
        kept, last = R.decimate(rows, None)
        self.assertAlmostEqual(kept[0][0], 2.49, places=2)          # last half second only
        self.assertTrue(all(b[0] - a[0] >= 0.0199 for a, b in zip(kept, kept[1:])))
        more, last2 = R.decimate(rows + [(3.0, 0), (3.01, 0), (3.02, 0)], last)
        self.assertEqual([r[0] for r in more], [3.01])
        restarted, _ = R.decimate([(i / 100, i) for i in range(50)], last2)
        self.assertTrue(restarted)


class ServerQueueTest(unittest.TestCase):
    def test_requests_parts_and_stream_without_bluez(self):
        server = BleServer(FakeEngine())
        server.on_write(b'{"view":"recordings","rec":{"sel":"data_1.csv"}}')
        self.assertEqual(server.take_ui_requests(), [{"view": "recordings", "rec": {"sel": "data_1.csv"}}])
        self.assertEqual(server.take_ui_requests(), [])
        server.publish_ui([("page", {"v": "monitor"}), ("tx", {"l": []})])
        self.assertEqual(json.loads(server.ui_page_bytes())["v"], "monitor")
        self.assertEqual(list(server._ui_dirty), ["page", "tx"])
        server._ui_dirty.clear()
        server.publish_ui([("page", {"v": "monitor"})])            # unchanged, tx gone
        self.assertEqual(list(server._ui_dirty), [])
        self.assertEqual(sorted(server._ui_parts), ["page"])
        server.push_stream(["1.0,2.0"] * 150, [])
        self.assertEqual(len(server._stream_tx), R.STREAM_BACKLOG)


if __name__ == "__main__":
    unittest.main()
