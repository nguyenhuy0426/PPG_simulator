"""Parse / validate / dispatch layer for the advanced simulation controls.

A Tk command callback that raises takes down the event loop or pops an
unreadable traceback, so nothing here propagates an exception: every entry
point returns ``(ok, message)`` and the panel renders the message.

Validation itself is NOT duplicated here — the DAC headroom rules live in
calibration.validate_ac_dc, the SpO2 slope rule in validate_coefficients and
the artefact bandwidth rule in models.noise. This module only converts the
text the user typed into numbers, forwards them, and turns the resulting
ValueError into something readable.
"""

from models.ppg_model import POLARITY_ABOVE_DC, POLARITY_BELOW_DC

# Blank Red DC means "mirror the IR channel" rather than "zero".
_MIRROR_IR = ""


def _to_float(text: str, field: str) -> float:
    """Parse one entry box.

    Raises:
        ValueError: with a message naming the offending field.
    """
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number, got {text!r}")


def ac_mv_from_pi(pi_percent: float, dc_ir_mv: float) -> float:
    """AC amplitude implied by a perfusion index (clinical PI = AC/DC x 100)."""
    return pi_percent / 100.0 * dc_ir_mv


def pi_from_ac_dc(ac_ir_mv: float, dc_ir_mv: float) -> float:
    """Perfusion index implied by an AC/DC pair; 0 for a non-positive DC."""
    if dc_ir_mv <= 0.0:
        return 0.0
    return ac_ir_mv / dc_ir_mv * 100.0


def apply_ac_dc(engine, ac_ir_text: str, dc_ir_text: str,
                dc_red_text: str) -> tuple:
    """Set the master AC/DC pair. A blank Red DC mirrors the IR channel."""
    try:
        ac_ir_mv = _to_float(ac_ir_text, "AC (IR)")
        dc_ir_mv = _to_float(dc_ir_text, "DC (IR)")
        dc_red_mv = (dc_ir_mv if str(dc_red_text).strip() == _MIRROR_IR
                     else _to_float(dc_red_text, "DC (Red)"))
        engine.update_ac_dc(ac_ir_mv, dc_ir_mv, dc_red_mv)
    except ValueError as exc:
        return False, str(exc)
    pi = pi_from_ac_dc(ac_ir_mv, dc_ir_mv)
    return True, (f"AC {ac_ir_mv:.1f} mV / DC {dc_ir_mv:.0f}·{dc_red_mv:.0f} mV "
                  f"-> PI {pi:.2f} %")


def apply_polarity(engine, polarity: int) -> tuple:
    """Select AC above (0) or below (1) the DC level."""
    try:
        engine.update_polarity(polarity)
    except ValueError as exc:
        return False, str(exc)
    label = "above DC" if polarity == POLARITY_ABOVE_DC else "below DC"
    return True, f"Pulse rides {label}"


def apply_spo2_coefficients(engine, coeff_a_text: str,
                            coeff_b_text: str) -> tuple:
    """Set the device-specific SpO2 calibration (SpO2 = A - B*R)."""
    try:
        coeff_a = _to_float(coeff_a_text, "Coefficient A")
        coeff_b = _to_float(coeff_b_text, "Coefficient B")
        engine.update_spo2_coefficients(coeff_a, coeff_b)
    except ValueError as exc:
        return False, str(exc)
    return True, f"SpO2 = {coeff_a:.1f} - {coeff_b:.1f}·R"


def apply_noise(engine, kind: str, amplitude_text: str,
                freq_text: str) -> tuple:
    """Select the artefact kind and its absolute amplitude / frequency."""
    try:
        amplitude_mv = _to_float(amplitude_text, "Artefact amplitude")
        freq_hz = _to_float(freq_text or "0", "Artefact frequency")
        engine.update_noise(kind, amplitude_mv=amplitude_mv, freq_hz=freq_hz)
    except ValueError as exc:
        return False, str(exc)
    if freq_hz > 0.0:
        return True, f"{kind}: {amplitude_mv:.1f} mV @ {freq_hz:.1f} Hz"
    return True, f"{kind}: {amplitude_mv:.1f} mV"


def format_stats(stats: dict) -> str:
    """One-line ring-buffer health summary for the status bar.

    Overruns mean the DAC thread fell behind and samples were dropped;
    underruns mean it ran dry. Both must stay at 0 for the output to be a
    faithful reproduction of the commanded waveform.
    """
    return ("buffer {fill} | overrun {ov} | underrun {un} | dropped {dr}"
            .format(fill=stats.get("buffer_fill", 0),
                    ov=stats.get("overruns", 0),
                    un=stats.get("underruns", 0),
                    dr=stats.get("dropped_samples", 0)))


__all__ = [
    "POLARITY_ABOVE_DC", "POLARITY_BELOW_DC",
    "ac_mv_from_pi", "pi_from_ac_dc", "apply_ac_dc", "apply_polarity",
    "apply_spo2_coefficients", "apply_noise", "format_stats",
]
