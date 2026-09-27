"""The `gpu` marker (docs/06 §1a): registered, deselected in CI, skipped unless QRAF_GPU=1."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DUMMY = "tests/test_markers.py::test_dummy_gpu"


def pytest_run(*args, gpu=None):
    env = {k: v for k, v in os.environ.items() if k != "QRAF_GPU"}
    if gpu is not None:
        env["QRAF_GPU"] = gpu
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


@pytest.mark.gpu
def test_dummy_gpu():
    """Stands in for the real-generation test; only ever run through pytest_run below."""
    assert True


def test_gpu_marker_is_registered():
    rc, out = pytest_run("--markers")
    assert rc == 0 and "@pytest.mark.gpu:" in out


def test_not_gpu_deselects_gpu_tests():
    rc, out = pytest_run("-q", "-m", "not gpu", DUMMY)
    assert "1 deselected" in out and "passed" not in out


def test_gpu_tests_skip_without_qraf_gpu():
    rc, out = pytest_run("-q", "-rs", DUMMY)
    assert rc == 0 and "1 skipped" in out and "QRAF_GPU" in out


def test_gpu_tests_run_with_qraf_gpu():
    rc, out = pytest_run("-q", DUMMY, gpu="1")
    assert rc == 0 and "1 passed" in out
