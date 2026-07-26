"""Allow ``python -m dexport.cli`` as well as ``python -m dexport``."""

from . import app

if __name__ == "__main__":
    app()
