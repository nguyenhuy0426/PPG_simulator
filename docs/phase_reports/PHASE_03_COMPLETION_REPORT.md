# Phase 3 Completion Report — AC/DC/PI and Red/IR SpO2 Waveform Model

**Project:** PPG_simulator_raspi
**Phase spec:** `docs/claude_phases/03_PHASE_AC_DC_PI_AND_RED_IR_MODEL.md`
**Date executed:** 2026-07-12

Evidence tags used below:
`[VERIFIED-CODE]` proven by reading source in this repo ·
`[VERIFIED-RUNTIME]` proven by a command actually run in this session ·
`[VERIFIED-USER]` asserted by the user / Phase 1 as a hardware fact ·
`[ENGINEERING-INFERENCE]` reasoned conclusion, not directly measured ·
`[UNKNOWN]` not verifiable with current evidence.

---

## 1. Phase

Phase 3 — AC/DC/PI and Red/IR SpO2 Waveform Model.

## 2. Status

**COMPLETE** — all in-scope software tasks implemented; all 51 tests (26 Phase 2 + 25 Phase 3) PASS. `[VERIFIED-RUNTIME]`

Hardware DAC changes were intentionally **not** performed (the spec says "Stop before hardware DAC changes"); no on-wire measurement was taken this session — see §11.

## 3. Prerequisites read

Read in this or the immediately preceding session before implementing:
- `docs/claude_phases/03_PHASE_AC_DC_PI_AND_RED_IR_MODEL.md` (Phase 3 spec). `[VERIFIED-CODE]`
- `docs/phase_reports/PHASE_02_COMPLETION_REPORT.md` (Phase 2 handoff — Phase 2 primitives to preserve). `[VERIFIED-CODE]`
- Phase 1 architecture report and Phase 1 completion report (polarity §22/E9, morphology preservation §57). `[VERIFIED-CODE]`
- Source: `models/ppg_model.py`, `calibration.py`, `config.py`, `core/signal_engine.py`, `config_store.py`, `ui/frames/pathology_frame.py`, `ui/frames/calibration_frame.py`, `tests/test_calibration.py`. `[VERIFIED-CODE]`

## 4. Completed tasks

1. **AC and DC are the master parameters; PI is derived.** Added `set_ac_dc(ac_ir_mv, dc_ir_mv, dc_red_mv=None)` to `PPGModel`: PI = AC_ir/DC_ir × 100 is computed and stored. `[VERIFIED-CODE]` `[VERIFIED-RUNTIME]`
2. **Independent Red/IR DC.** `PPGParameters` now carries `dc_ir_mv`, `dc_red_mv` (mV); the model works in Volts (`dc_ir`, `dc_red`). `set_dc_levels()` sets them independently. `[VERIFIED-CODE]`
3. **Full ratio-of-ratios.** IR AC = PI/100·DC_ir; Red AC = `ac_red_from_target(R, AC_ir, DC_red, DC_ir)` = R·AC_ir·(DC_red/DC_ir). Reconstructed R = (AC_red/DC_red)/(AC_ir/DC_ir) equals the target R for **any** DC pair. `[VERIFIED-CODE]` `[VERIFIED-RUNTIME]`
4. **Pure math primitives** added to `calibration.py`: `perfusion_index_from_ac_dc`, `ratio_of_ratios`, `ac_red_from_target`, `validate_ac_dc`. `[VERIFIED-CODE]`
5. **Polarity (AC above / below DC).** `POLARITY_ABOVE_DC` (default, legacy pulse-up) / `POLARITY_BELOW_DC`; `set_polarity()`. Signal composition applies the sign to the AC term only. `[VERIFIED-CODE]`
6. **Engine wiring.** `SignalEngine.update_ac_dc`, `update_dc_levels`, `update_polarity` delegate to the model and mirror state onto `ppg_params`. `[VERIFIED-CODE]`
7. **Backward-compatible persistence.** `config_store` persists `dc_ir_mv`/`dc_red_mv`/`ac_polarity` with default-merge + validation + fallback. `[VERIFIED-CODE]` `[VERIFIED-RUNTIME]`
8. **UI amplitude label** updated to full ratio-of-ratios (uses live per-channel DC). `[VERIFIED-CODE]`
9. **Removed the fixed `PPG_AC_SCALE_PER_PI = 0.015` constant** (the old global Volts-per-PI forcing); every AC magnitude now flows from PI × DC. `[VERIFIED-CODE]` `[VERIFIED-RUNTIME]`
10. **Focused Phase 3 tests** (`tests/test_phase3_acdc.py`, 25 cases). `[VERIFIED-RUNTIME]`

