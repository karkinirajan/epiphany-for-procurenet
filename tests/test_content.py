import pytest

from epiphany.content import BadAnswer, LongContent, ShortContent, extract_json_object, parse


def test_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_a_code_fence_and_prose_around_the_object_are_ignored():
    assert extract_json_object('Sure! Here it is:\n```json\n{"a": 1}\n```\nAnything else?') == {
        "a": 1
    }


def test_escaped_quotes_and_newlines_inside_html_survive():
    """The old code deleted every backslash and newline first, which broke exactly this."""
    text = '{"short_description": "<p class=\\"x\\">line one\\nline two</p>"}'
    assert extract_json_object(text)["short_description"] == '<p class="x">line one\nline two</p>'


def test_braces_inside_strings_do_not_confuse_the_parser():
    assert extract_json_object('{"a": "x } y { z"}') == {"a": "x } y { z"}


def test_a_stray_brace_before_the_object_is_skipped():
    assert extract_json_object('note {not json} then {"a": 2}') == {"a": 2}


def test_the_first_valid_object_wins():
    assert extract_json_object('{"a": 1} {"a": 2}') == {"a": 1}


@pytest.mark.parametrize("text", ["", None, "no json here", "[1, 2]", "{broken", '"just a string"'])
def test_no_object_is_a_bad_answer(text):
    with pytest.raises(BadAnswer):
        extract_json_object(text)


def test_categories_are_coerced_to_integers():
    got = parse(
        ShortContent, '{"short_description": "x", "categories": ["12", 7, null, "x", true, " 9 "]}'
    )
    assert got.categories == [12, 7, 9]


@pytest.mark.parametrize(("raw", "expected"), [("5", [5]), (5, [5]), (None, []), ([], [])])
def test_a_single_category_or_none_is_accepted(raw, expected):
    import json

    assert (
        parse(ShortContent, json.dumps({"short_description": "x", "categories": raw})).categories
        == expected
    )


def test_missing_categories_default_to_none():
    assert parse(ShortContent, '{"short_description": "x"}').categories == []


def test_a_missing_description_is_a_bad_answer():
    with pytest.raises(BadAnswer):
        parse(ShortContent, '{"categories": [1]}')
    with pytest.raises(BadAnswer):
        parse(LongContent, '{"seo_title": "t"}')


def test_a_list_for_the_seo_title_is_joined_as_the_old_code_did():
    got = parse(
        LongContent,
        '{"long_description": "x", "seo_title": ["A", "B"], "focus_keyword": ["k1", "k2"]}',
    )
    assert (got.seo_title, got.focus_keyword) == ("A B", "k1 k2")


def test_tags_may_be_a_comma_separated_string_or_a_list():
    assert parse(LongContent, '{"long_description": "x", "tags": "a, b ,, c"}').tags == [
        "a",
        "b",
        "c",
    ]
    assert parse(LongContent, '{"long_description": "x", "tags": [" a ", "", "b"]}').tags == [
        "a",
        "b",
    ]
    assert parse(LongContent, '{"long_description": "x", "tags": null}').tags == []


def test_null_text_fields_become_empty_strings():
    got = parse(
        LongContent, '{"long_description": "x", "seo_title": null, "meta_description": null}'
    )
    assert got.seo_title == got.meta_description == got.focus_keyword == ""
