"""Isolated CPU inference process: stdout contains exactly one JSON preview."""
import argparse
from dataclasses import asdict
import json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=int)
    parser.add_argument('--model', choices=('lsm', 'physiomix', 'physioflow'), default='lsm')
    parser.add_argument('--hr', type=float, default=75.)
    parser.add_argument('--domain', default='bidmc')
    parser.add_argument('--hr-range', type=float, nargs=2, metavar=('LOW', 'HIGH'),
                        help='Rate range in bpm (PhysioMix/PhysioFlow); replaces --hr')
    args = parser.parse_args(argv)
    if args.model in ('physiomix', 'physioflow'):
        from core.neural_preview import PhysioMixGenerator
        preview = PhysioMixGenerator(slot=args.model).generate(args.seed, args.hr, args.domain,
                                                               hr_range=args.hr_range)
    else:
        from core.neural_preview import LSMSequenceGenerator
        preview = LSMSequenceGenerator().generate(args.seed)
    print(json.dumps(asdict(preview), allow_nan=False))


if __name__ == '__main__':
    main()
