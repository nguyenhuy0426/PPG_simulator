# Hardware validation records

Each dated folder holds what was run for a hardware check and the files it produced. Most come
from the Raspberry Pi 4; a file made on the laptop says so (in 2026-09-30, `pytest.txt` and
`ui-smoke.txt`). These records are software evidence. None of them measures a DAC voltage, an
LED current or the optical path unless it says so.

| Folder | Contents |
|---|---|
| [2026-09-30/](2026-09-30/) | DAC writer timing counters (headless and with the UI), the LSM-GAN strip on the Pi's PyTorch 2.5.1 compared with the laptop, an A0 capture during playback |

## Generators on the Pi

[scripts/verify_generators_on_pi.py](../../scripts/verify_generators_on_pi.py) checks that the
three generators in `assets/neural` (PhysioMix, PhysioFlow and LSM-GAN) compute on the Pi the
strips they compute on the laptop, and times them. Close the simulator first, or run
`systemctl --user stop ppg-simulator.service` if `scripts/deploy_and_run.sh` started it. Then,
on the Pi:

```bash
cd ~/final_project/PPG_simulator_raspi
.venv/bin/python scripts/verify_generators_on_pi.py --out docs/hardware-validation/$(date +%F)/generators.json
```

For each generator the script:

1. runs the worker that the Neural page starts (`python -m core.sequence_worker`), which must
   answer within the 120 s after which the page gives up (`WORKER_TIMEOUT_S` in
   `core/sequence_worker.py`);
2. loads the model with the app's loader, which checks its SHA-256 against
   `assets/neural/manifest.json`;
3. feeds the noise vectors and conditions stored in `assets/neural/generator_reference.json`
   to the model and compares every sample with the laptop's strip;
4. checks that the app's own `generate()`, from a seed, returns the laptop's strips. Without
   AVX2 (as on the Pi) `torch.randn` rounds the seeded noise slightly differently (about 1e-6
   on the laptop with `ATEN_CPU_CAPABILITY=default`), so the noise difference is reported and
   only the strips are judged;
5. times one 30 s strip as Table 1 of the paper does: one thread, one warm-up, median of
   seven runs.

The exit status is 0 when no check failed. On the laptop the whole run takes about 20 s; it has
not been run on the Pi yet.

A strip passes when no sample differs from the laptop's by more than 1e-3 in the generators'
normalised units. That is 45 µV at the default 45 mV infrared amplitude, under 0.06 of a DAC
step. On the laptop, changing the thread count or the convolution kernels moves a strip by at
most 2.4e-6. If the worker dies with an illegal instruction, the installed PyTorch build does
not suit the Cortex-A72; `requirements/neural.txt` pins the version that does, and the script
checks it before importing torch.

Copy the report back to the laptop and commit it in its date folder (create the folder
first; `scp` does not):

```bash
mkdir -p docs/hardware-validation/<date>
scp ppg-rpi4-ethernet:final_project/PPG_simulator_raspi/docs/hardware-validation/<date>/generators.json docs/hardware-validation/<date>/
```

The reference is made on the laptop. Remake it whenever a model in `assets/neural` changes;
`tests/test_verify_generators_on_pi.py` fails until it matches the manifest again:

```bash
PPG_DRY_RUN=1 .venv/bin/python scripts/verify_generators_on_pi.py --make-reference
```