## 5. Out-of-scope tasks intentionally deferred

| Deferred item | Owning phase |
|---------------|--------------|
| OPT101 acquisition (A0/A2 ADC read path) | **Phase 5** — not started. `[VERIFIED-CODE]` |
| Measured SpO2 from real receiver data | **Phase 6** — not started. `[VERIFIED-CODE]` |
| Real DAC output / MCP4725 I2C AC/DC write path changes | Deferred per spec ("stop before hardware DAC changes"). |
| GUI controls to edit AC/DC/DC-Red/polarity live | Not required by Phase 3 (model + engine + persistence API is in place). `[ENGINEERING-INFERENCE]` |
| Which MCP4725 (0x60/0x61) or ADC (A0/A2) maps to Red vs IR | Not assumed; left to a phase with physical wiring evidence. `[UNKNOWN]` |

## 6. Files modified / created / deleted

| File | Action | Why |
|------|--------|-----|
| `calibration.py` | MODIFIED (extended) | Added Phase 3 pure primitives (`perfusion_index_from_ac_dc`, `ratio_of_ratios`, `ac_red_from_target`, `validate_ac_dc`) + `DAC_FULLSCALE_MV` import. (File itself was created in Phase 2, still untracked.) |
| `models/ppg_model.py` | MODIFIED | Per-channel DC state, PI-derived AC, full ratio-of-ratios, polarity, new setters; removed `PPG_AC_SCALE_PER_PI`. |
| `core/signal_engine.py` | MODIFIED | `update_ac_dc` / `update_dc_levels` / `update_polarity` engine methods. |
| `config_store.py` | MODIFIED | Persist/validate `dc_ir_mv`, `dc_red_mv`, `ac_polarity` (backward compatible). |
| `ui/frames/pathology_frame.py` | MODIFIED | Amplitude label uses full ratio-of-ratios with live per-channel DC. |
| `tests/test_phase3_acdc.py` | CREATED | 25 stdlib `unittest` cases for the Phase 3 scope. |
| `docs/phase_reports/PHASE_03_COMPLETION_REPORT.md` | CREATED | This report. |

**Not deleted.** No files removed. `config.py` and `ui/frames/calibration_frame.py` appear modified in `git status` but were **not** touched this session — those are Phase 2 changes. `[VERIFIED-RUNTIME]`

## 7. Behavior changes (before vs after)

| Aspect | Before (Phase 2) | After (Phase 3) |
|--------|------------------|-----------------|
| AC magnitude | `AC_ir = PI × 0.015 V` (fixed global scale `PPG_AC_SCALE_PER_PI`) | `AC_ir = PI/100 × DC_ir` (per-channel DC; PI derived from AC/DC) |
| Red AC | `AC_red = AC_ir × R` (equal-DC only) | `AC_red = R × AC_ir × (DC_red/DC_ir)` (correct for any DC) |
| DC baseline | single shared `dc_baseline = 1.5 V` | independent `dc_ir`, `dc_red`; `dc_baseline` kept as legacy alias of `dc_ir` |
| Polarity | pulse always above DC | selectable above/below DC (default above = legacy) |
| Baseline wander | scaled by single `dc_baseline` | scaled per channel by `dc_ir` / `dc_red` |
| Persistence | HR/PI/SpO2/A/B | + `dc_ir_mv`, `dc_red_mv`, `ac_polarity` |
| Clipping | clamp to `[0, 3.2 V]` | unchanged clamp; per-channel DC now feeds it |

**Backward-compat invariant preserved** `[VERIFIED-RUNTIME]`: with defaults `DC_ir = DC_red = 1.5 V`, `AC_ir = PI/100·1.5 = PI × 0.015 V` (identical to the old constant) and `AC_red = R·AC_ir·(1.5/1.5) = R·AC_ir`. `get_ac_amplitude()` returns `0.045 V` at PI = 3, exactly as before. Respiration (BW/AM/FM-RSA) and noise generation were preserved (refined only where the per-channel DC required it — wander is now per channel). AM/HR couplings multiply both channels equally, so R is preserved.

## 8. Math / config / API changes

