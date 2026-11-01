"""What the model is asked to return, and the tolerant parsing of what it actually returns."""

import json
import re

from pydantic import BaseModel, ValidationError, field_validator

FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class BadAnswer(Exception):
    """The model's answer is not usable (no JSON object, or the wrong shape)."""


def extract_json_object(text):
    """The first JSON object in ``text``. The old code took the *last* ``{`` and deleted every
    backslash and newline, which broke any answer with an escaped quote in its HTML. Here the
    text is decoded as JSON from each ``{`` in turn, so surrounding prose or a code fence is fine."""
    text = FENCE.sub("", (text or "").strip())
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise BadAnswer("no JSON object in the answer")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value)


class ShortContent(BaseModel):
    short_description: str
    categories: list[int] = []

    @field_validator("categories", mode="before")
    @classmethod
    def _ids(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        ids = []
        for item in value:
            if isinstance(item, bool) or item is None:
                continue
            try:
                ids.append(int(str(item).strip()))
            except ValueError:
                continue
        return ids


class LongContent(BaseModel):
    long_description: str
    seo_title: str = ""
    meta_description: str = ""
    focus_keyword: str = ""
    tags: list[str] = []

    @field_validator("seo_title", "meta_description", "focus_keyword", mode="before")
    @classmethod
    def _joined(cls, value):
        return _text(value).strip()

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.split(",")
        return [str(tag).strip() for tag in value if str(tag).strip()]


def parse(model, text):
    try:
        return model.model_validate(extract_json_object(text))
    except ValidationError as error:
        raise BadAnswer(
            f"the answer has the wrong shape: {error.error_count()} problem(s)"
        ) from error
