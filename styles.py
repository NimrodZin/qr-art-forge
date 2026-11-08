"""Style presets (OD 14, order B): a prompt suffix, negative suffix and QR strength per style.
Pure table and lookups; no generation, no UI. See docs/04_Build_Plan.md:41."""
from typing import NamedTuple

STYLE_NONE = "None"
STYLE_NEGATIVE = "text, letters, words, watermark, signature"


class Style(NamedTuple):
    prompt_suffix: str
    negative_suffix: str
    strength: float


STYLES = {
    "Mosaic": Style(
        prompt_suffix=("as an ancient Roman floor mosaic, small square marble and lapis "
                       "tesserae, irregular grout, soft daylight, photographed from directly above"),
        negative_suffix=STYLE_NEGATIVE,
        strength=1.35),
    "Rug": Style(
        prompt_suffix=("woven into a hand-knotted wool rug, dense pile, natural dyes, "
                       "geometric border, photographed from directly above"),
        negative_suffix=STYLE_NEGATIVE,
        strength=1.35),
    "Embroidery": Style(
        prompt_suffix=("as hand embroidery on natural linen, french knots and satin stitch, "
                       "colourful silk threads, macro photograph, front view"),
        negative_suffix=STYLE_NEGATIVE,
        strength=1.35),
}
STYLE_CHOICES = [STYLE_NONE, *STYLES]


def apply_style(name: str | None, prompt: str, negative: str | None) -> tuple:
    """Pure: (effective prompt, effective negative). None style passes prompt and negative
    through untouched (same objects), so default generation stays byte-identical."""
    if name is None or name == STYLE_NONE:
        return prompt, negative
    style = STYLES[name]
    effective_prompt = prompt + ", " + style.prompt_suffix
    if negative is None or not negative.strip():
        effective_negative = style.negative_suffix
    else:
        effective_negative = negative.strip() + ", " + style.negative_suffix
    return effective_prompt, effective_negative


def style_strength(name: str | None) -> float | None:
    """Reads STYLES at call time. None style (or Python None) has no strength to set."""
    if name is None or name == STYLE_NONE:
        return None
    return STYLES[name].strength
