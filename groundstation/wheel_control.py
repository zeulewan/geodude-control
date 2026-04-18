"""Compatibility launcher for the groundstation frontend service.

The frontend app now lives in groundstation/frontend/app.py. Keep this wrapper
so existing systemd units and old dev scripts continue to work during the
layout refactor.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from frontend.app import *  # noqa: F401,F403
from frontend.app import main


if __name__ == "__main__":
    main()
