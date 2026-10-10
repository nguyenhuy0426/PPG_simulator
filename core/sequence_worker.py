"""Isolated CPU inference process: stdout contains exactly one JSON preview."""
import argparse
from dataclasses import asdict
import json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=int)
    parser.add_argument('--model', choices=('lsm', 'physiomix'), default='lsm')
    parser.add_argument('--hr', type=float, default=75.)
    parser.add_argument('--domain', default='bidmc')
    args = parser.parse_args(argv)
    if args.model == 'physiomix':
        from core.neural_preview import PhysioMixGenerator
        preview = PhysioMixGenerator().generate(args.seed, args.hr, args.domain)
    else:
        from core.neural_preview import LSMSequenceGenerator
        preview = LSMSequenceGenerator().generate(args.seed)
    print(json.dumps(asdict(preview), allow_nan=False))


if __name__ == '__main__':
    main()
