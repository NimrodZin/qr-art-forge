"""m2-9b: unreadable or purged style reference shows a clear re-upload message.
Rows refer to steps/m2-9b/spec.md §2. CPU only; generation is never run."""
import asyncio
import gc
import traceback
import types
import weakref

import gradio as gr
import gradio.utils
import pytest
from gradio.data_classes import ImageData
from gradio.state_holder import SessionState
from PIL import Image, UnidentifiedImageError

import app

REF_LABEL = "Style reference image (optional)"
SVG_MESSAGE = "SVG files are not supported as input images for this app."
AVIF_BYTES = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 64
SIZE = (37, 23)
PIXELS = bytes(i % 251 for i in range(SIZE[0] * SIZE[1] * 3))


def make_payload(path, name):
    return {"path": str(path), "orig_name": name, "meta": {"_type": "gradio.FileData"}}


def image_data(path, name):
    return ImageData(**make_payload(path, name))


def make_inputs(ref):
    return ["example.com", "p", 1, 1.35, 25, 7, False, 1, "", ref, 0.5, "None"]


def save_image(path):
    Image.frombytes("RGB", SIZE, PIXELS).save(path)
    return path


@pytest.fixture(autouse=True)
def gradio_cache(monkeypatch, tmp_path):
    """Blocks read the cache dir when built; keep test copies out of the real Gradio cache."""
    cache = tmp_path / "gradio_cache"
    monkeypatch.setenv("GRADIO_TEMP_DIR", str(cache))
    return cache


@pytest.fixture
def ui():
    demo = app.build_ui()
    (btn,) = [b for b in demo.blocks.values() if isinstance(b, gr.Button) and b.value == "Forge"]
    (dep,) = [f for f in demo.fns.values() if (btn._id, "click") in f.targets]
    return types.SimpleNamespace(demo=demo, dep=dep, ref=dep.inputs[9])


@pytest.fixture
def avif(tmp_path):
    path = tmp_path / "ref.avif"
    path.write_bytes(AVIF_BYTES)
    return path


@pytest.fixture
def png(tmp_path):
    return save_image(tmp_path / "ref.png")


@pytest.fixture
def jpg(tmp_path):
    return save_image(tmp_path / "ref.jpg")


@pytest.fixture
def purged(tmp_path):
    return tmp_path / "purged" / "ref.png"


@pytest.fixture
def recorder(monkeypatch):
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return [], "report", None

    monkeypatch.setattr(app, "run_forge", record)
    return calls


def preprocess_data(ui, ref):
    return asyncio.run(ui.demo.preprocess_data(ui.dep, make_inputs(ref), None))


def process_api(ui, ref):
    return asyncio.run(ui.demo.process_api(ui.dep, make_inputs(ref), state=SessionState(ui.demo)))


def raiser(exc):
    def original(payload):
        raise exc
    return original


# ---------------------------------------------------------------- the component (rows 1-6)
def test_avif_shows_reference_error(ui, avif):  # row 1
    with pytest.raises(gr.Error) as e:
        ui.ref.preprocess(image_data(avif, "ref.avif"))
    assert e.value.message == app.REF_ERROR


def test_purged_upload_shows_reference_error(ui, purged):  # row 2
    with pytest.raises(gr.Error) as e:
        ui.ref.preprocess(image_data(purged, "ref.png"))
    assert e.value.message == app.REF_ERROR


def test_png_truncated_in_header_shows_reference_error(ui, png):  # row 3
    png.write_bytes(png.read_bytes()[:40])
    with pytest.raises(gr.Error) as e:
        ui.ref.preprocess(image_data(png, "ref.png"))
    assert e.value.message == app.REF_ERROR


