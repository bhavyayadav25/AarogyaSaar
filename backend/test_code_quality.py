import inspect
from datetime import datetime, timezone
from pathlib import Path

import main


def test_utc_now_uses_modern_utc_clock_and_preserves_naive_db_boundary():
    value = main.utc_now()
    assert isinstance(value, datetime)
    assert value.tzinfo is None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((now - value).total_seconds()) < 5


def test_application_code_has_no_deprecated_utcnow_calls():
    backend_dir = Path(main.__file__).resolve().parent
    offenders = []
    for path in backend_dir.glob("*.py"):
        if path.name.startswith("__") or path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        if "datetime.utcnow" in text:
            offenders.append(path.name)
    assert offenders == []
