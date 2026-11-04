"""Isolated CPU inference process: stdout contains exactly one JSON preview."""
import argparse
from dataclasses import asdict
import json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=int)
    args = parser.parse_args(argv)
    from core.neural_preview import LSMSequenceGenerator
    preview = LSMSequenceGenerator().generate(args.seed)
    print(json.dumps(asdict(preview), allow_nan=False))


if __name__ == '__main__':
    main()
