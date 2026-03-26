"""Compatibility launcher for the GEO-DUDe PCA9685 test utility."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.pca9685_test import *  # noqa: F401,F403