**Formulas (calibration.py, pure):** `[VERIFIED-CODE]`
- `perfusion_index_from_ac_dc(ac, dc) = ac / dc × 100` (units cancel).
- `ratio_of_ratios(ac_red, dc_red, ac_ir, dc_ir) = (ac_red/dc_red)/(ac_ir/dc_ir)`.
- `ac_red_from_target(r, ac_ir, dc_red, dc_ir) = r × ac_ir × (dc_red/dc_ir)`.
- `validate_ac_dc(ac_mv, dc_mv, fullscale_mv=3200)` → enforces DC > 0, AC ≥ 0, DC ≤ FS, DC+AC ≤ FS (above-DC peak), DC−AC ≥ 0 (below-DC trough); returns `(ac, dc)` or raises `ValueError`.

**Constants:** removed `PPG_AC_SCALE_PER_PI = 0.015`. Added `POLARITY_ABOVE_DC = 0`, `POLARITY_BELOW_DC = 1`, `DEFAULT_DC_BASELINE_V = 1.5` in `models/ppg_model.py`; `_DEFAULT_DC_MV = 1500.0` in `config_store.py`. `[VERIFIED-CODE]`

**Units/ranges:** DC persisted/user-facing in **mV**; model internal in **Volts**. DC ∈ (0, 3200] mV. PI clamped to the existing [0.5, 20] slider range in both `set_perfusion_index` and the derived `set_ac_dc`. R clamped to `[R_CLAMP_MIN, R_CLAMP_MAX] = [0.4, 1.6]` (unchanged Phase 2 constants). DAC full-scale = `DAC_FULLSCALE_V = 3.2 V` (Phase 2 SSOT, unchanged). `ADC_VOLTAGE_REF = 3.3` unchanged (confirmed at runtime). `[VERIFIED-RUNTIME]`

**New API surface:** `[VERIFIED-CODE]`
- `PPGModel.set_ac_dc(ac_ir_mv, dc_ir_mv, dc_red_mv=None)`, `set_dc_levels(dc_ir_mv, dc_red_mv=None)`, `set_polarity(polarity)`. `set_dc_baseline(dc)` retained (now sets both channels).
- `SignalEngine.update_ac_dc(...)`, `update_dc_levels(...)`, `update_polarity(...)`.
- `config_store` keys: `dc_ir_mv`, `dc_red_mv`, `ac_polarity`.
- No MCP4725 / I2C driver calls were changed. `[VERIFIED-CODE]`

## 9. Tests added and commands executed

Added `tests/test_phase3_acdc.py` (25 cases) covering the six spec-required categories: AC/DC→PI, equal & unequal DC ratio-of-ratios, A/B changes, clipping, AC above/below DC, invalid combinations. Plus backward-compat cases.

Commands actually run this session: `[VERIFIED-RUNTIME]`
```
python3 -m unittest tests.test_phase3_acdc -v
python3 -m unittest tests.test_calibration -v
python3 -m unittest tests.test_calibration tests.test_phase3_acdc
python3 -c "import config, calibration, config_store; import models.ppg_model; import core.signal_engine"   # import chain
python3 -c "...smoke: backward-compat AC, unequal-DC R, below-DC polarity..."
python3 -c "...config_store round-trip / legacy / corrupt fallback..."
```

## 10. Actual results

| Item | Result |
|------|--------|
| `python3 -m unittest tests.test_phase3_acdc -v` | **PASS** — `Ran 25 tests ... OK`. `[VERIFIED-RUNTIME]` |
| `python3 -m unittest tests.test_calibration -v` | **PASS** — `Ran 26 tests ... OK` (no Phase 2 regression). `[VERIFIED-RUNTIME]` |
| Combined (51 tests) | **PASS** — `Ran 51 tests ... OK`. `[VERIFIED-RUNTIME]` |
| Import chain (config/calibration/config_store/model/engine) | **PASS** — `IMPORTS_OK`; `DAC_FULLSCALE_V=3.2`, `ADC_VOLTAGE_REF=3.3`. `[VERIFIED-RUNTIME]` |
| Smoke: backward-compat `get_ac_amplitude()` at PI=3, DC=1.5 | **PASS** — `0.045 V`. `[VERIFIED-RUNTIME]` |
| Smoke: unequal DC (1.5/0.9) reconstructed R vs target 0.8 | **PASS** — match (Δ < 1e-9). `[VERIFIED-RUNTIME]` |
| Smoke: below-DC polarity dips below DC_ir | **PASS**. `[VERIFIED-RUNTIME]` |
| config_store round-trip / legacy-defaults / corrupt-fallback | **PASS**. `[VERIFIED-RUNTIME]` |
| Full GUI launch (`main.py`) | **NOT RUN** — requires `customtkinter` + display; out of Phase 3 scope. |
| `pytest` | **NOT RUN** — system Python lacks it; tests are stdlib `unittest`. |

