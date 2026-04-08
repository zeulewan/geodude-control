"""Compatibility launcher for the GEO-DUDe attitude controller."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.attitude_controller import *  # noqa: F401,F403
from backend.attitude_controller import app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, threaded=True)
