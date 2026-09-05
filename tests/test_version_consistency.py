"""Version strings must agree across the code and the README.

The repository has carried three different numbers at once (config.py 3.1.0,
README badge 4.0.0, README body 4.1.0). A user reading the README then sees a
different version in the log banner main.py prints from config.FIRMWARE_VERSION,
and a bug report cannot be pinned to a build. config.FIRMWARE_VERSION is the
single source of truth; this test is what stops the README drifting from it
again.
"""

import os
import re
import unittest

import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
BADGE = re.compile(r"!\[Version\]\(https://img\.shields\.io/badge/version-([\d.]+)-")
BODY = re.compile(r"^\*\*Version:\*\*\s*([\d.]+)", re.MULTILINE)


def _readme() -> str:
    with open(README, encoding="utf-8") as fh:
        return fh.read()


class TestVersionConsistency(unittest.TestCase):

    def test_firmware_version_is_semver(self):
        self.assertRegex(config.FIRMWARE_VERSION, SEMVER)

    def test_readme_badge_matches_config(self):
        match = BADGE.search(_readme())
        self.assertIsNotNone(match, "README.md has no version badge to check")
        self.assertEqual(match.group(1), config.FIRMWARE_VERSION)

    def test_readme_body_matches_config(self):
        match = BODY.search(_readme())
        self.assertIsNotNone(match, "README.md has no '**Version:**' line to check")
        self.assertEqual(match.group(1), config.FIRMWARE_VERSION)


if __name__ == "__main__":
    unittest.main()
