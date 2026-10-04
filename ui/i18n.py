"""Small, dependency-free UI vocabulary for the application shell."""

LANGUAGE_EN = "en"
LANGUAGE_VI = "vi"
LANGUAGES = {LANGUAGE_EN: "English", LANGUAGE_VI: "Tiếng Việt"}

_TEXT = {
    LANGUAGE_EN: {
        "title": "PPG Simulator • Optical signal workstation", "workstation": "OPTICAL SIGNAL WORKSTATION",
        "simulation": "SIMULATION / NO HARDWARE", "hardware": "HARDWARE MODE",
        "classic": "Classic / Monitor", "calibration": "Calibration / RX",
        "recordings": "Recordings", "neural": "PPG morphology", "ready": "Ready",
        "research": "Research simulator", "settings": "Signal setup", "language": "Language",
        "settings_short": "Setup", "theme_dark": "Dark theme", "theme_light": "Light theme",
        "language_hint": "Choose the display language. Technical abbreviations and units remain unchanged.",
        "language_applied": "Language saved. Main navigation was updated.", "standby": "STANDBY",
        "running": "RUNNING", "tx_ready": "TX DAC READY", "tx_unavailable": "TX DAC UNAVAILABLE",
        # Footer
        "mode_dry_run": "DRY RUN", "mode_hardware": "HARDWARE", "mode_no_dac": "NO DAC",
        "tx_model": "TX model", "dac_target": "DAC target", "buffer": "Buffer", "lost": "Lost",
        "clipped": "Clipped",
        # Classic page
        "tx_card": "TX output signal", "rx_card": "RX received signal",
        "record": "Record CSV", "save_record": "Save CSV", "start": "Start output", "stop": "Stop output",
        "hr": "Heart rate", "spo2": "SpO₂ target", "rr": "Respiration", "pi": "Perfusion index PI",
        "red_manual": "manual", "red_follows": "from SpO₂", "red_negative": "R < 0, clamped",
        "badge_red_manual": "RED AC manual", "badge_locked": "AC/DC locked",
        "tx_idle": "Output is off", "tx_idle_sub": "Press Start output; DACs hold 0 V until then",
        "status_emitting": "Driving the LEDs.",
        "status_emitting_detail": "IR (0x{ir:02X}) and RED (0x{red:02X}) receive commands at {rate} Hz.",
        "status_dry": "Simulation running.",
        "status_dry_detail": "Dry run: no DAC is written and no LED is driven.",
        "status_no_dac": "Signal computed, DAC not responding.",
        "status_no_dac_detail": "No MCP4725 at 0x{ir:02X}/0x{red:02X}; the LEDs are not driven.",
        "status_dac_errors": "DAC write errors.",
        "status_dac_errors_detail": "IR errors {ir_err}, RED errors {red_err}; check the I²C wiring.",
        "status_calibrating": "Calibration sine running.",
        "status_clip": "30-second sequence playing.",
        "status_stopped": "Output stopped.",
        "status_stopped_detail": "DACs held at 0 V (LEDs off).",
        "status_stopped_no_dac": "No MCP4725 found at 0x{ir:02X}/0x{red:02X}; output stays off.",
        "applied": "Applied to the generator.", "csv_saved": "CSV saved in dataset/.",
        "record_needs_run": "Start output before recording.", "record_failed": "Recording could not start.",
        "gaussian_selected": "Original 3-Gaussian shape selected.",
    },
    LANGUAGE_VI: {
        "title": "Trình mô phỏng PPG • Trạm tín hiệu quang học", "workstation": "TRẠM TÍN HIỆU QUANG HỌC",
        "simulation": "MÔ PHỎNG / KHÔNG PHẦN CỨNG", "hardware": "CHẾ ĐỘ PHẦN CỨNG",
        "classic": "Cổ điển / Theo dõi", "calibration": "Hiệu chuẩn / RX",
        "recordings": "Bản ghi", "neural": "Hình thái PPG", "ready": "Sẵn sàng",
        "research": "Trình mô phỏng nghiên cứu", "settings": "Thiết lập tín hiệu", "language": "Ngôn ngữ",
        "settings_short": "Thiết lập", "theme_dark": "Giao diện tối", "theme_light": "Giao diện sáng",
        "language_hint": "Chọn ngôn ngữ hiển thị. Viết tắt kỹ thuật và đơn vị được giữ nguyên.",
        "language_applied": "Đã lưu ngôn ngữ. Thanh điều hướng đã được cập nhật.", "standby": "CHỜ",
        "running": "ĐANG CHẠY", "tx_ready": "DAC TX SẴN SÀNG", "tx_unavailable": "DAC TX KHÔNG SẴN SÀNG",
        "mode_dry_run": "MÔ PHỎNG", "mode_hardware": "PHẦN CỨNG", "mode_no_dac": "KHÔNG CÓ DAC",
        "tx_model": "Mô hình TX", "dac_target": "DAC đích", "buffer": "Bộ đệm", "lost": "Mất mẫu",
        "clipped": "Cắt đỉnh",
        "tx_card": "Tín hiệu phát TX", "rx_card": "Tín hiệu thu RX",
        "record": "Ghi CSV", "save_record": "Lưu CSV", "start": "Phát", "stop": "Dừng phát",
        "hr": "Nhịp tim", "spo2": "SpO₂ mục tiêu", "rr": "Nhịp thở", "pi": "Chỉ số tưới máu PI",
        "red_manual": "đặt tay", "red_follows": "theo SpO₂", "red_negative": "R < 0, đã kẹp",
        "badge_red_manual": "Tách AC RED", "badge_locked": "Khoá AC/DC",
        "tx_idle": "Chưa phát", "tx_idle_sub": "Nhấn Phát để bắt đầu; DAC giữ 0 V cho tới lúc đó",
        "status_emitting": "Đang phát ra LED.",
        "status_emitting_detail": "IR (0x{ir:02X}) và RED (0x{red:02X}) nhận lệnh ở {rate} Hz.",
        "status_dry": "Đang chạy mô phỏng.",
        "status_dry_detail": "Dry-run: không ghi DAC, LED không được điều khiển.",
        "status_no_dac": "Đang tính tín hiệu, DAC không phản hồi.",
        "status_no_dac_detail": "Không thấy MCP4725 ở 0x{ir:02X}/0x{red:02X}; LED không được điều khiển.",
        "status_dac_errors": "Lỗi ghi DAC.",
        "status_dac_errors_detail": "IR lỗi {ir_err}, RED lỗi {red_err}; kiểm tra dây I²C.",
        "status_calibrating": "Đang phát sine hiệu chuẩn.",
        "status_clip": "Đang phát chuỗi 30 giây.",
        "status_stopped": "Đã dừng phát.",
        "status_stopped_detail": "DAC giữ 0 V (LED tắt).",
        "status_stopped_no_dac": "Không thấy MCP4725 ở 0x{ir:02X}/0x{red:02X}; đầu ra vẫn tắt.",
        "applied": "Đã áp dụng cho bộ phát.", "csv_saved": "Đã lưu CSV vào dataset/.",
        "record_needs_run": "Hãy Phát trước khi ghi.", "record_failed": "Không bắt đầu ghi được.",
        "gaussian_selected": "Đã chọn dạng 3-Gaussian gốc.",
    },
}

# Condition presets keep their model names (CONDITION_NAMES) as identifiers;
# these are display labels only, in the same order.
CONDITION_LABELS = {
    LANGUAGE_EN: ("Normal", "Arrhythmia", "Weak perfusion", "Vasoconstriction",
                  "Strong perfusion", "Vasodilation"),
    LANGUAGE_VI: ("Bình thường", "Loạn nhịp", "Tưới máu yếu", "Co mạch",
                  "Tưới máu mạnh", "Giãn mạch"),
}


def normalise_language(value):
    return value if value in LANGUAGES else LANGUAGE_EN


def text(language, key):
    language = normalise_language(language)
    return _TEXT[language].get(key, _TEXT[LANGUAGE_EN].get(key, key))


def condition_labels(language):
    return CONDITION_LABELS[normalise_language(language)]
