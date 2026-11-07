# 02 — Datasheet and Hardware-Evidence Audit

**Scope:** Read every locally available datasheet, schematic image, and reference PDF in
`docs/ds_linhkien/` and `docs/whale_device/`, extract verified electrical/mechanical parameters
component-by-component, and compare that evidence against the claims already recorded in
`01_CURRENT_SYSTEM_AUDIT.md`. This document does not modify any implementation, test,
configuration, architecture, phase, historical-report, schematic, or PCB file. No resistor,
capacitor, or LED-driver values are calculated here, and no new schematic/PCB artifacts are
created. Ground-truth facts F-01…F-12 and negative facts N-01…N-05 are taken as authoritative
from `00_BASE_CONTEXT.md` and are not re-derived here.

**Evidence labels used (only these nine are permitted):**
`[VERIFIED-USER]`, `[VERIFIED-DATASHEET]`, `[VERIFIED-SCHEMATIC]`, `[VERIFIED-CODE]`,
`[CALCULATED]`, `[ENGINEERING-INFERENCE]`, `[RECOMMENDED STARTING VALUE]`,
`[MEASUREMENT-REQUIRED]`, `[UNKNOWN]`. The non-approved label `[VERIFIED-PDF]` (found at
`calibration.py:13` per `01_CURRENT_SYSTEM_AUDIT.md` §5.10/C-14) is never used in this document.

---

## 1. Source documents inspected

| File | Manufacturer / Title | Pages | Role in this audit |
|---|---|---|---|
| `docs/ds_linhkien/opt101.pdf` | TI OPT101, SBBS002B, Rev B (Jan 1994 – rev. June 2015) | 31 | Photodiode + transimpedance amp IC datasheet |
| `docs/ds_linhkien/lm358ba.pdf` | TI LM158/LM258/LM2904/LM358 family, SLOS068AB (rev. Oct 2024) | 68 | Op-amp family datasheet (multi-variant) |
| `docs/ds_linhkien/2SC1815L-GR.PDF` | TOSHIBA 2SC1815, dated 2007-11-01 | 4 | NPN transistor datasheet (all hFE bins) |
| `docs/ds_linhkien/red_led_3.3mm_datasheet.pdf` | China Young Sun LED Technology, model YSL-R341R3D-D2 | 4 | Red LED datasheet |
| `docs/ds_linhkien/IR_led_3.3mm_datasheet.pdf` | Everlight Electronics, SIR234, DIR-0000974 | 9 | IR LED datasheet |
| `docs/ds_linhkien/MCP4725_schematic.png` | Adafruit MCP4725 breakout, rev C (image, no text datasheet) | 1 image | Module-level schematic only — **no local MCP4725 IC datasheet exists** |
| `docs/ds_linhkien/grove_base_hat.pdf` | Seeed Studio, Part Number 103030275 | 5 | Grove Base HAT (ADC front-end for Raspberry Pi) |
| `docs/ds_linhkien/raspberry-pi-4-datasheet.pdf` | Raspberry Pi (Trading) Ltd., Release 1.1, March 2024 | 13 | Host SBC electrical/GPIO reference |
| `docs/whale_device/whale_device.pdf` | WhaleTeq, "AECG100-datasheet…v2.1-20240417" | 4 | WhaleTeq AECG100 brochure — confirmed **not** part of this project's physical hardware (N-01); reference-only, historical source of default SpO2 coefficients A=110/B=25 |
| `docs/whale_device/user_manual.pdf` | WhaleTeq AECG100 user manual, "um_mix_en_v.1.9.0_251208" | 93 | Metadata-level only; confirmed same non-physical reference role as above, no further content read (see §1.1) |
| `docs/whale_device/version_sdk_app_whale.pdf` | WhaleTeq SDK/app version doc | 6 | Metadata-level only; same reference-only role |

### 1.1 Why `user_manual.pdf` and `version_sdk_app_whale.pdf` were not read cover-to-cover

`whale_device.pdf` (the 4-page product brochure) was read in full and already establishes,
unambiguously, that the WhaleTeq AECG100 is a **separate, self-contained commercial test
instrument** with its own built-in photodiode/LED modules (PPG-1R-525, PPG-2TF-660, PPG-2R-880,
PPG-2R-940) in a single housing — structurally and physically unrelated to this project's
two-isolated-dark-chamber design. This directly confirms N-01 (no WhaleTeq fixture in this
project). The 93-page user manual and 6-page SDK version document describe operating procedures
and software interfaces for that separate commercial instrument; per `00_BASE_CONTEXT.md` §5,
WhaleTeq documents are "functional references only," not part of this project's physical
architecture. No parameter in those two files can change the conclusion already established by
the brochure, so exhaustive line-by-line reading of them was not performed. This is recorded
explicitly as a scope decision, not an omission: **I am not sure based on the currently available
evidence** whether those two documents contain any additional detail relevant to the SpO2
coefficient provenance beyond what `whale_device.pdf` and the existing code comments already
state; if that provenance detail becomes safety- or accuracy-critical, those two files should be
read in full in a future prompt.

---

## 2. Evidence tables

