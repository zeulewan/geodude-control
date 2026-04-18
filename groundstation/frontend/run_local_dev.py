import os

try:
    from . import app as frontend_app
except ImportError:
    import app as frontend_app


def main():
    port = int(os.environ.get("WHEEL_CONTROL_PORT", "8081"))
    frontend_app.main(port=port)


if __name__ == "__main__":
    main()
