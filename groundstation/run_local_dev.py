import os
import threading

import wheel_control


def main():
    port = int(os.environ.get("WHEEL_CONTROL_PORT", "8081"))
    threading.Thread(target=wheel_control.sensor_loop, daemon=True).start()
    threading.Thread(target=wheel_control.watchdog_loop, daemon=True).start()
    threading.Thread(target=wheel_control.positions_flush_loop, daemon=True).start()
    wheel_control.app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
