"""Isolated CPU inference process: stdout contains exactly one JSON preview."""
import argparse
from dataclasses import asdict
import json

# The Neural page kills a worker that has not answered after this many seconds
# (ui/frames/neural_frame.py); scripts/verify_generators_on_pi.py times the worker against it.
WORKER_TIMEOUT_S = 120


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=int)
    parser.add_argument('model', nargs='?', default='LSM-GAN', choices=('LSM-GAN', 'PSF-GAN'))
    parser.add_argument('hr', nargs='?', type=float, default=75.0, help='requested HR in bpm (PSF-GAN only)')
    args = parser.parse_args(argv)
    if args.model == 'PSF-GAN':
        from core.psf_preview import PSFSequenceGenerator
        preview = PSFSequenceGenerator().generate(args.seed, args.hr)
    else:
        from core.neural_preview import LSMSequenceGenerator
        preview = LSMSequenceGenerator().generate(args.seed)
    print(json.dumps(asdict(preview), allow_nan=False))


if __name__ == '__main__':
    main()
