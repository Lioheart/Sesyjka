from __future__ import annotations

import logging
import sys

from .app import SesyjkaApplication
from .logging_setup import configure_logging


def main() -> int:
    log_path = configure_logging()
    logging.getLogger(__name__).info("Uruchamianie Sesyjki. Log: %s", log_path)
    app = SesyjkaApplication()
    try:
        return int(app.run(sys.argv))
    except Exception:
        logging.getLogger(__name__).exception("Nieobsłużony błąd aplikacji")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
