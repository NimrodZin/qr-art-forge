"""`gpu` tests (docs/06 §1a) run only on the PC with QRAF_GPU=1; CI also deselects them."""
import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("QRAF_GPU") == "1":
        return
    skip = pytest.mark.skip(reason="gpu test: set QRAF_GPU=1 on the RTX 4070 to run")
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(skip)