def test_png_truncated_in_pixels_shows_reference_error(ui, png):  # row 3, fails on load, not open
    data = png.read_bytes()
    png.write_bytes(data[:len(data) // 2])
    Image.open(png).close()  # the header still opens, so this reaches the pixel load
    with pytest.raises(gr.Error) as e:
        ui.ref.preprocess(image_data(png, "ref.png"))
    assert e.value.message == app.REF_ERROR


def test_decompression_bomb_shows_reference_error(ui, png, monkeypatch):  # row 4
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(gr.Error) as e:
        ui.ref.preprocess(image_data(png, "ref.png"))
    assert e.value.message == app.REF_ERROR


def _caught_errors(ui, avif, purged):
    errors = []
    for path, name in ((avif, "ref.avif"), (purged, "ref.png")):
        with pytest.raises(gr.Error) as e:
            ui.ref.preprocess(image_data(path, name))
        errors.append(e.value)
    return errors


def test_error_keeps_upload_path_out_of_message(ui, avif, purged, tmp_path):  # row 5
    for err in _caught_errors(ui, avif, purged):
        assert err.print_exception is False
        assert "ref.avif" not in err.message
        assert "ref.png" not in err.message
        assert str(tmp_path) not in err.message


def test_error_keeps_upload_path_out_of_traceback(ui, avif, purged, tmp_path):  # row 5, `from None`
    for err in _caught_errors(ui, avif, purged):
        printed = "".join(traceback.format_exception(err))
        assert "ref.avif" not in printed
        assert str(tmp_path) not in printed


def test_reference_error_wording():  # row 6
    for word in ("re-upload", "PNG", "JPG"):
        assert word in app.REF_ERROR


# ---------------------------------------------------------------- the real Gradio path (rows 7-11)
def test_gradio_preprocess_avif_shows_reference_error(ui, avif):  # row 7
    with pytest.raises(gr.Error) as e:
        preprocess_data(ui, make_payload(avif, "ref.avif"))
    assert e.value.message == app.REF_ERROR


def test_gradio_preprocess_purged_shows_reference_error(ui, purged):  # row 8
    with pytest.raises(gr.Error) as e:
        preprocess_data(ui, make_payload(purged, "ref.png"))
    assert e.value.message == app.REF_ERROR


def test_gradio_preprocess_purged_from_cache_shows_reference_error(ui):  # row 8, as delete_cache leaves it
    gone = f"{ui.ref.GRADIO_CACHE}/0123456789abcdef/ref.png"
    with pytest.raises(gr.Error) as e:
        preprocess_data(ui, make_payload(gone, "ref.png"))
    assert e.value.message == app.REF_ERROR


def test_error_payload_shows_message_with_show_error_off(ui, avif):  # row 9
    with pytest.raises(gr.Error) as e:
        preprocess_data(ui, make_payload(avif, "ref.avif"))
    assert gradio.utils.error_payload(e.value, False)["error"] == app.REF_ERROR


def test_avif_never_reaches_generation(ui, avif, recorder):  # row 10
    with pytest.raises(gr.Error) as e:
        process_api(ui, make_payload(avif, "ref.avif"))
    assert e.value.message == app.REF_ERROR
    assert recorder == []


def test_purged_never_reaches_generation(ui, purged, recorder):  # row 11
    with pytest.raises(gr.Error) as e:
        process_api(ui, make_payload(purged, "ref.png"))
    assert e.value.message == app.REF_ERROR
    assert recorder == []


def test_no_reference_reaches_generation_unchanged(ui, recorder):  # guard: rows 10-11 are not vacuous
    process_api(ui, None)
    assert len(recorder) == 1
    args, kwargs = recorder[0]
    assert args[:2] == ("example.com", "p")
    assert kwargs["reference"] is None
    assert kwargs["reference_scale"] == 0.5


def test_readable_reference_reaches_generation(ui, png, recorder):  # guard: rows 10-11 are not vacuous
    process_api(ui, make_payload(png, "ref.png"))
    assert len(recorder) == 1
    reference = recorder[0][1]["reference"]
    assert isinstance(reference, Image.Image)
    assert reference.size == SIZE


# ---------------------------------------------------------------- no reference, readable reference (rows 12-16)
def test_no_reference_returns_none(ui):  # row 12
    assert ui.ref.preprocess(None) is None


def test_gradio_preprocess_no_reference(ui):  # row 13
    processed = preprocess_data(ui, None)
    assert processed[9] is None
    assert processed[10] == 0.5


@pytest.mark.parametrize("fixture, name", [("png", "ref.png"), ("jpg", "ref.jpg")])
def test_readable_reference_returns_image(ui, request, fixture, name):  # row 14
    im = ui.ref.preprocess(image_data(request.getfixturevalue(fixture), name))
    assert isinstance(im, Image.Image)
    assert im.mode == "RGB"
    assert im.size == SIZE


def test_readable_reference_pixels_match_plain_component(ui, png):  # row 15
    wrapped = ui.ref.preprocess(image_data(png, "ref.png"))
    plain = gr.Image(type="pil").preprocess(image_data(png, "ref.png"))
    assert wrapped.tobytes() == plain.tobytes()


def test_gradio_preprocess_readable_reference(ui, png):  # row 16
    processed = preprocess_data(ui, make_payload(png, "ref.png"))
    assert isinstance(processed[9], Image.Image)
    assert processed[9].size == SIZE


# ---------------------------------------------------------------- what must not be remapped (rows 17-19)
def test_svg_keeps_gradio_message(ui, tmp_path):  # row 17
    svg = tmp_path / "x.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    with pytest.raises(gr.Error) as e:
        ui.ref.preprocess(image_data(svg, "x.svg"))
    assert e.value.message == SVG_MESSAGE


def test_missing_path_keeps_value_error(ui):  # row 18
    with pytest.raises(ValueError) as e:
        ui.ref.preprocess(ImageData(path=None))
    assert not isinstance(e.value, gr.Error)
    assert str(e.value) == "Image path is None."


def test_unrelated_error_propagates_unchanged():  # row 19
    with pytest.raises(RuntimeError, match="^x$") as e:
        app.reference_preprocess(lambda p: (_ for _ in ()).throw(RuntimeError("x")))(None)
    assert type(e.value) is RuntimeError


@pytest.mark.parametrize("exc", [
    UnidentifiedImageError("cannot identify image file"),
    FileNotFoundError("no such file"),
    OSError("image file is truncated"),
    SyntaxError("broken PNG file"),
    Image.DecompressionBombError("too many pixels"),
])
def test_wrapper_maps_the_named_upload_errors(exc):  # §1 edit 2, the caught types
    with pytest.raises(gr.Error) as e:
        app.reference_preprocess(raiser(exc))(None)
    assert e.value.message == app.REF_ERROR
    assert e.value.print_exception is False


# ---------------------------------------------------------------- P6 and the component itself (rows 20-22)
def test_wrapper_keeps_no_image(ui, png):  # row 20
    im = ui.ref.preprocess(image_data(png, "ref.png"))
    wr = weakref.ref(im)
    del im
    gc.collect()
    assert wr() is None


def test_component_is_still_a_plain_image(ui):  # row 21
    assert type(ui.ref) is gr.Image
    assert ui.ref.get_block_name() == "image"
    assert ui.ref.type == "pil"
    ui.demo.get_api_info()


def test_wrapper_is_on_this_component_only(ui, avif):  # §1, instance wrapper, not a class patch
    with pytest.raises(UnidentifiedImageError):
        gr.Image(type="pil").preprocess(image_data(avif, "ref.avif"))


def test_component_config_matches_plain_image(ui):  # row 22
    plain = gr.Image(label=REF_LABEL, type="pil", sources=["upload"], height=160)
    wrapped_config, plain_config = ui.ref.get_config(), plain.get_config()
    for key in ("type", "sources", "label", "height", "image_mode"):
        assert wrapped_config[key] == plain_config[key]
