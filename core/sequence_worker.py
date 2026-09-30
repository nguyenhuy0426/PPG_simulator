"""Isolated CPU inference process: stdout contains exactly one JSON preview."""
from dataclasses import asdict
import json
import sys
from core.neural_preview import LSMSequenceGenerator

if __name__ == '__main__':
    preview=LSMSequenceGenerator().generate(int(sys.argv[1]))
    print(json.dumps(asdict(preview),allow_nan=False))
