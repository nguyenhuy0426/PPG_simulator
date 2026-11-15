"""Isolated CPU inference process: stdout contains exactly one JSON preview."""
import argparse
from dataclasses import asdict
import json

# The Neural page kills a worker that has not answered after this many seconds (ui/frames/neural_frame.py).
WORKER_TIMEOUT_S = 120
# APFT-GAN on the Pi 4 (PyTorch 2.5.1, one thread, GUI running): 12 s to load the 402 MB checkpoint and 91-100 s per
# 30 s window, measured 15/11/2026 (docs/hardware-validation/2026-11-14-ir-overload/README.md section 18).
APFT_TIMEOUT_S = 300
HR_MODELS = ('PSF-GAN', 'APFT-GAN')     # take a requested heart rate


def timeout_s(model):
    return APFT_TIMEOUT_S if model == 'APFT-GAN' else WORKER_TIMEOUT_S


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=int)
    parser.add_argument('model', nargs='?', default='LSM-GAN', choices=('LSM-GAN', *HR_MODELS))
    parser.add_argument('hr', nargs='?', type=float, default=75.0, help='requested HR in bpm (PSF-GAN and APFT-GAN)')
    args = parser.parse_args(argv)
    if args.model == 'PSF-GAN':
        from core.psf_preview import PSFSequenceGenerator
        preview = PSFSequenceGenerator().generate(args.seed, args.hr)
    elif args.model == 'APFT-GAN':
        from core.apft_preview import APFTSequenceGenerator
        preview = APFTSequenceGenerator().generate(args.seed, args.hr)
    else:
        from core.neural_preview import LSMSequenceGenerator
        preview = LSMSequenceGenerator().generate(args.seed)
    print(json.dumps(asdict(preview), allow_nan=False))


if __name__ == '__main__':
    main()
