"""Run the quickstart the way a reader does and check its printed summary."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "quickstart.sh"
HEADINGS = ("Auction replay quickstart", "Benchmark summary",
            "Bid ceilings for the team that won each sale (neutral scenario)",
            "Buy versus pass bounds at the price paid (projected season points)", "Files")


@unittest.skipIf(shutil.which("sh") is None, "the quickstart needs a POSIX shell")
class QuickstartChecks(unittest.TestCase):
    def test_quickstart_prints_buy_versus_pass_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            # Start outside the checkout to prove the script finds the repository on its own.
            result = subprocess.run(["sh", str(SCRIPT), str(output)], cwd=directory,
                                    env=dict(os.environ, PYTHON=sys.executable),
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("report.md", "decisions.csv", "summary.json"):
                self.assertTrue((output / name).is_file(), name)
        lines = result.stdout.splitlines()
        for heading in HEADINGS:
            self.assertIn(heading, lines)
        self.assertIn("Benchmark complete: yes (replay exit code 0)", lines)
        self.assertLess(len(lines), 70, "the summary should stay short")

        def table(heading):
            start = next(i for i in range(lines.index(heading), len(lines)) if lines[i].startswith("Pick"))
            rows = {line.split()[0]: line.split() for line in lines[start + 1:start + 13]}
            self.assertEqual(sorted(rows, key=int), [str(pick) for pick in range(1, 13)])
            return rows

        # One row per sale. These rows back the examples in examples/synthetic/README.md.
        ceilings, bounds = table(HEADINGS[2]), table(HEADINGS[3])
        self.assertEqual([ceilings[pick][8] for pick in ("1", "3", "4")], ["$14", "$7", "$0"])
        self.assertEqual((bounds["1"][1:4], bounds["1"][-1]), (["Player", "B1", "$12"], "buy"))
        self.assertEqual((bounds["3"][1:4], bounds["3"][-1]), (["Player", "A1", "$9"], "pass"))
        self.assertEqual((bounds["4"][1:4], bounds["4"][-1]), (["Player", "D1", "$10"], "pass"))


if __name__ == "__main__":
    unittest.main()
