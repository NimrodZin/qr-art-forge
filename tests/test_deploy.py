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
