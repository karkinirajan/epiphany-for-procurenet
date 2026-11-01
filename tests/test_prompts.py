from epiphany.prompts import SYSTEM, long_description_prompt, short_description_prompt


def test_the_short_prompt_carries_the_product_the_base_text_and_the_categories():
    text = short_description_prompt("Acetone", "A solvent.", "10: Solvents, 11: Acids")
    assert "for product 'Acetone'" in text
    assert "base description: 'A solvent.'" in text
    assert "10: Solvents, 11: Acids" in text
    assert '"short_description", "categories"' in text and "up to three categories" in text


def test_the_long_prompt_carries_the_product_and_the_base_text():
    text = long_description_prompt("Acetone", "Old long text.")
    assert "'Old long text.'" in text and "for 'Acetone'" in text
    for key in ("long_description", "seo_title", "meta_description", "focus_keyword", "tags"):
        assert f'"{key}"' in text
    assert "under 155 characters" in text


def test_paragraph_breaks_are_real_newlines_not_the_letters_nn():
    """The old code JSON-encoded the prompt and then deleted every backslash: "\\n\\n" became "nn"."""
    text = long_description_prompt("Acetone", "x")
    assert "Drug Interactions.\n\nFor other products" in text
    assert "Interactions.nn" not in text and "\\n" not in text


def test_the_prompts_are_plain_text_not_json():
    assert not short_description_prompt("t", "d", "c").startswith("{")
    assert not long_description_prompt("t", "d").startswith("{")
    assert SYSTEM == "You are a helpful assistant."
