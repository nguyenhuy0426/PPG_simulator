"""How often does the APFT HR-range search find a window in range within MAX_CALLS generator calls of BATCH windows
(the Pi's 240 s budget at ~57-60 s a batch of 8)? Real checkpoint, laptop CPU.
python scripts/apft_range_eval.py --trials 20 [--batch 1 --max-calls 5 for the unbatched search]"""
import argparse, json, os, sys
sys.path.insert(0, os.getcwd())
import torch
from core.apft_preview import APFTSequenceGenerator
from core import apft_range

p = argparse.ArgumentParser()
p.add_argument("--trials", type=int, default=20)
p.add_argument("--max-calls", type=int, default=4)
p.add_argument("--batch", type=int, default=apft_range.BATCH)
p.add_argument("--out")
a = p.parse_args()
torch.set_num_threads(4)
gen = APFTSequenceGenerator()
ticks = iter(range(10**9))
clock = lambda: next(ticks)          # one tick per clock read: 3 reads a call -> budget counts calls
rows = {}
for lo, hi in ((60, 65), (70, 75), (70, 80), (85, 90), (95, 100), (60, 100)):
    found, tries, rates = 0, [], []
    for trial in range(a.trials):
        r = apft_range.search(gen.windows, lo, hi, seed=10007 * trial + lo, budget_s=3 * a.max_calls - 2,
                             batch=a.batch, clock=clock)
        tries.append(len({t[0] for t in r.tries}))
        if r.window is not None:
            found += 1
            rates.append(r.check.bpm)
    rows[f"{lo}-{hi}"] = dict(found=found, trials=a.trials, mean_calls=sum(tries) / len(tries),
                             measured=[round(x, 1) for x in rates])
    print(f"{lo}-{hi} bpm: in range {found}/{a.trials}, mean calls {sum(tries)/len(tries):.1f}, "
          f"accepted rates {min(rates, default=float('nan')):.1f}-{max(rates, default=float('nan')):.1f}", flush=True)
if a.out:
    json.dump(dict(max_calls=a.max_calls, batch=a.batch, rows=rows), open(a.out, "w"), indent=1)
