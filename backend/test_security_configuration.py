"""FIX 5 configuration-hardening checks."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_demo_passwords_are_configurable_and_not_short():
    import main
    assert len(main.DEMO_PATIENT_PASSWORD) >= 8
    assert len(main.DEMO_DOCTOR_PASSWORD) >= 8
    assert len(main.DEMO_ADMIN_PASSWORD) >= 8


def test_database_and_upload_paths_are_environment_driven():
    import main
    assert main.DATABASE_URL
    assert main.UPLOAD_DIR.is_absolute()


def test_production_rejects_wildcard_cors():
    env = os.environ.copy()
    env.update({"SIH_ENV": "production", "SIH_CORS_ORIGINS": "*", "SIH_DEMO_MODE": "0"})
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Wildcard CORS is forbidden in production" in (result.stdout + result.stderr)
