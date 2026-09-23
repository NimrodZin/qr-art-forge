"""The scheduler must build from the real DreamShaper 8 config (network; tiny file)."""
from diffusers import DPMSolverMultistepScheduler
import app


def test_scheduler_builds_from_dreamshaper_config():
    config = DPMSolverMultistepScheduler.load_config("Lykon/dreamshaper-8", subfolder="scheduler")
    scheduler = app.make_scheduler(config)
    assert scheduler.config.algorithm_type == "dpmsolver++"
    assert scheduler.config.use_karras_sigmas is True
