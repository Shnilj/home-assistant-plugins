"""CLI entry point for (re)training the recognition model.

    python3 -m app.train

Normally you just click "Train" in the web UI, but this is handy for testing.
"""
from __future__ import annotations

import logging

from . import classifier, config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.ensure_dirs(config.load_settings())
    summary = classifier.train()
    if summary["trained"]:
        print(f"Trained on {summary['samples']} images: {summary['cats']}")
    else:
        print("No labelled images yet. Label some captures in the web UI first.")


if __name__ == "__main__":
    main()
