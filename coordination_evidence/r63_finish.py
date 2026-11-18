"""Serial final checks; each phase owns its own atomic lock and aborts on failure."""
from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    for phase in ("fixed_tests", "fixed_after", "fixed_off", "fixed_goldens"):
        print(f"R63 FINAL PHASE {phase}", flush=True)
        result = subprocess.run([sys.executable, str(root / "coordination_evidence/r63_checks.py"), phase], cwd=root)
        if result.returncode:
            sys.exit(result.returncode)
