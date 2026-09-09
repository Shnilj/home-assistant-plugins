"""Test bootstrap: isolate data/config to a temp dir and make `app` importable."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # catwatch/
sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="cw-test-")
os.environ["DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["CONFIG_DIR"] = os.path.join(_tmp, "config")
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["CONFIG_DIR"], exist_ok=True)
