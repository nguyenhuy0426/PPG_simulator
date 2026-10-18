# Third-party references

## Literature removed from the repository

These publications were stored as PDFs in `docs/` but nothing in the code or the
project documents referred to them. They were removed to keep third-party
copyrighted files out of a public repository. The citation is kept so the source
can be found again. An original copy can be restored from history, for example:

```bash
git show 8edab0a1:"docs/2018 Breathing rate estimation from the ECG and PPG A review.pdf" > review.pdf
```

| Former file in `docs/` | Citation |
|---|---|
| `005-Mohamed_new.pdf` | M. Elgendi, "On the analysis of fingertip photoplethysmogram signals," *Current Cardiology Reviews*, vol. 8, no. 1, pp. 14–25, 2012. |
| `1-s2.0-S1746809423011266-main.pdf` | G. R. E. Bradley and P. A. Kyriacou, "Opening the envelope: Efficient envelope-based PPG denoising algorithm," *Biomedical Signal Processing and Control*, vol. 88, 105693, 2024. doi:10.1016/j.bspc.2023.105693 |
| `1vmoqb4wv271y4m2ulnt4i5vwj7so8by.pdf` | P. Jain, C. Ding, C. Rudin and X. Hu, "A self-supervised algorithm for denoising photoplethysmography signals for heart rate estimation from wearables," *Harvard Data Science Review*, vol. 6, no. 3, 2024. doi:10.1162/99608f92.8636cb81 |
| `2018 Breathing rate estimation from the ECG and PPG A review.pdf` | P. H. Charlton et al., "Breathing rate estimation from the electrocardiogram and photoplethysmogram: A review," *IEEE Reviews in Biomedical Engineering*, vol. 11, pp. 2–20, 2018. doi:10.1109/RBME.2017.2763681 |
| `2307.07414v1.pdf` | S. S. Khan, S. Kumar, B. Jan, L. Somappa and S. Malik, "An embedded auto-calibrated offset current compensation technique for PPG/fNIRS system," arXiv:2307.07414, 2023. |
| `CVv391S182016022.pdf` | Đặng Xuân Kiên and Vũ Đức Hải, "Thiết kế hệ thống thu thập, phân tích và xử lý tín hiệu điện tim di động photoplethysmography (PPG) dựa trên hệ điều hành Android," *Journal of Transportation Science and Technology*, vol. 18, p. 22, Feb. 2016 (scanned copy). |
| `PPG_sig_proc_Chapter_20210612.pdf` | E. Mejía-Mejía, J. Allen, K. Budidha, C. El-Hajj, P. A. Kyriacou and P. H. Charlton, "Photoplethysmography signal processing and synthesis," book chapter in *Photoplethysmography: Technology, Signal Analysis and Applications* (author preprint dated 12 June 2021). |
| `b7862f6475958be20fe047754abd818da9c0.pdf` | B. Lin, M. Atef and G. Wang, "14.85 µW analog front-end for photoplethysmography acquisition with 142-dBΩ gain and 64.2-pArms noise," *Sensors*, vol. 19, no. 3, 512, 2019. doi:10.3390/s19030512 |
| `engproc-128-00047.pdf` | N. Bugtai et al., "Simulation and real-time testing of photoplethysmogram signal-based biometric recognition system," *Engineering Proceedings*, vol. 128, 47, 2026. doi:10.3390/engproc2026128047 |
| `sensors-26-00324-v2.pdf` | A. Benkert, J. Bludau, L. Boborzi, S. Prueckner and R. Schniepp, "Impact of helicopter vibrations on in-ear PPG monitoring for vital signs—Mountain Rescue Technology Study (MoReTech)," *Sensors*, vol. 26, no. 1, 324, 2026. doi:10.3390/s26010324 |
| `transfer_db.pdf` | D. Birrenkott, "Respiratory quality index design and validation for ECG and PPG derived respiratory data," transfer-of-status report, Department of Engineering Science, University of Oxford, 11 Dec. 2015. |
| `https___www.frontiersin.org_..._fphys-12-808451-g003.webp` | Figure 3 of *Frontiers in Physiology* article 12:808451 (image only). |
| `effect_HR_SpO2_RR_to_PPG.docx` | Personal Vietnamese notes saved as plain text with a `.docx` name; not a publication. |
| `some_ques_aboutPPG.txt` | Four personal study questions about PPG; not a publication. |

## Third-party documents kept in the repository

The hardware design documents cite these files by name and page, so they stay.

| File | Document |
|---|---|
| `docs/ds_linhkien/MCP4725-Data-Sheet.pdf` | Microchip MCP4725 12-bit DAC with EEPROM, DS20002039E |
| `docs/ds_linhkien/MCP4725_schematic.png` | Schematic image of an MCP4725 breakout module (not the board used here) |
| `docs/ds_linhkien/opt101.pdf` | Texas Instruments OPT101 monolithic photodiode and transimpedance amplifier, SBBS002B |
| `docs/ds_linhkien/lm358ba.pdf` | Texas Instruments LM358 family dual operational amplifiers, SLOS068AB (Oct. 2024) |
| `docs/ds_linhkien/2SC1815L-GR.PDF` | Toshiba 2SC1815 NPN transistor |
| `docs/ds_linhkien/IR_led_3.3mm_datasheet.pdf` | 3 mm infrared LED SIR234 |
| `docs/ds_linhkien/red_led_3.3mm_datasheet.pdf` | 3 mm red LED YSL-R531R3D-D2 |
| `docs/ds_linhkien/grove_base_hat.pdf` | Seeed Studio Grove Base Hat for Raspberry Pi (103030275) |
| `docs/ds_linhkien/raspberry-pi-4-datasheet.pdf` | Raspberry Pi 4 Model B datasheet, release 1.1, March 2024 |
| `docs/whale_device/user_manual.pdf` | WhaleTeq AECG100 ECG, PPG and PWTT multifunction tester user manual (PC software 1.0.10.40, 2025-12-08). Source of the parameter ranges cited in `models/limits.py`, `models/respiration.py` and `models/waveform.py`. |
| `docs/whale_device/whale_device.pdf` | WhaleTeq AECG100 datasheet v2.1 (2024-04-17) |
| `docs/whale_device/version_sdk_app_whale.pdf` | WhaleTeq AECG100 SDK and application version notes |