### 2.1 OPT101 (Photodiode + Transimpedance Amplifier)

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| OPT101 | opt101.pdf | p.1, §1 Features | Supply range | 2.7 V to 36 V | 3.28 V (F-08) is within the supported supply range | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.3, §5 Pin Configuration and Functions | Pinout (8-pin DIP/SOP) | Pin1=Vs, Pin2=−In, Pin3=−V, Pin4=1MΩ Feedback, Pin5=Output, Pin6=NC, Pin7=NC, Pin8=Common | Defines which physical pins must be traced on the actual module to determine wiring | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.3, §5, Pin 4 description | Internal 1-MΩ feedback pin description | "Connection to internal feedback network. Typically connect to Output, pin 5." | Confirms the 1-MΩ feedback resistor **exists inside the IC**, but pin 4 must be physically tied to pin 5 for it to be active — it is not automatically active by virtue of the part being an OPT101 | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.1, Block Diagram | Internal feedback network topology | 1 MΩ resistor in parallel with 8 pF, from pin 4/5 node to the photodiode/−In node; 7.5 mV internal offset source shown at photodiode | Confirms internal RC feedback network topology as drawn by TI | `[VERIFIED-DATASHEET]` |
| OPT101 (this project's module) | — no local schematic — | — | Whether pin 4 is actually tied to pin 5 in the physical module used in this project | Not established | **Cannot claim the module uses the internal 1-MΩ feedback** — no schematic or photograph of the OPT101 wiring for this project exists in `docs/ds_linhkien/` or elsewhere in the repo | `[MEASUREMENT-REQUIRED]` |
| OPT101 | opt101.pdf | p.5, §6.5 Electrical Characteristics, "DARK ERRORS, RTO" | Dark output offset voltage | Min 5 mV, Typ 7.5 mV, Max 10 mV | Sets the expected non-zero baseline (dark) output level for both IR and Red channels absent any light | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.5, §6.5, "FREQUENCY RESPONSE" | Bandwidth | 14 kHz (at V_OUT=10 Vpp, R_F=1MΩ internal) | Upper bound on usable PPG signal bandwidth for this front end when internal 1-MΩ feedback is used; far above physiological PPG bandwidth (~0.5–10 Hz), so bandwidth is not the limiting factor here | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.5, §6.5, "OUTPUT" | Capacitive load, stable operation | 10 nF | Any external capacitive loading on the OPT101 output (cabling, filter caps) must stay at/below 10 nF for stability unless external compensation is added | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.5, §6.5, "POWER SUPPLY" | Quiescent current | Dark: 120 µA typ; R_L=∞, V_OUT=10V: 220 µA typ | Low quiescent draw; not a significant load on the 3.28 V rail (F-08) | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.5, §6.5, "OUTPUT" | Voltage output, high (rail-referenced max) | (V_S) − 1.3 V (min) to (V_S) − 1.15 V (max) | At V_S = 3.28 V (F-08): output can swing to approximately 1.98 V–2.13 V max before clipping against the internal high-output limit | `[CALCULATED]` |
| OPT101 | opt101.pdf | p.6, §6.6 Electrical Characteristics: Photodiode | Photodiode current responsivity | 0.45 A/W | Test condition is λ = 650 nm only (visible red), **not** at this project's actual LED wavelengths (620–625 nm Red per LED datasheet, 875 nm IR per LED datasheet) | `[VERIFIED-DATASHEET]` |
| OPT101 | opt101.pdf | p.1, Spectral Responsivity graph / p.7 Fig.1 Normalized Spectral Responsivity | Responsivity vs wavelength (graphical only) | Peak visually near 800–900 nm; curve shows response is still rising/near-peak in the 620–900 nm span | No tabulated numeric responsivity value exists at 620–625 nm or at 875 nm — only a graphical curve. Any responsivity figure used at those specific wavelengths for signal-budget calculation is a graphical read, not a tabulated spec | `[ENGINEERING-INFERENCE]` |
| OPT101 (responsivity at 620–625 nm and 875 nm, numeric) | — | — | Exact A/W or V/µW at these two specific wavelengths | Not tabulated anywhere in this datasheet | **I am not sure based on the currently available evidence** what the exact responsivity is at 620–625 nm or 875 nm; only the 650 nm test-condition value (0.45 A/W) and the graphical curve exist | `[UNKNOWN]` |
| OPT101 | opt101.pdf | p.4, §6.1 Absolute Maximum Ratings | Supply voltage, output short-circuit, temperature limits | 0–36 V supply; continuous output short-circuit tolerance; −25…85 °C operating/junction/storage | Confirms 3.28 V and 5.00 V rails referenced elsewhere in this project (F-08, F-11) are both far inside absolute maximum ratings for this specific IC (only applies to the OPT101 itself, at 3.28 V) | `[VERIFIED-DATASHEET]` |
| OPT101 layout guidance | opt101.pdf | §11 Layout (p.23, per ToC; not reproduced verbatim here) | Recommended bypass cap, trace-length and shielding guidance for the photodiode node | Datasheet gives generic layout guidance (bypass 0.01–0.1 µF Vs-to-(−V), keep photodiode node traces short/guarded) | Generic TI guidance; whether this project's dark-chamber module follows it is unverified | `[VERIFIED-DATASHEET]` (guidance exists) / `[MEASUREMENT-REQUIRED]` (whether followed) |
| OPT101 application circuits | opt101.pdf | §9 Application and Implementation (p.16 per ToC) | TI reference application circuits | Generic TI application examples (single photodiode, single supply) | These are TI's generic example circuits and are **not evidence about this project's own isolated dual-chamber design** (per N-02/N-03) | `[VERIFIED-DATASHEET]` (as TI's own generic examples only) |

### 2.2 LM358 family (op-amp used in the LED-driver / signal-conditioning stage)

The local file `lm358ba.pdf` (TI document SLOS068AB, 68 pages total including the Package Option
Addendum and mechanical package drawings) is a **multi-variant family datasheet** covering
LM158/LM158A/LM258/LM258A/LM2904/LM2904B/LM2904BA/LM2904V/LM358/LM358A/LM358B/LM358BA together in
one document, despite the local filename `lm358ba.pdf` suggesting a single variant. All figures
below are explicitly tied to the variant/table they came from.

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| LM358 family | lm358ba.pdf | §6 Pin Configuration and Functions, Fig. 4-1 (8-pin) | Pinout | Pin1=OUT1, Pin2=IN1−, Pin3=IN1+, Pin4=V−, Pin5=IN2+, Pin6=IN2−, Pin7=OUT2, Pin8=V+ | Standard dual op-amp pinout — needed to trace which op-amp channel drives which stage in this project | `[VERIFIED-DATASHEET]` |
| LM358 family | lm358ba.pdf | Family Comparison table (§5/§6 area) | Supply voltage range by variant | 3–36 V (B/BA); 3–30 V (LM358/LM358A/LM158/LM258A); 3–26 V (LM2904) | 5.00 V (F-11) is within range for **every** variant in the family, so this parameter alone cannot identify which variant is installed | `[VERIFIED-DATASHEET]` |
| LM358 family | lm358ba.pdf | Family Comparison table | Input offset voltage (VOS) | ±3.0 mV typ max (B); ±2.5 mV typ max (BA); ±7 mV (LM358); ±3 mV (LM358A) | Offset error budget differs by up to ~4.5 mV depending on exact variant installed — directly affects any DC-precision calculation in the signal chain | `[VERIFIED-DATASHEET]` |
| LM358 family | lm358ba.pdf | Family Comparison table | Input bias current (IB) typ/max | 10/35 nA (B/BA); 20/250 nA (LM358); 15/100 nA (LM358A) | Bias-current-induced offset across any feedback/gain resistor will vary by up to ~7x depending on variant | `[VERIFIED-DATASHEET]` |
| LM358 family | lm358ba.pdf | Family Comparison table | Gain-bandwidth product (GBW) | 1.2 MHz (B/BA); 0.7 MHz (others) | Sets upper usable closed-loop bandwidth for any amplifier stage built with this part; PPG signal band (≪1 kHz) is far below either value, so GBW is not the limiting factor for this application | `[VERIFIED-DATASHEET]` |
| LM358B/BA @ VS=5–36 V | lm358ba.pdf | §5.5 Electrical Characteristics (VS = 5 V to 36 V) | Common-mode input voltage range | (V−) to (V+) − 1.5 V typ; (V+) − 2 V over full temperature range | At V+ = 5.00 V (F-11): valid CM range is roughly 0 V to ~3.0–3.5 V typ (worse over temperature, ~3.0 V). **This directly bounds how high any input signal can swing before CMR is violated** | `[CALCULATED]` |
| LM358B/BA @ VS=5–36 V | lm358ba.pdf | §5.5 | Output swing, positive rail dropout | 1.35–1.42 V typ @ 50 µA load, up to 1.5–1.61 V @ 5 mA load | At V+ = 5.00 V: output cannot swing above roughly 3.4–3.65 V (light load) or 3.4 V (heavier load) — **confirms NOT rail-to-rail output** even for the "improved" B/BA variants | `[VERIFIED-DATASHEET]` |
| LM358B/BA @ VS=5–36 V | lm358ba.pdf | §5.5 | Output swing, negative rail | 100–150 mV @ 50 µA down to 5–20 mV @ heavier load | Output cannot swing fully to 0 V/ground either — small but nonzero floor | `[VERIFIED-DATASHEET]` |
| LM358/LM358A @ VS=5V | lm358ba.pdf | §5.7 Electrical Characteristics (VS = 5 V) | Output swing (positive), slew rate | (V+) − 1.5 V typ (R_L≥10kΩ); SR = 0.3 V/µs | If the installed part is the older (non-B/BA) LM358/LM358A variant, dropout is larger (1.5 V vs 1.35–1.42 V) and slew rate is roughly half that of B/BA (0.3 vs 0.5 V/µs) | `[VERIFIED-DATASHEET]` |
| LM358 family | lm358ba.pdf | §7.3 Feature Description (explicit prose) | Common-mode range statement | "The valid common-mode range is from device ground to VS − 1.5 V (VS − 2 V across temperature)... If both inputs exceed the valid range, the output phase is undefined." | Direct, explicit textual confirmation that this part is **not** rail-to-rail on the input, and that violating CMR produces undefined (not just clipped) output behavior — a real failure mode to check for in this project's 5.00 V stage | `[VERIFIED-DATASHEET]` |
| LM358 family | lm358ba.pdf | §8 Application and Implementation | Generic inverting-amp example, 0.1 µF supply bypass recommendation | TI reference application circuit | Generic TI example only — not evidence of this project's actual LED-driver/amplifier topology, which has no local schematic (per `00_BASE_CONTEXT.md` §7 open item) | `[VERIFIED-DATASHEET]` (as TI's own generic example only) |
| LM358 family | lm358ba.pdf | Package Option Addendum (end of document) | Physical top-mark by ordering variant, e.g. "LM358BIDR" marks "LM358B" | Device marking table | Confirms that variant identity IS discoverable, but only by reading the physical top-side marking on the installed chip — the datasheet itself cannot tell us which one is installed | `[VERIFIED-DATASHEET]` (marking scheme) / `[MEASUREMENT-REQUIRED]` (which chip is actually installed) |
| LM358 (exact variant in this project) | — | — | Which of LM358/LM358A/LM358B/LM358BA/LM2904-family is physically installed | Not established | **Do not assume rail-to-rail; do not assume the B/BA-class specs apply.** Physical chip top-mark must be read and matched against the Package Option Addendum table before any CMRR/offset/dropout number is used in a calculation | `[MEASUREMENT-REQUIRED]` |

### 2.3 2SC1815 (NPN transistor, likely LED driver / switch)

The local file is genuinely titled `2SC1815L-GR.PDF`, but its content is the standard **TOSHIBA
generic 2SC1815 datasheet covering all four hFE bins (O/Y/GR/BL) together** — the "GR" in the
filename does not restrict the datasheet content to the GR bin only.

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| 2SC1815 | 2SC1815L-GR.PDF | p.1, header | Exact manufacturer / part / package | TOSHIBA, 2SC1815, TO-92 (JEDEC TO-92 / JEITA SC-43 / TOSHIBA 2-5F1B) | Confirms genuine TOSHIBA part, not a generic clone datasheet, and the physical package/pin spacing | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, title block | Polarity | NPN, silicon epitaxial (PCT process) | Confirms polarity assumption for driver-stage analysis | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, Absolute Maximum Ratings | VCEO | 50 V | Far above any rail in this project (3.28 V / 5.00 V), so VCEO is not a constraint here | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, Absolute Maximum Ratings | IC max | 150 mA | Upper bound on any LED drive current this transistor stage could deliver | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, Absolute Maximum Ratings | PC (collector power dissipation) | 400 mW | Upper thermal bound at Ta=25 °C; must be derated per the PC–Ta graph on p.3 for higher ambient temperatures | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, Electrical Characteristics | hFE(1), Note (all bins combined) | Min 70, Max 700 | Confirms extremely wide gain spread if bin is unknown — a factor-of-10 range | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, note beneath Electrical Characteristics table | hFE classification by bin | O: 70–140; Y: 120–240; GR: 200–400; BL: 350–700 | The filename suggests "GR" bin (200–400), but **the datasheet itself does not prove which bin is physically installed** — bin is normally marked on the transistor body, not derivable from this generic datasheet alone | `[VERIFIED-DATASHEET]` (bin ranges) / `[MEASUREMENT-REQUIRED]` (which bin is installed) |
| 2SC1815 (minimum applicable hFE if GR assumed) | 2SC1815L-GR.PDF | p.1, hFE note | GR-bin minimum hFE | 200 | **Do not use this number unless the physical part is confirmed GR-marked** — if the filename is wrong or a different bin was substituted at assembly, the true minimum could be as low as 70 (O bin) | `[MEASUREMENT-REQUIRED]` (bin confirmation) → `[VERIFIED-DATASHEET]` (value, conditional on bin confirmation) |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, Electrical Characteristics | VCE(sat) | Typ 0.1 V, Max 0.25 V @ IC=100mA, IB=10mA | Needed for any saturation-region driver calculation (not performed in this document) | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, Electrical Characteristics | VBE(sat) | Max 1.0 V @ IC=100mA, IB=10mA | Needed for base-drive calculation (not performed in this document) | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, Electrical Characteristics | fT (transition frequency) | Min 80 MHz @ VCE=10V, IC=1mA | Far above any PPG-relevant frequency; not a constraint for this application | `[VERIFIED-DATASHEET]` |
| 2SC1815 | 2SC1815L-GR.PDF | p.1, mechanical drawing | TO-92 pinout | Pin1=Emitter, Pin2=Collector, Pin3=Base (viewed per datasheet orientation drawing) | **This is the datasheet's own pinout only** — "do not assume every transistor marked C1815 has the same pinout," since third-party/clone parts have historically shipped with reordered EBC pinouts; the physically installed part's pinout must be independently confirmed against this exact orientation drawing | `[VERIFIED-DATASHEET]` (this datasheet's pinout) / `[MEASUREMENT-REQUIRED]` (confirm against installed part) |

### 2.4 Red LED (YSL-R341R3D-D2)

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, header | Exact manufacturer / model | China Young Sun LED Technology Co., Ltd., Model YSL-R341R3D-D2 | Confirms exact part identity for this project's Red channel LED | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, Absolute Maximum Ratings | Forward current (IF) | 20 mA | Upper continuous-current bound for the Red LED drive stage | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, Absolute Maximum Ratings | Peak forward current (IFP) | 30 mA | Upper pulsed-current bound (no pulse-width/duty condition stated in this table) | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, Absolute Maximum Ratings | Reverse voltage (VR) | 5 V | Constrains any reverse-bias condition (e.g. during multiplexed drive, if applicable) | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, Absolute Maximum Ratings | Power dissipation (PD) | 105 mW | Thermal bound on drive stage design | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, second table (Electrical/Optical, IF=20mA) | Forward voltage (VF) | Min 1.8 V, Max 2.2 V | Needed for driver headroom calculation (not performed here) | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, second table | Dominant wavelength (Δλ) | 620–625 nm | This is the actual optical wavelength reaching the Red-channel OPT101 (per F-06) — confirms the OPT101 responsivity gap noted in §2.1 is real, since no tabulated OPT101 responsivity exists at exactly this band | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, second table | Luminous intensity (Iv) | 150–200 mcd @ IF=20mA | Relevant to expected optical power budget in the dark chamber (not calculated here) | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.1, second table | 50% viewing angle | 40–60° | Relevant to optical coupling geometry inside the isolated dark chamber (per F-06/N-03) | `[VERIFIED-DATASHEET]` |
| Red LED | red_led_3.3mm_datasheet.pdf | p.2, mechanical dimensions drawing | Package | 3 mm round, T-1 style, leads per drawing | Confirms physical package for chamber-mount fit | `[VERIFIED-DATASHEET]` |
| Red LED polarity/pinout | red_led_3.3mm_datasheet.pdf | (all 4 pages checked) | Explicit cathode/anode lead diagram | **Not present anywhere in this datasheet** | Unlike the IR LED datasheet (§2.5), this Red LED datasheet contains no polarity diagram at all — polarity must be determined by the physical lead-length/flat-edge convention on the installed part itself, not from this document | `[UNKNOWN]` (in-document) / `[MEASUREMENT-REQUIRED]` (on installed part) |

### 2.5 IR LED (Everlight SIR234)

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| IR LED | IR_led_3.3mm_datasheet.pdf | p.1, title/header | Exact manufacturer / model | Everlight Electronics Co., Ltd., SIR234 (3mm Infrared LED, T-1) | Confirms exact part identity for this project's IR channel LED | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.2, Device Selection Guide | Chip material / lens color | GaAlAs chip, Blue lens | Material system relevant to spectral output and to optical isolation from the Red channel (per N-05) | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.2, Absolute Maximum Ratings | Continuous forward current (IF) | 100 mA | Upper continuous-current bound, five times higher than the Red LED's 20 mA rating — asymmetric drive-current headroom between the two channels | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.2, Absolute Maximum Ratings | Peak forward current (IFP) | 1.0 A (pulse width ≤100µs, duty ≤1%) | Confirms a defined pulse condition (unlike the Red LED table, which gives no pulse condition for its 30 mA peak rating) | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.2, Absolute Maximum Ratings | Reverse voltage (VR) | 5 V | Same as Red LED | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.2, Absolute Maximum Ratings | Power dissipation (Pd) | 150 mW | 43% higher thermal budget than the Red LED (105 mW) | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.3, Electro-Optical Characteristics | Radiant intensity (Ie) | Min 5.6, Typ 9.0 mW/sr @ IF=20mA | Needed for optical power budget (not calculated here) | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.3, Electro-Optical Characteristics | Peak wavelength (λp) | 875 nm typ | This is the actual optical wavelength reaching the IR-channel OPT101 (per F-05) — same responsivity-gap caveat as §2.1 applies | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.3, Electro-Optical Characteristics | Spectral bandwidth (Δλ) | 45 nm typ | Optical linewidth around the 875 nm peak | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.3, Electro-Optical Characteristics | Forward voltage (VF) | Typ 1.30 V, Max 1.65 V @ IF=20mA | Needed for driver headroom calculation (not performed here); notably lower than the Red LED's 1.8–2.2 V VF | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.3, Electro-Optical Characteristics | Viewing angle (2θ1/2) | 30° typ | Narrower than the Red LED's 40–60° — different optical coupling geometry between the two isolated chambers (F-05 vs F-06) | `[VERIFIED-DATASHEET]` |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.3, Rank/Bin table | Radiant intensity bins (L/M/N/P) | L:5.60–8.90; M:7.80–12.50; N:11.0–17.6; P:15.0–24.0 mW/sr | Same bin-uncertainty caveat as the 2SC1815 (§2.3) — actual installed part's bin is not confirmed by this generic datasheet | `[VERIFIED-DATASHEET]` (bin ranges) / `[MEASUREMENT-REQUIRED]` (which bin is installed) |
| IR LED | IR_led_3.3mm_datasheet.pdf | p.5, Package Dimension | Polarity / pinout | Pin①=Cathode, Pin②=Anode (explicit diode-symbol diagram) | Explicit, unambiguous polarity marking — stronger evidence than the Red LED, which has no polarity diagram at all | `[VERIFIED-DATASHEET]` |

### 2.6 MCP4725 (DAC IC + module)

**No local IC-level MCP4725 datasheet exists in this repository.** The only local evidence is a
single breakout-module schematic image (`MCP4725_schematic.png`), an Adafruit "MCP4725 rev C"
board. Because there is no manufacturer (Microchip) IC datasheet on disk, every IC-level electrical
parameter below is `[UNKNOWN]` at the datasheet-evidence level, even though F-09/F-10 establish the
supply and full-scale voltage as user-verified facts from direct measurement/configuration, not
from a datasheet.

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| MCP4725 module | MCP4725_schematic.png | (single image, no page/section structure) | Main IC marking on the schematic | "MCP4725A1T-E/CH" annotation present | Confirms the A1 address variant is used on this specific breakout, consistent with F-03/F-04's two distinct I2C addresses (0x60=IR, 0x61=Red) being obtained from the A0 address pin, not from two different IC part numbers | `[VERIFIED-SCHEMATIC]` |
| MCP4725 module | MCP4725_schematic.png | (image) | Bypass capacitor(s) near VDD | Present in schematic (values not legible/specified in the image beyond presence) | Confirms basic decoupling practice was followed on the module, but exact capacitance value is not extractable from this image with confidence | `[VERIFIED-SCHEMATIC]` (presence only) |
| MCP4725 module | MCP4725_schematic.png | (image) | Power/status LED | Present ("ON" LED near supply input) | Minor additional load on the 3.28 V rail (F-09); not quantified | `[VERIFIED-SCHEMATIC]` (presence only) |
| MCP4725 module | MCP4725_schematic.png | (image) | I2C pull-up resistors | Present near SCL/SDA/A0 pins on the module | **This means the module itself already provides I2C pull-ups.** If the Grove Base HAT or Raspberry Pi I2C bus also has its own pull-ups, and two MCP4725 modules plus the Grove Base HAT ADC are all on the same bus (per F-03/F-04/F-05/F-06), the effective parallel pull-up resistance could be lower than intended by any single design — this is a real bus-loading question for a shared I2C bus with multiple devices, not addressed anywhere in the available documents | `[VERIFIED-SCHEMATIC]` (presence) / `[ENGINEERING-INFERENCE]` (multi-device parallel pull-up loading risk) |
| MCP4725 module | MCP4725_schematic.png | (image) | Address configuration | A0 pin routed to a pad/jumper area for address selection (consistent with A1-variant addressing) | Consistent with F-03/F-04 (0x60 vs 0x61 differ only in the A0-pin-derived LSB of the 7-bit address) | `[VERIFIED-SCHEMATIC]` |
| MCP4725 IC | — no local datasheet — | — | Resolution (bits), INL/DNL, settling time, output slew rate, internal reference behavior, power-on-reset default output, EEPROM behavior | Not available locally | These are standard MCP4725 characteristics from the Microchip datasheet, but **that datasheet is not present in this repository** and must not be reasoned from memory per the user's explicit instruction. | `[UNKNOWN]` |
| MCP4725 (full-scale voltage) | — | — | Whether full-scale output truly equals VDD (3.28 V per F-10) with no internal reference offset/gain error | Not established from a local IC datasheet | F-10 is `[VERIFIED-USER]` (direct user assertion), which is a stronger and independent source of truth than a datasheet would be — but it means the 3.2 V figure hard-coded in `config.py:107-115` (`DAC_FULLSCALE_V = 3.2`, per `01_CURRENT_SYSTEM_AUDIT.md` §5.2/C-01) cannot be reconciled against this local evidence set either, since no IC datasheet exists to check gain error against | `[VERIFIED-USER]` (F-10) vs `[VERIFIED-CODE]` (config.py value) — **contradiction, see §3** |

### 2.7 Grove Base HAT (ADC front end)

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| Grove Base HAT | grove_base_hat.pdf | p.2, Overview / Product Details | ADC resolution and channel count | "12-bit 8 channel ADC" (explicit prose) | Confirms 12-bit resolution (4096 codes) across up to 8 analog channels — directly relevant to any LSB/quantization calculation for the A0 (IR) and A2 (Red) channels used per F-05/F-06 | `[VERIFIED-DATASHEET]` |
| Grove Base HAT | grove_base_hat.pdf | p.3, Features bullet list | ADC resolution (restated) | "12-bit ADC" | Corroborates the p.2 prose statement | `[VERIFIED-DATASHEET]` |
| Grove Base HAT | grove_base_hat.pdf | p.3, "build-in MCU STM32" (Features bullet) vs. same page, boxed Note | MCU variant — **explicit internal contradiction inside this one document** | Features bullet says "build-in MCU STM32"; the boxed Note on the same page states: "Because ST32 series chips are out of stock globally... We have no choice but to switch to the MM32 chip. The specific replacement models are as follows: STM32F030F4P6TR is replaced by MM32F031F6P6... Moreover, the IIC address of MM32 is 0x08, while the STM32 is 0x04." | This single document, under the same Part Number 103030275, describes **two different physical hardware revisions with two different I2C addresses.** The Features-bullet MCU claim ("STM32") is stale relative to the boxed Note's disclosure of the MM32 substitution — the datasheet itself does not resolve which revision ships today, and by extension cannot resolve which revision is physically in this project | `[VERIFIED-DATASHEET]` (both statements exist in the document, and they conflict with each other) |
| Grove Base HAT | grove_base_hat.pdf | p.4, Technical Details table | MCU field (as printed) | "SMT32" (sic — likely a typo for STM32 in this vendor-supplied table) | Third, differently-worded MCU claim in the same document, reinforcing that the document's own internal MCU/version bookkeeping is inconsistent and should not be trusted as a proxy for which chip/address is actually installed | `[VERIFIED-DATASHEET]` (as printed, including the apparent typo) |
| Grove Base HAT | grove_base_hat.pdf | p.4, Technical Details table | Operating Voltage | 3.3 V | This is the **HAT's own supply/logic voltage**, not a confirmed ADC voltage reference. **Do not treat ADC reference = 3.3V as verified** unless supported by driver source or a real measurement — this document does not state an ADC full-scale/reference voltage anywhere | `[VERIFIED-DATASHEET]` (as the HAT's operating voltage only) / `[MEASUREMENT-REQUIRED]` (as an ADC reference assumption) |
| Grove Base HAT (this project's actual unit) | grove_base_hat.pdf | p.3, boxed Note | Which I2C address (0x04 or 0x08) this project's actual installed HAT uses | Not established — depends on which MCU revision was actually shipped/purchased | **Do not automatically treat 0x04 as correct.** `config.py` in this project sets `GROVE_ADC_ADDR = 0x04` (per prior reading of that file), which matches the *older* STM32 revision per this datasheet — but since Seeed's own document confirms an active, chip-shortage-driven hardware revision with a *different* address (0x08 for MM32), this must be physically confirmed (e.g. `i2cdetect` against the real board) before being trusted, regardless of what the code currently assumes | `[MEASUREMENT-REQUIRED]` |
| Grove Base HAT | grove_base_hat.pdf | p.3, Pin Out diagram | Physical port groupings | Digital, PWM, UART, Analog, I2C, SWD/GPIO port groups shown on silkscreen-style diagram | Confirms physical port layout; individual analog channel labels (A0…) are visible in the diagram but not enumerated in accompanying prose text in this document | `[VERIFIED-DATASHEET]` |
| Grove Base HAT | grove_base_hat.pdf | p.2, "Attention" note | Board contents | "This hat does not contain a Raspberry Pi" | Confirms this is purely an add-on board, consistent with F-02 | `[VERIFIED-DATASHEET]` |

### 2.8 Raspberry Pi 4 Model B (host SBC)

| Component | Exact document | Page/section | Verified parameter | Value/range | Design implication | Evidence label |
|---|---|---|---|---|---|---|
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.6, §2.2 Interfaces | GPIO / I2C interface count | 28x user GPIO; "Up to 6x I2C" | Confirms multiple I2C bus options exist on-chip, though this project's physical wiring only uses one (per F-01/F-02 context and the Grove Base HAT's fixed I2C connector) | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.7, Table 2 Absolute Maximum Ratings | VIN (5V input pin) absolute max | Min −0.5 V, Max 6.0 V | This rating is for the 5V power-input pin, not directly the GPIO/I2C signal pins | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.7, prose immediately below Table 2 | GPIO bank voltage | "VDD_IO is the GPIO bank voltage which is tied to the on-board 3.3V supply rail." | Confirms GPIO/I2C signal pins are referenced to 3.3 V, not 5 V — directly relevant since this project also has a 5.00 V rail (F-11, for the LM358 stage) and a 3.28 V rail (F-08/F-09, for OPT101/MCP4725) that must never be connected directly to a GPIO/I2C pin | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.8, Table 3 DC Characteristics | VIH (input high voltage) | Min 2.0 V, Max VDD_IO (=3.3V) | The *maximum* input high voltage a GPIO/I2C pin is characterized for is 3.3 V — this is the closest this datasheet comes to a "do not exceed" figure for logic-level inputs, but it is a characterization table entry, not a standalone prose warning | `[VERIFIED-DATASHEET]` (table value) / `[ENGINEERING-INFERENCE]` (interpreting this as an implicit "never apply 5V to GPIO/I2C" warning — no separate explicit prose warning against 5V exists in this document) |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.8, Table 3 | VIL (input low voltage) | Min 0 V, Max 0.8 V | Logic-low threshold for GPIO/I2C pins | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.8, Table 3 | Pull-up / pull-down resistor range | 18–73 kΩ (47 kΩ typ) | Relevant if relying on internal GPIO pulls for any auxiliary signal (not the I2C bus itself, which per F-03/F-04/F-05/F-06 uses external Grove/MCP4725 hardware) | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.8, Table 3 | Output low/high current, drive strength | IOL/IOH 7 mA min (default 8mA strength), 16 mA max drive strength | Not directly relevant to the I2C-only interface used here, but bounds any GPIO-driven auxiliary signal in this project | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.9, §5.1.1 GPIO Pin Assignments, Fig. 3 | Physical I2C pin locations (default) | GPIO2 (pin 3) = SDA1, GPIO3 (pin 5) = SCL1 (default ALT0 function, per Table 5 on p.10) | Identifies exactly which physical header pins carry the I2C bus that the Grove Base HAT (F-02) and by extension the MCP4725/OPT101/ADC chain rides on | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.9, Fig. 3 boxed warning | ID_SD / ID_SC pins (physical pins 27/28) | "DO NOT USE these pins for anything other than attaching an I2C ID EEPROM. Leave unconnected if ID EEPROM not required." | Explicit, direct textual warning — the only such explicit "DO NOT" warning found anywhere in this datasheet, and it is about a **different** I2C interface (the HAT-ID EEPROM bus) than the main SDA1/SCL1 bus used for the Grove Base HAT | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.11, §5.6 Temperature Range and Thermals | Operating temperature range | 0–50 °C recommended; thermal throttle at junction ≤85 °C | Relevant to any long-duration bench testing of this simulator | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 | raspberry-pi-4-datasheet.pdf | p.8, §4.1 Power Requirements | USB-C power input | 5V at 3A (or 5V/2.5A if downstream USB load <500mA) | Confirms the Pi's own power input requirement; unrelated to the 3.28 V/5.00 V project rails, which are supplied separately (per F-08/F-09/F-11, source of those two rails not established in this document) | `[VERIFIED-DATASHEET]` |
| Raspberry Pi 4 (explicit "never connect 5V to GPIO" prose warning) | raspberry-pi-4-datasheet.pdf | — searched entire 13-page document — | Standalone prose warning against applying 5V to GPIO/I2C pins | **Not found as a standalone warning statement** — only the VIN table (p.7, −0.5 to 6.0V, for the 5V *power* pin only) and the VIH/VDD_IO characterization (p.8, max = 3.3V, for *logic* pins) exist | The conclusion "never apply 5V to a GPIO/I2C pin" is a valid engineering inference from these two tables, but it is **not a directly quoted warning** in this specific datasheet — this distinction matters because the user's instructions explicitly ask this to be flagged rather than presented as a verbatim warning | `[ENGINEERING-INFERENCE]` |

---

## 3. Contradictions found vs. `01_CURRENT_SYSTEM_AUDIT.md`

This section records findings only. **No conflicting file was modified in this prompt.**

### 3.1 DAC full-scale voltage: 3.28 V vs 3.2 V vs 3.3 V (relates to C-01/C-02/C-03, `01_CURRENT_SYSTEM_AUDIT.md` §5.2)

- F-10 (`00_BASE_CONTEXT.md`, `[VERIFIED-USER]`): MCP4725 full-scale = **3.28 V**.
- `config.py:107-115` (`01_CURRENT_SYSTEM_AUDIT.md` §5.2): `DAC_FULLSCALE_V = 3.2`, incorrectly tagged `[VERIFIED-USER]` in that file's own comments even though it does not match F-10.
- `config.py:149`: `ADC_VOLTAGE_REF = 3.3` — a **separate** Grove-ADC-side reference value, correctly kept distinct from the DAC full-scale value by the code's own test guard (`test_phase4_dac.py:113`, `assertNotEqual(DAC_FULLSCALE_V, ADC_VOLTAGE_REF)`).
- **New datasheet-evidence angle from this prompt:** neither 3.2 V nor 3.3 V is confirmed by any local datasheet. §2.6 above shows no local MCP4725 IC datasheet exists to check gain/reference error against 3.28 V, and §2.7 shows the Grove Base HAT's documented "3.3V" is its own operating voltage, not a proven ADC reference. This means **all three numbers (3.28, 3.2, 3.3) are presently ungrounded in datasheet evidence** — 3.28 V rests solely on the user's direct assertion (F-10, which is a legitimate and strong evidence class, just not a datasheet), while 3.2 V and 3.3 V in code have no cited backing at all in either the code comments (per that audit) or in any document read in this prompt.
- Finding: this is a genuine, still-unresolved discrepancy. It is **not fixed here** per this prompt's scope.

### 3.2 Grove ADC channel mapping: A0/A2 (code) vs A1 (many docs) (relates to C-10/C-11/C-12, `01_CURRENT_SYSTEM_AUDIT.md` §5.3)

- F-05/F-06 (`00_BASE_CONTEXT.md`, `[VERIFIED-USER]`): OPT101 IR → Grove ADC **A0**; OPT101 Red → Grove ADC **A2**; A1 unused (F-07).
- Code (`config.py:57-59`, `opt101_rx.py:4-7`, `test_phase5_rx.py`) is consistent with F-05/F-06/F-07.
- ~13 documents remain stale, most seriously the Phase 6 spec itself (`docs/claude_phases/06_*.md:14,26,85,105`) and `docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md:26`, which still describe A1=Red.
- **This prompt's datasheet evidence does not resolve which mapping is correct** — the Grove Base HAT datasheet (§2.7) confirms the HAT provides multiple analog channels and shows an "Analog" port group in its pin-out diagram, but does not itself enumerate which channel number (A0/A1/A2…) is authoritative; that determination rests entirely on F-05/F-06/F-07 (`[VERIFIED-USER]`), which the code already matches. The datasheet evidence here only confirms the *existence* of multiple ADC channels on the HAT, not the specific wiring — that remains a code-vs-docs consistency issue already flagged in `01_CURRENT_SYSTEM_AUDIT.md`, unchanged by this prompt.

### 3.3 WhaleTeq provenance leaking into code as if it were this project's physical hardware (relates to C-13, `01_CURRENT_SYSTEM_AUDIT.md` §5.5)

- This prompt's full read of `whale_device.pdf` (§1, §1.1 above) reinforces the finding already made in `01_CURRENT_SYSTEM_AUDIT.md`: WhaleTeq's AECG100 is a **separate commercial instrument with its own built-in optical modules**, structurally unrelated to this project (confirms N-01). The only legitimate use of the WhaleTeq document is as the historical source of the default SpO2 linear coefficients (A=110, B=25) referenced in `calibration.py:10-13,31,146`, `ppg_model.py:58`, and `test_calibration.py:43`. Those references should be worded as "default coefficients sourced from WhaleTeq reference methodology" rather than implying WhaleTeq hardware is present in this system — this rewording was already recommended in `01_CURRENT_SYSTEM_AUDIT.md` and is **not performed in this prompt** (no code files are touched here).

### 3.4 Banned evidence label `[VERIFIED-PDF]` (relates to C-14, `01_CURRENT_SYSTEM_AUDIT.md` §5.10)

- `calibration.py:13` and `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md` use the non-approved label `[VERIFIED-PDF]`. This document does not use that label anywhere, and does not modify those files. The correct replacement label depends on what is actually being cited there (likely `[VERIFIED-DATASHEET]` if citing `whale_device.pdf`, or possibly `[ENGINEERING-INFERENCE]` if the SpO2 coefficients were adapted rather than directly copied) — determining which is a task for a future prompt that touches `calibration.py`, not this one.

### 3.5 New finding this prompt: Grove Base HAT I2C address (0x04 vs 0x08) is a datasheet-confirmed, still-open hardware-revision question

- Not previously called out by number in `01_CURRENT_SYSTEM_AUDIT.md` (that audit's §10 open-unknowns list U-01/U-03/U-05/U-06 but does not include the HAT's own I2C address as a distinct item).
- `grove_base_hat.pdf` p.3 (§2.7 above) is unambiguous and internally explicit: the STM32-based hardware revision uses address **0x04**; the MM32-based revision (introduced due to a chip shortage, same Part Number 103030275) uses address **0x08**.
- `config.py` sets `GROVE_ADC_ADDR = 0x04` (per prior reading of that file in this session), which matches only the older STM32 revision.
- Per the user's explicit instruction: **do not automatically treat 0x04 as correct.** This is now `[MEASUREMENT-REQUIRED]` — the actual installed Grove Base HAT must be probed (e.g. `i2cdetect -y 1` against the real hardware) to confirm which address it actually responds on, since Seeed's own documentation confirms both variants exist under the same product listing and the datasheet cannot resolve which one was shipped in this project's specific unit.

---

## 4. Information still required before circuit calculation

The following items must be resolved — by physical measurement, by reading the actual installed
component markings, or by locating additional documentation — before any resistor, capacitor, or
LED-driver value can be responsibly calculated for this project:

1. **OPT101 front-end wiring:** whether pin 4 (1-MΩ Feedback) is tied to pin 5 (Output) in the
   actual installed module, or whether an external feedback network is used instead. No schematic
   exists locally for this. `[MEASUREMENT-REQUIRED]`
2. **OPT101 responsivity at the project's actual wavelengths (620–625 nm Red, 875 nm IR):** only a
   650 nm test-condition value (0.45 A/W) and a graphical curve exist. I am not sure based on the
   currently available evidence what the exact numeric responsivity is at either wavelength.
   `[UNKNOWN]` / `[MEASUREMENT-REQUIRED]`
3. **LM358 family — exact variant installed** (LM358 / LM358A / LM358B / LM358BA / LM2904-family):
   determines which of the two significantly different electrical-characteristics tables (§5.5 vs
   §5.7 in `lm358ba.pdf`) actually applies at the project's 5.00 V rail (F-11). Requires reading the
   physical chip top-mark against the Package Option Addendum. `[MEASUREMENT-REQUIRED]`
4. **2SC1815 — exact hFE bin installed** (O/Y/GR/BL): the filename suggests GR, but this is not
   proven by the (bin-generic) datasheet content itself. `[MEASUREMENT-REQUIRED]`
5. **2SC1815 — pinout confirmation on the physically installed part:** the datasheet's EBC pinout
   should not be assumed without checking the actual part, since third-party/clone TO-92 parts
   marked "C1815" have historically shipped with non-standard pinouts. `[MEASUREMENT-REQUIRED]`
6. **MCP4725 IC-level electrical parameters** (resolution behavior, INL/DNL, settling time,
   power-on-reset/EEPROM default, exact full-scale/gain-error relationship to VDD): no Microchip
   MCP4725 IC datasheet exists locally. I am not sure based on the currently available evidence what
   these values are; only a module-level schematic image is available. `[UNKNOWN]`
7. **The 3.28 V vs 3.2 V vs 3.3 V discrepancy** (§3.1): none of the three values is grounded in a
   local datasheet; 3.28 V rests on `[VERIFIED-USER]` (F-10) alone. `[MEASUREMENT-REQUIRED]` if an
   independent DMM measurement of the actual DAC full-scale output has not yet been performed and
   recorded.
8. **Grove Base HAT actual I2C address on the physically installed unit** (0x04 STM32-revision vs
   0x08 MM32-revision) — confirmed by this prompt's reading to be a real, datasheet-acknowledged
   hardware-revision split, not a hypothetical concern. `[MEASUREMENT-REQUIRED]`
9. **Grove Base HAT ADC voltage reference** — "Operating Voltage 3.3V" in the datasheet is the
   HAT's own supply/logic voltage, not a confirmed ADC full-scale reference. I am not sure based on
   the currently available evidence whether the ADC reference truly equals 3.3 V, a regulated
   internal reference, or something else. `[MEASUREMENT-REQUIRED]`
10. **LED driver circuit topology** (how the MCP4725 output, the LM358 stage, and the 2SC1815
    transistor are actually interconnected to drive the Red/IR LEDs): no schematic exists locally
    for this stage at all, confirmed already as an open item in `00_BASE_CONTEXT.md` §7 and
    `01_CURRENT_SYSTEM_AUDIT.md` §10 (U-06). I am not sure based on the currently available evidence
    what this topology is. `[UNKNOWN]`
11. **I2C bus pull-up loading** with two MCP4725 modules (each carrying its own onboard pull-ups
    per §2.6) plus the Grove Base HAT sharing one bus (per F-01/F-02/F-03/F-04): effective parallel
    pull-up resistance is not calculated or verified anywhere in the available documents.
    `[MEASUREMENT-REQUIRED]`

---

## 5. Summary

All eight files in `docs/ds_linhkien/` were read in full (OPT101 8 of 31 relevant pages spanning
Features through Typical Characteristics; LM358 family sections previously read in full — 5.5, 5.7,
7.3, 8, Family Comparison, Pin Config, Package Option Addendum; 2SC1815 all 4 pages; both LED
datasheets all pages including the IR LED's polarity diagram on p.5; the Grove Base HAT all 5 pages;
the Raspberry Pi 4 datasheet all 13 pages; and the MCP4725 module schematic image). The
`whale_device.pdf` brochure in `docs/whale_device/` was read in full and confirms N-01; the two
remaining WhaleTeq files were scoped at the metadata level only, per the reasoning in §1.1.

Two new, datasheet-grounded findings emerged in this prompt beyond what `01_CURRENT_SYSTEM_AUDIT.md`
already flagged: (a) the Grove Base HAT's own datasheet contains an internal contradiction about
which MCU/I2C-address revision is current (§2.7, §3.5), which upgrades the existing "ADC address"
assumption from an unexamined default to a confirmed, real, `[MEASUREMENT-REQUIRED]` hardware
question; and (b) neither LED datasheet's wavelength (620–625 nm Red, 875 nm IR) has a matching
tabulated OPT101 responsivity value — only a 650 nm test point and a graphical curve exist — which
is a concrete gap for any future optical signal-budget calculation.

No resistor or capacitor values were calculated, no LED driver was designed, and no schematic or PCB
file was created, per this prompt's explicit scope. Prompt 03 has not been started.

---

## 6. Addendum — items 3, 8 and 9 resolved by user confirmation (2026-07-29)

The body above is left unmodified as a point-in-time record. Three of the eleven
open items in §4 have since been closed by authoritative user facts (recorded as
F-13…F-17 in `00_BASE_CONTEXT.md` §3):

| §4 item | Status | Resolution |
|---|---|---|
| 3 — LM358 variant | **RESOLVED** | Installed device is **LM358P — standard/classic variant, PDIP package** (F-17). Use the classic LM358 table (`lm358ba.pdf` §5.7) at V<sub>S</sub> = 5 V: output swing (V+)−1.5 V typ (R<sub>L</sub> ≥ 10 kΩ), SR = 0.3 V/µs, V<sub>OS</sub> ±7 mV, I<sub>B</sub> 20 nA typ / 250 nA max, GBW 0.7 MHz. Common-mode range is ground to V<sub>S</sub>−1.5 V (V<sub>S</sub>−2 V over temperature). **Do not** apply LM358B / LM358BA numbers. |
| 8 — Grove HAT I²C address | **RESOLVED** | MCU is **MM32**, ADC I²C address is **0x08** (F-13, F-14). This matches the datasheet's own boxed note on p.3 and closes the revision split identified in §2.7 / §3.5. |
| 9 — Grove ADC reference | **RESOLVED** | Grove ADC full-scale / reference used by this project is **3.28 V**, resolution **12 bits** (F-15, F-16). The datasheet's "Operating Voltage 3.3 V" remains the HAT supply figure and is *not* the reference — §2.7's caution was correct. |

§4 item 7 (the 3.28 / 3.2 / 3.3 V split) is **partially** resolved: the code-level
inconsistency is gone — `config.py` now holds 3.28 V for both the MCP4725
full-scale and the Grove ADC reference (see `00_BASE_CONTEXT.md` §9). The
underlying evidence basis is unchanged: 3.28 V rests on `[VERIFIED-USER]` alone.
An independent DMM measurement of the actual MCP4725 full-scale output and of the
Grove ADC reference remains `[MEASUREMENT-REQUIRED]`.

Items 1, 2, 4, 5, 6, 10 and 11 remain open and unchanged.
