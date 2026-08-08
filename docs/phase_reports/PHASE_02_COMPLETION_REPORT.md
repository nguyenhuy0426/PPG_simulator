# Phase 2 Completion Report — Config Centralization & SpO2 Calibration

**Project:** PPG_simulator_raspi
**Phase spec:** `docs/claude_phases/02_PHASE_CONFIG_AND_SPO2_CALIBRATION.md`
**Date executed:** 2026-07-11
**Status:** COMPLETE — all in-scope items implemented, all tests PASS.

Evidence tags used below:
`[VERIFIED-CODE]` proven by reading source in this repo ·
`[VERIFIED-RUNTIME]` proven by a command actually run in this session ·
`[VERIFIED-USER]` asserted by the user/Phase 1 as a hardware fact ·
`[ENGINEERING-INFERENCE]` reasoned conclusion, not directly measured ·
`[UNKNOWN]` not verifiable with current evidence.

---

## 1. Scope executed (and scope explicitly NOT touched)

**In scope (done):**
1. Centralized the measured 3.2 V DAC full-scale as a single source of truth. `[VERIFIED-CODE]`
2. Removed duplicated 3.3 V DAC scaling/clamping across engine + UI frames. `[VERIFIED-CODE]`
3. Added configurable, validated SpO2 A/B coefficients (`SpO2 = A − B·R`). `[VERIFIED-CODE]`
4. Added forward (`spo2_from_r`) and inverse (`r_target_from_spo2`) functions. `[VERIFIED-CODE]`
5. Preserved backward-compatible config persistence for A/B. `[VERIFIED-CODE]` `[VERIFIED-RUNTIME]`
6. Added narrow unit tests and ran them. `[VERIFIED-RUNTIME]`

**Explicitly NOT touched (deferred per instructions):**
- AC/DC/PI ownership redesign → **Phase 3**. Not started. `[VERIFIED-CODE]`
- OPT101 acquisition → **Phase 5**. Not started. `[VERIFIED-CODE]`
- ADC voltage scaling: `ADC_VOLTAGE_REF = 3.3` left **unchanged** — confirmed at runtime it still reads 3.3. `[VERIFIED-RUNTIME]`
- Phase 1 work: not redone, not rewritten.

---

## 2. Modified / created files

| File | Action | Purpose |
|------|--------|---------|
| `config.py` | MODIFIED | `DAC_FULLSCALE_V=3.2` SSOT + derived `DAC_FULLSCALE_MV`, `DAC_V_PER_STEP`, backward alias `DAC_VOLTAGE_MAX`. `ADC_VOLTAGE_REF` untouched. |
| `calibration.py` | CREATED | SSOT for SpO2 coefficients, forward/inverse R↔SpO2, validation, `dac_voltage_to_code`, `SpO2Calibration` dataclass, R clamp constants. |
| `models/ppg_model.py` | MODIFIED | `PPGParameters` carries `spo2_coeff_a/b`; R computed via `r_target_from_spo2`; clamps use `DAC_FULLSCALE_V`; added `set_spo2_coefficients()`. |
| `core/signal_engine.py` | MODIFIED | `_v_to_dac` delegates to shared `dac_voltage_to_code`; comments corrected to 3.2 V. |
| `ui/frames/pathology_frame.py` | MODIFIED | Removed hardcoded R formula; uses shared calibration + clamp constants. |
| `ui/frames/calibration_frame.py` | MODIFIED | Slider `to=DAC_FULLSCALE_MV`; DAC code via shared converter; draw range uses `DAC_FULLSCALE_MV`. |
| `config_store.py` | MODIFIED | A/B in `_DEFAULTS`; save/load round-trip; validates on load, falls back to defaults on corrupt values. |
| `tests/test_calibration.py` | CREATED | 26 stdlib `unittest` cases (no numpy/hardware deps). |

Incidental: `CLAUDE.md` and `MedicalSimulator` show as modified in `git status` but were **not** touched by Phase 2 (pre-existing working-tree state from before this session). Tracked `.pyc` files changed as a byproduct of running Python. `[VERIFIED-RUNTIME]`

---

## 3. Exact behavior changes

- **DAC scaling.** Previously each site computed `int(v / 3.3 * 4095)`. Now every site calls `dac_voltage_to_code(v)` which uses `DAC_FULLSCALE_V = 3.2`. Consequence: a given voltage now maps to a **slightly higher DAC code** than before (÷3.2 instead of ÷3.3), and full-scale is reached at 3.2 V. `[VERIFIED-CODE]` `[VERIFIED-RUNTIME]`
  - Regression guard confirmed: `dac_voltage_to_code(3.2) == 4095`, and it is **not** equal to the old `int(3.2/3.3*4095)=3969`. `[VERIFIED-RUNTIME]`
- **Truncation preserved.** Conversion still uses `int(...)` truncation (not rounding), matching legacy behavior — only the divisor changed. `[VERIFIED-CODE]`
- **R computation.** `R_target` is now `(A − SpO2)/B` with configurable A/B (defaults 110/25), then clamped to `[0.4, 1.6]`. Physiological clamp range unchanged from prior code. `[VERIFIED-CODE]`
- **Validation.** `B ≤ 0`, non-finite, `bool`, or non-numeric coefficients raise `ValueError`. On persisted-config load, invalid A/B log a warning and fall back to 110/25 rather than crashing or storing a non-invertible mapping. `[VERIFIED-CODE]` `[VERIFIED-RUNTIME]`
- **Persistence.** New keys `spo2_coeff_a/b` are saved; legacy config files lacking them merge to defaults. `[VERIFIED-RUNTIME]`
- **No change** to ADC scaling, signal-generation timing, threading, DAC I2C addresses, or waveform math. `[VERIFIED-CODE]`

