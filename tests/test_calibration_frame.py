"""Calibration page texts: the Δ legend is always shown and TX shows level ± amplitude as the DACs output it."""
import os
import unittest

os.environ.setdefault("PPG_DRY_RUN", "1")
HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class CalibrationTextsTest(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from ui.frames.calibration_frame import CalibrationFrame
        self.root = ctk.CTk()
        self.root.language = "vi"
        self.addCleanup(self.root.destroy)
        self.frame = CalibrationFrame(self.root)
        self.frame.pack()
        self.root.update()

    def test_delta_legend_is_shown_without_running(self):
        self.assertEqual(self.frame.delta_legend.cget("text"), "Δ = mức thu − mức phát (mV)")

    def test_slider_ranges_follow_dac_and_opt101_limits(self):
        f = self.frame
        self.assertEqual((f.ir_slider.minimum, f.ir_slider.maximum), (0, 2400))
        self.assertEqual((f.red_slider.minimum, f.red_slider.maximum), (0, 2400))
        self.assertEqual(f.swing_slider.maximum, 1200)
        self.assertEqual((f.frequency_slider.minimum, f.frequency_slider.maximum), (1.0, 5.0))
        self.assertEqual((f.tolerance_slider.minimum, f.tolerance_slider.maximum), (1, 100))

    def test_dark_lane_says_the_led_is_not_lit(self):
        from core.calib_match import Match
        self.frame._target = (1000.0, 1000.0, 0.0)
        self.frame._matches = {"IR": Match(False, (6.0,), -994.0), "RED": Match(False, (890.0,), -110.0)}
        self.frame._paint_dots(True, 0.0)
        self.assertEqual(self.frame.dot_text["IR"].cget("text"), "IR LED chưa sáng (6 mV): DAC đã ghi, kiểm tra driver/LED")
        self.assertEqual(self.frame.dot_text["RED"].cget("text"), "RED 890 mV  Δ-110")

    def test_zero_mv_lane_blames_the_receiver_not_the_led(self):
        # Measured on the Pi: a dead RED receiver reads 0 mV even with its DAC at 0, below the OPT101 dark level.
        from core.calib_match import Match
        for red_level in (1000.0, 0.0):
            self.frame._target = (1000.0, red_level, 0.0)
            self.frame._matches = {"IR": Match(True, (1001.0,), 1.0), "RED": Match(False, (0.0,), -red_level)}
            self.frame._paint_dots(True, 0.0)
            self.assertEqual(self.frame.dot_text["RED"].cget("text"),
                             "RED RX 0 mV, thấp hơn mức tối ~6 mV: OPT101 RED mất nguồn/GND hoặc dây ADC, không phải LED")

    def test_spo2_calibration_button_and_saved_result(self):
        from unittest import mock
        from core import rx_spo2_cal
        self.assertEqual(self.frame.spo2_btn.cget("text"), "Hiệu chuẩn SpO₂")
        fit = rx_spo2_cal.RxSpo2Calibration(118.04, 30.96, 1000.0, 1000.0, 0.62, ((98.0, 0.6), (70.0, 1.5)), 0.0)
        self.frame._spo2_run = mock.Mock(calibration=fit, error=None)
        with mock.patch.object(rx_spo2_cal, "save", return_value=True) as save:
            self.frame._spo2_finished()
        save.assert_called_once_with(fit)
        self.assertIsNone(self.frame._spo2_run)
        self.assertEqual(self.frame.status.cget("text"),
                         "Đã lưu: SpO₂ thu = 118.0 − 31.0·R, lệch tối đa 0.6 % ở DC IR 1000 / RED 1000 mV."
                         " Đổi DC hay chỉnh carrier thì chạy lại.")

    def test_spo2_calibration_failures_are_explained(self):
        from unittest import mock
        for error, text in (("residual:3.4", "R thu không theo đường thẳng (lệch 3.4 % > 2 %): làn thu chưa ổn định"),
                            ("reason:mismatch", "IR và RED không cùng nhịp"), ("aborted", "đã dừng")):
            self.frame._spo2_run = mock.Mock(calibration=None, error=error)
            self.frame._spo2_finished()
            self.assertEqual(self.frame.status.cget("text"), "Hiệu chuẩn SpO₂ không thành: " + text)

    def test_tx_range_is_level_plus_minus_amplitude_clipped_at_zero(self):
        self.frame._target = (1000.0, 500.0, 1000.0)
        self.frame._paint_tx_range(True)
        self.assertEqual(self.frame.tx_range.cget("text"), "Phát: IR 0–2000 · RED 0–1500 mV")
        self.frame._target = (1000.0, 800.0, 0.0)
        self.frame._paint_tx_range(True)
        self.assertEqual(self.frame.tx_range.cget("text"), "Phát: IR 1000 · RED 800 mV")
        self.frame._paint_tx_range(False)
        self.assertEqual(self.frame.tx_range.cget("text"), "")


if __name__ == "__main__":
    unittest.main()
