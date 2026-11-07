"""Isolated CPU inference process: stdout contains exactly one JSON preview."""
from dataclasses import asdict
import json
import sys
from core.neural_preview import LSMSequenceGenerator

if __name__ == '__main__':
    if len(sys.argv)>2 and sys.argv[2]=='PSF-GAN':
        from core.psf_preview import PSFSequenceGenerator
        preview=PSFSequenceGenerator().generate(int(sys.argv[1]),float(sys.argv[3]))
    else:
        preview=LSMSequenceGenerator().generate(int(sys.argv[1]))
    print(json.dumps(asdict(preview),allow_nan=False))
