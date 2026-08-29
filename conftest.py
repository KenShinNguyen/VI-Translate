"""Put the repository root on sys.path for the test run.

The tests import `pdf2zh` and `scripts.translate_pdf` from the checkout rather
than from an installed package. `python -m pytest` happens to work because -m
puts the working directory on sys.path; plain `pytest` does not, and every test
module failed to import. A conftest.py here fixes both invocations.
"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
