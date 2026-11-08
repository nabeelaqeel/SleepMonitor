"""Config hardening — the JWT_SECRET placeholder must never boot.

Runs `import api.config` in a subprocess with the exact .env.example
placeholder JWT_SECRET and expects a non-zero exit. A subprocess (not an
in-process importlib reload) because api.config raises at IMPORT time and
also loads .env.development on import — isolating it keeps the surrounding
pytest process' environment clean regardless of what CI exported.

The "accepts a strong secret" side is exercised by test_api_smoke.py,
which imports app with CI's strong JWT_SECRET in the environment.
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The placeholder .env.example ships — copying the template verbatim must
# fail startup (api/config.py rejects values that hash-match / contain it).
PLACEHOLDER_SECRET = "change_me_random_hex_at_least_32_characters_long"


def test_placeholder_jwt_secret_refused():
    """Booting api.config with the .env.example placeholder JWT_SECRET must abort in a subprocess, erroring at JWT_SECRET."""
    env = {**os.environ, "JWT_SECRET": PLACEHOLDER_SECRET}
    result = subprocess.run(
        [sys.executable, "-c", "import api.config"],
        # DELIBERATE non-zero exit — check=False (the point of this test)
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode != 0, "placeholder JWT_SECRET must abort startup"
    assert "JWT_SECRET" in result.stderr, "failure must point at JWT_SECRET"


def test_short_jwt_secret_refused():
    """Booting api.config with a below-minimum-length JWT_SECRET must abort in a subprocess, erroring at JWT_SECRET."""
    env = {**os.environ, "JWT_SECRET": "too_short"}
    result = subprocess.run(
        [sys.executable, "-c", "import api.config"],
        # DELIBERATE non-zero exit — check=False (the point of this test)
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode != 0, "32-char-minimum JWT_SECRET must abort startup"
    assert "JWT_SECRET" in result.stderr, "failure must point at JWT_SECRET"
