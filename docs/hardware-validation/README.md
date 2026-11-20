# Hardware validation records

Each dated folder holds what was run for a hardware check and the files it produced. Most come
from the Raspberry Pi 4; a file made on the laptop says so (in 2026-09-30, `pytest.txt` and
`ui-smoke.txt`). These records are software evidence. None of them measures a DAC voltage, an
LED current or the optical path unless it says so.

| Folder | Contents |
|---|---|
| [2026-11-21-dc-sweep-ac/](2026-11-21-dc-sweep-ac/README.md) | DC sweep 300-1500 mV at 45 mV AC: received vs sent AC per step, before and after AC balance (`core/ac_balance.py`) |
| [2026-09-30/](2026-09-30/) | DAC writer timing counters (headless and with the UI), the LSM-GAN strip on the Pi's PyTorch 2.5.1 compared with the laptop, an A0 capture during playback |

## Generators on the Pi

`scripts/verify_generators_on_pi.py` and `tests/test_verify_generators_on_pi.py` (commit `b04a7f90`, 2026-10-19)
compared the PhysioMix, PhysioFlow and LSM-GAN strips computed on the Pi with the laptop's. Neither file is in the
repository any more: the merge `95958d4a` (2026-11-07) left them out, and PhysioMix and PhysioFlow had already left
the app. No `generators.json` from the Pi was ever committed here. `assets/neural/generator_reference.json` remains
and no code reads it now. To repeat the check, restore the script from that commit
(`git show b04a7f90:scripts/verify_generators_on_pi.py`) and adapt it to the generators the app still ships.