## 11. Hardware validation

**NOT RUN / BLOCKED.** No hardware was exercised this session. No MCP4725 I2C writes, no on-wire DAC voltage measurement, no OPT101 read. DAC code/clipping behavior is verified only as integer/float math in software. Physical output voltage, Red/IR-to-address mapping, and A0/A2 mapping are `[UNKNOWN]` pending physical evidence. The measured 3.2 V full-scale is a `[VERIFIED-USER]` fact the code honors but did not re-measure.

## 12. Remaining gaps and risks

- **No live GUI controls** for AC/DC/DC-Red/polarity yet; the model+engine+persistence API exists but no frame calls `update_ac_dc`/`update_dc_levels`/`update_polarity`. `[VERIFIED-CODE]`
- **Preset ↔ AC/DC interaction (documented, not a regression):** condition presets drive PI, and `_generate_dynamic_pi` clamps beat-to-beat PI to `[pi_min×0.8, pi_max×1.2]`. So a high PI set via `set_ac_dc`/`set_perfusion_index` can be pulled toward the active condition's range on the next beat. This is the pre-existing PI ownership behavior, preserved deliberately. `[VERIFIED-CODE]` `[ENGINEERING-INFERENCE]`
- **Below-DC + PI path never clips at 0** because AC = PI/100·DC < DC for PI < 100 (so DC−AC > 0). Upper clipping at 3.2 V is exercised and bounded. `[VERIFIED-RUNTIME]` `[ENGINEERING-INFERENCE]`
- **DAC write path unchanged:** the DAC still receives `dc_baseline`-referenced values through the existing engine→`dac_manager` path; independent Red DC is represented in the generated `signal_red` but on-wire behavior is unverified. `[UNKNOWN]`

## 13. Unknowns / assumptions

- **Assumption (engineering):** keeping PI as the internal magnitude driver (with AC/DC as the master input that derives PI) best preserves condition presets and beat-to-beat variability while achieving ratio-of-ratios correctness. `[ENGINEERING-INFERENCE]`
- **Assumption (polarity default):** default = ABOVE-DC to preserve existing pulse-up morphology (Phase 3 §57), even though Phase 1 §22 notes AECG100 can drive below-DC. BELOW-DC is selectable. `[ENGINEERING-INFERENCE]` from `[VERIFIED-USER]` Phase 1 notes.
- **Unknown:** physical DAC output voltage, MCP4725 address↔channel mapping, OPT101/ADC channel mapping. `[UNKNOWN]`
- **Verified vs inferred:** all formula/round-trip/clip claims tagged `[VERIFIED-RUNTIME]` were executed this session; morphology-preservation is `[ENGINEERING-INFERENCE]` backed by the backward-compat invariant test, not a visual/scope comparison.

## 14. `git diff --stat` / `git status --short`

`git diff --stat` (tracked Phase 3 source; `calibration.py` and `tests/` are untracked so not shown by diff): `[VERIFIED-RUNTIME]`
```
 config_store.py              |  71 ++++++++++++
 core/signal_engine.py        |  47 ++++++--
 models/ppg_model.py          | 252 ++++++++++++++++++++++++++++++++++++-------
 ui/frames/pathology_frame.py |  14 ++-
 4 files changed, 332 insertions(+), 52 deletions(-)
```

`git status --short` (excluding `__pycache__`/`.pyc`): `[VERIFIED-RUNTIME]`
```
 M CLAUDE.md                       (pre-existing; not Phase 3)
 m MedicalSimulator                (submodule; pre-existing)
 M config.py                       (Phase 2; not touched in Phase 3)
 M config_store.py                 (Phase 3)
 M core/signal_engine.py           (Phase 3)
 M models/ppg_model.py             (Phase 3)
 M ui/frames/calibration_frame.py  (Phase 2; not touched in Phase 3)
 M ui/frames/pathology_frame.py    (Phase 3)
?? calibration.py                  (created Phase 2, extended Phase 3; untracked)
?? docs/architecture/  docs/claude_phases/  docs/phase_reports/  tests/
```

