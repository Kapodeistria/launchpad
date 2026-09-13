"""Keep the suite independent of the machine it runs on.

The app row is configuration read at import time from `$LAUNCHPAD_HOME`, so
anyone running these tests with their own `apps.toml` would otherwise watch
the layout tests fail against a board that is not broken, merely theirs.
Pointing at a directory that does not exist makes every run use the built-in
row, which is what those tests are about.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ["LAUNCHPAD_HOME"] = str(Path(__file__).parent / "_no_config_here")
