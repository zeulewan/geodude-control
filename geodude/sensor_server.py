"""Compatibility launcher for the GEO-DUDe hardware backend."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.sensor_server import *  # noqa: F401,F403
from backend.sensor_server import app, camera_reader_thread, pca_init, sensor_loop


if __name__ == "__main__":
    try:
        pca_init()
    except Exception as e:
        print("PCA init failed: %s" % e, flush=True)
    import threading

    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=camera_reader_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
