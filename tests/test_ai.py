import types

import pytest

from epiphany.ai import ContentGenerator, GenerationError
from epiphany.prompts import SYSTEM, long_description_prompt, short_description_prompt


class FakeOpenAI:
    """Answers with the given texts in turn (the last one repeats)."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.answers[min(len(self.calls), len(self.answers)) - 1]
        choices = (
            []
            if text is None
            else [types.SimpleNamespace(message=types.SimpleNamespace(content=text))]
        )
        return types.SimpleNamespace(choices=choices)


GOOD_SHORT = '{"short_description": "<ul><li>a</li></ul>", "categories": [10, "11"]}'
GOOD_LONG = '{"long_description": "<p>l</p>", "seo_title": "T", "meta_description": "M", "focus_keyword": "K", "tags": ["a"]}'


async def test_short_description_sends_the_system_and_user_messages_and_the_model():
    client = FakeOpenAI(GOOD_SHORT)
    result = await ContentGenerator(client, "demo-model").short(
        "Acetone", "A solvent.", "10: Solvents"
    )
    assert result.short_description == "<ul><li>a</li></ul>" and result.categories == [10, 11]
    call = client.calls[0]
    assert call["model"] == "demo-model"
    assert call["messages"][0] == {"role": "system", "content": SYSTEM}
    # exactly the prompt, as plain text (the old code sent it JSON-wrapped and stripped of backslashes)
    assert call["messages"][1] == {
        "role": "user",
        "content": short_description_prompt("Acetone", "A solvent.", "10: Solvents"),
    }


async def test_the_long_prompt_is_sent_as_it_is_too():
    client = FakeOpenAI(GOOD_LONG)
    await ContentGenerator(client, "m").long("Acetone", "old text")
    assert client.calls[0]["messages"][1] == {
        "role": "user",
        "content": long_description_prompt("Acetone", "old text"),
    }


async def test_long_description_is_parsed_into_all_its_fields():
    result = await ContentGenerator(FakeOpenAI(GOOD_LONG), "m").long("Acetone", "old")
    assert (result.long_description, result.seo_title, result.meta_description) == (
        "<p>l</p>",
        "T",
        "M",
    )
    assert (result.focus_keyword, result.tags) == ("K", ["a"])


async def test_an_unusable_answer_is_asked_again():
    client = FakeOpenAI("I cannot do that.", GOOD_SHORT)
    result = await ContentGenerator(client, "m", attempts=2).short("t", "d", "c")
    assert result.short_description and len(client.calls) == 2


async def test_it_gives_up_after_the_configured_attempts():
    client = FakeOpenAI("nope")
    with pytest.raises(GenerationError, match="short description"):
        await ContentGenerator(client, "m", attempts=3).short("t", "d", "c")
    assert len(client.calls) == 3


async def test_an_answer_without_choices_counts_as_unusable():
    client = FakeOpenAI(None, GOOD_LONG)
    assert (await ContentGenerator(client, "m", attempts=2).long("t", "d")).seo_title == "T"


async def test_at_least_one_attempt_is_made():
    client = FakeOpenAI(GOOD_SHORT)
    assert (await ContentGenerator(client, "m", attempts=0).short("t", "d", "c")).short_description
    assert len(client.calls) == 1