---

## 4. Commands actually run & real results

| Command | Result |
|---------|--------|
| `python3 -m unittest tests.test_calibration -v` | **PASS** — `Ran 26 tests in 0.013s / OK`. `[VERIFIED-RUNTIME]` |
| `python3 -c "import config, calibration, config_store; import models.ppg_model; ..."` | **PASS** — `IMPORTS_OK 3.2 3200.0 3.3`. Confirms SSOT values and that `ADC_VOLTAGE_REF` is still 3.3. `[VERIFIED-RUNTIME]` |
| `git status --short` / `git diff --stat` | Captured (see §2 and §8). `[VERIFIED-RUNTIME]` |

**Test coverage of the 26 cases:** forward mapping, inverse mapping, forward↔inverse round-trip across 3 A/B pairs, invalid B (0 and negative), non-finite/non-numeric coefficient rejection, DAC boundary/clamp/midpoint, 3.2-vs-3.3 regression guard, mV↔V conversion parity, `SpO2Calibration` dataclass, and config backward-compat (legacy/valid/corrupt) + `PPGModel` integration.

**NOT RUN / BLOCKED:**
- Full GUI launch (`main.py`) — **NOT RUN**. Requires `customtkinter` + display; out of narrow Phase 2 scope. `[VERIFIED-CODE]`
- Real DAC / I2C hardware output — **NOT RUN / BLOCKED**. No hardware exercised this session; DAC code values are pure integer math, not verified on-wire. `[UNKNOWN]` for physical output voltage.
- `pytest` — not run (system Python lacks it); tests were written stdlib-only so `unittest` suffices. `[VERIFIED-RUNTIME]`

---

## 5. Remaining gaps / known risks

- **UI ↔ engine coefficient wiring:** A/B are stored, validated, and persisted, but there is **no GUI control** yet to edit A/B live. `set_spo2_coefficients()` exists but is not called from any frame. `[VERIFIED-CODE]` — candidate for a later phase, not Phase 2.
- **Physical DAC verification:** 3.2 V full-scale is a `[VERIFIED-USER]` measurement; the code honors it, but on-wire output was not re-measured this session. `[UNKNOWN]`
- **`requirements.txt`:** observed to list `pygame` rather than `customtkinter`. Deliberately **left unchanged** — outside the narrowed Phase 2 scope. Flagging only.
- **Pre-existing unused imports** (`tk` in `pathology_frame.py`, `Optional` in `config_store.py`): not mine, left untouched to avoid scope creep.

---

## 6. Acceptance checklist

- [x] 3.2 V DAC full-scale centralized as single source of truth. `[VERIFIED-CODE]`
- [x] Duplicated 3.3 V scaling/clamping removed (engine + both frames + model). `[VERIFIED-CODE]`
- [x] Configurable A/B coefficients with validation. `[VERIFIED-CODE]`
- [x] Forward + inverse R↔SpO2 functions present and round-trip correct. `[VERIFIED-RUNTIME]`
- [x] Backward-compatible persistence (legacy/valid/corrupt all handled). `[VERIFIED-RUNTIME]`
- [x] Narrow tests added and passing (26/26). `[VERIFIED-RUNTIME]`
- [x] `ADC_VOLTAGE_REF` still 3.3 (not changed by DAC work). `[VERIFIED-RUNTIME]`
- [x] Phase 3 (AC/DC/PI) and Phase 5 (OPT101) NOT started. `[VERIFIED-CODE]`
- [x] No fabricated results; NOT-RUN/BLOCKED items labeled. `[VERIFIED-CODE]`

---

## 7. Do-not-redo handoff for Phase 3

Phase 3 (AC/DC/PI ownership redesign) should build on — **not re-implement** — these now-stable Phase 2 primitives:

- **DAC scaling is centralized.** Always use `calibration.dac_voltage_to_code()` / `config.DAC_FULLSCALE_V`. Do not reintroduce `/3.3` or `*4095` literals.
- **SpO2 calibration is centralized.** Use `calibration.spo2_from_r` / `r_target_from_spo2` / `SpO2Calibration` and the `R_CLAMP_MIN/MAX` constants. A/B live on `PPGParameters.spo2_coeff_a/b` and persist via `config_store`.
- **Do not change `ADC_VOLTAGE_REF` (3.3)** — separate hardware fact from Phase 1; unrelated to DAC full-scale.
- **Persistence contract is fixed:** keys `spo2_coeff_a/b`; loader validates and falls back to defaults. Extend the dict-merge pattern for any new Phase 3 keys — do not break legacy files.
- **What is still open for Phase 3:** AC/DC baseline and Perfusion-Index ownership currently spread across `ppg_model.py` and `signal_engine.py`; that consolidation is Phase 3's job. `dc_baseline`, `measured_peak/valley`, and PI→AC amplitude math were intentionally left as-is.

---

## 8. Git diff summary (tracked files)

```
config.py                      | 12 +-
config_store.py                | 27 +++++
core/signal_engine.py          | 19 +--
models/ppg_model.py            | 49 ++++++--
ui/frames/calibration_frame.py | 16 +--
ui/frames/pathology_frame.py   |  8 +-
```
Plus untracked new files: `calibration.py`, `tests/test_calibration.py`, `docs/phase_reports/PHASE_02_COMPLETION_REPORT.md`.
(`CLAUDE.md`, `MedicalSimulator`, and `.pyc` artifacts appear in `git status` but are not Phase 2 source changes.) `[VERIFIED-RUNTIME]`

---

**STOP.** Phase 2 is complete. Phase 3 not started — awaiting explicit instruction.
