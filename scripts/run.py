#!/usr/bin/env python3
"""Choose an explicitly configured or private Python environment; never install implicitly."""
import os
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    configured = os.environ.get('TWK_PYTHON') or os.environ.get('WKR_PYTHON')
    candidates = [Path(configured).expanduser()] if configured else [
        Path.home()/'.local/share/teacher-wenkai/venv/bin/python',
        Path.home()/'.local/share/wenkai-research/venv/bin/python',
        Path(sys.executable),
    ]
    interpreter = next((p for p in candidates if p.is_file()), None)
    if interpreter is None: raise SystemExit('Configured Python interpreter does not exist')
    raise SystemExit(subprocess.call([str(interpreter), str(Path(__file__).resolve().with_name('research.py')), *sys.argv[1:]]))
