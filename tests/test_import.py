"""R14: the package imports without PyObjC and never imports EventKit eagerly."""

import subprocess
import sys


def _run(code: str) -> subprocess.CompletedProcess[str]:
    # A fresh interpreter, so the result doesn't depend on test order.
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


def test_imports_with_pyobjc_blocked() -> None:
    code = (
        "import sys\n"
        "for name in ('EventKit', 'Foundation', 'objc'):\n"
        "    sys.modules[name] = None\n"
        "import macos_calendar_events as m\n"
        "print(m.__version__)\n"
    )
    proc = _run(code)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() != ""


def test_import_does_not_load_eventkit() -> None:
    code = "import sys, macos_calendar_events\nprint('EventKit' in sys.modules)\n"
    proc = _run(code)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"