## 15. Acceptance criteria checklist

- [x] AC and DC are master adjustable parameters (`set_ac_dc`, `set_dc_levels`). `[VERIFIED-CODE]`
- [x] PI is calculated from AC/DC (`perfusion_index_from_ac_dc`; derived in `set_ac_dc`). `[VERIFIED-RUNTIME]`
- [x] Independent Red/IR AC and DC. `[VERIFIED-CODE]`
- [x] Full ratio-of-ratios `R = (AC_red/DC_red)/(AC_ir/DC_ir)`. `[VERIFIED-RUNTIME]`
- [x] Target Red amplitude `AC_red = R·AC_ir·(DC_red/DC_ir)`; simplifies at equal DC. `[VERIFIED-RUNTIME]`
- [x] AC above / below DC behavior added (Phase 1-approved). `[VERIFIED-RUNTIME]`
- [x] Clipping bounded by the real 3.2 V DAC range. `[VERIFIED-RUNTIME]`
- [x] Respiration/noise preserved (per-channel wander refinement only). `[VERIFIED-CODE]`
- [x] Backward compatibility preserved at default equal DC. `[VERIFIED-RUNTIME]`
- [x] Tests for AC/DC→PI, equal & unequal DC, A/B, clipping, above/below DC, invalid combos. `[VERIFIED-RUNTIME]`
- [x] No hardcoded 3.3 V DAC scaling or hardcoded 110/25 SpO2 logic reintroduced. `[VERIFIED-CODE]`
- [x] Phase 5 (OPT101) and Phase 6 (measured SpO2) NOT started. `[VERIFIED-CODE]`
- [x] Stopped before hardware DAC changes; no fabricated hardware results. `[VERIFIED-CODE]`

## 16. Next-phase readiness

**Ready:** The synthesis model now emits two independent Red/IR streams with correct AC/DC/PI/ratio-of-ratios and a validated AC/DC envelope, plus persistence. Phase 4 (or a later UI phase) can add controls that call the existing engine methods without touching the model math.

**Blocks:** Any phase claiming physical DAC/optical behavior is blocked until on-wire measurement and Red/IR↔address / ADC-channel mapping are confirmed (`[UNKNOWN]`). OPT101 acquisition (Phase 5) and measured SpO2 (Phase 6) remain unstarted by design.

## 17. Do-not-redo handoff (for the next phase)

Preserve — do **not** re-implement — these now-stable pieces:
- **AC/DC/PI math lives in `calibration.py`:** `perfusion_index_from_ac_dc`, `ratio_of_ratios`, `ac_red_from_target`, `validate_ac_dc`. Reuse them; do not inline new AC/DC formulas.
- **Master/derived contract:** AC & DC are master; PI is derived (`PI = AC/DC×100`). IR AC = `PI/100·DC_ir`; Red AC via `ac_red_from_target`. Do not reintroduce a fixed Volts-per-PI constant.
- **Per-channel DC:** `dc_ir`/`dc_red` (Volts) + `dc_ir_mv`/`dc_red_mv` (mV on `PPGParameters`). `dc_baseline` is a legacy alias of `dc_ir` — keep it in sync, don't repurpose it.
- **Polarity:** `POLARITY_ABOVE_DC` (default) / `POLARITY_BELOW_DC`; sign applies to the AC term only.
- **Engine API:** `update_ac_dc` / `update_dc_levels` / `update_polarity`. Wire UI/BLE to these, not directly to the model.
- **Persistence contract:** keys `dc_ir_mv`, `dc_red_mv`, `ac_polarity` merge with defaults and validate on load (fallback to 1500/1500/above-DC). Extend the same dict-merge pattern for new keys; don't break legacy files.
- **Phase 2 primitives remain the SSOT:** `dac_voltage_to_code`, `spo2_from_r`, `r_target_from_spo2`, `SpO2Calibration`, `DAC_FULLSCALE_V = 3.2`, persistent `spo2_coeff_a/b`. `ADC_VOLTAGE_REF = 3.3` unchanged.

---

**STOP.** Phase 3 is complete. Phase 4 not started — awaiting explicit instruction.
