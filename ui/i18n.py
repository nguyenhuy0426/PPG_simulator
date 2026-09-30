"""Small, dependency-free UI vocabulary for the application shell."""

LANGUAGE_EN = "en"
LANGUAGE_VI = "vi"
LANGUAGES = {LANGUAGE_EN: "English", LANGUAGE_VI: "Tiếng Việt"}

_TEXT = {
    LANGUAGE_EN: {
        "title": "PPG Simulator • Optical signal workstation", "workstation": "OPTICAL SIGNAL WORKSTATION",
        "simulation": "SIMULATION / NO HARDWARE", "hardware": "HARDWARE MODE",
        "classic": "01   Classic / Monitor", "calibration": "02   Calibration / RX",
        "recordings": "03   Recordings", "neural": "04   PPG morphology", "ready": "Ready",
        "research": "Research simulator", "settings": "Signal setup", "language": "Language",
        "language_hint": "Choose the display language. Technical abbreviations and units remain unchanged.",
        "language_applied": "Language saved. Main navigation was updated.", "standby": "STANDBY",
        "running": "RUNNING", "tx_ready": "TX DAC READY", "tx_unavailable": "TX DAC UNAVAILABLE",
    },
    LANGUAGE_VI: {
        "title": "Trình mô phỏng PPG • Trạm tín hiệu quang học", "workstation": "TRẠM TÍN HIỆU QUANG HỌC",
        "simulation": "MÔ PHỎNG / KHÔNG PHẦN CỨNG", "hardware": "CHẾ ĐỘ PHẦN CỨNG",
        "classic": "01   Cổ điển / Theo dõi", "calibration": "02   Hiệu chuẩn / RX",
        "recordings": "03   Bản ghi", "neural": "04   Hình thái PPG", "ready": "Sẵn sàng",
        "research": "Trình mô phỏng nghiên cứu", "settings": "Thiết lập tín hiệu", "language": "Ngôn ngữ",
        "language_hint": "Chọn ngôn ngữ hiển thị. Viết tắt kỹ thuật và đơn vị được giữ nguyên.",
        "language_applied": "Đã lưu ngôn ngữ. Thanh điều hướng đã được cập nhật.", "standby": "CHỜ",
        "running": "ĐANG CHẠY", "tx_ready": "DAC TX SẴN SÀNG", "tx_unavailable": "DAC TX KHÔNG SẴN SÀNG",
    },
}


def normalise_language(value):
    return value if value in LANGUAGES else LANGUAGE_EN


def text(language, key):
    language = normalise_language(language)
    return _TEXT[language].get(key, _TEXT[LANGUAGE_EN].get(key, key))
