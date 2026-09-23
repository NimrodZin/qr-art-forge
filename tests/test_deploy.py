"""Deploy config: GitHub main mirrors to the Hugging Face Space."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNC = ROOT / ".github" / "workflows" / "sync-to-hf.yml"
SPACE = "huggingface.co/spaces/zinim78/qr-art-forge"


def test_sync_workflow_pushes_main_to_space():
    assert SYNC.exists()
    text = SYNC.read_text()
    assert re.search(r"^on:\s*\n\s+push:\s*\n\s+branches:\s*\[\s*main\s*\]", text, re.M)
    assert "secrets.HF_TOKEN" in text
    assert SPACE in text


def test_readme_front_matter_is_gradio_space():
    text = (ROOT / "README.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m
    front = m.group(1).splitlines()
    assert "sdk: gradio" in front
    assert "app_file: app.py" in front


def test_readme_short_description_within_hub_limit():
    text = (ROOT / "README.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m
    m = re.search(r"^short_description:\s*(.*?)\s*$", m.group(1), re.M)
    assert m
    assert len(m.group(1)) <= 60


def test_ui_api_info_builds():
    import app
    app.build_ui().get_api_info()


def test_requirements_pin_gradio_and_pydantic():
    for name in ("requirements.txt", "requirements-ci.txt"):
        lines = (ROOT / name).read_text().splitlines()
        assert "gradio==4.44.1" in lines, name
        assert "pydantic==2.10.6" in lines, name


def test_readme_front_matter_pins_python_version():
    text = (ROOT / "README.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m
    assert "python_version: 3.11" in m.group(1).splitlines()
    assert "sdk_version: 4.44.1" in m.group(1).splitlines()
