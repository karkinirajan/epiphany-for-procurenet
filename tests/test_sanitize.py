from epiphany.sanitize import clean_html


def test_allowed_markup_is_kept():
    html = "<p>Intro</p><ul><li><strong>Purity:</strong> 99%</li></ul><h2>Specs</h2>"
    assert clean_html(html) == html


def test_scripts_and_event_handlers_are_removed():
    out = clean_html(
        '<p onclick="steal()">Hi</p><script>alert(1)</script><img src=x onerror=alert(1)>'
    )
    assert (
        "script" not in out and "onclick" not in out and "onerror" not in out and "alert" not in out
    )
    assert "Hi" in out


def test_javascript_links_lose_their_href_and_real_links_get_rel():
    out = clean_html('<a href="javascript:evil()">bad</a> <a href="https://example.com/x">good</a>')
    assert "javascript" not in out
    assert 'href="https://example.com/x"' in out and 'rel="noopener noreferrer"' in out


def test_entity_escaped_html_is_restored_then_cleaned():
    """The model sometimes returns &lt;ul&gt;...; the old code unescaped it, without cleaning."""
    out = clean_html(
        "&lt;ul&gt;&lt;li&gt;A &amp;amp; B&lt;/li&gt;&lt;/ul&gt;&lt;script&gt;x()&lt;/script&gt;"
    )
    assert out.startswith("<ul><li>") and "script" not in out and "x()" not in out


def test_forms_iframes_and_style_attributes_are_removed():
    out = clean_html(
        '<form action="/x"><input></form><iframe src="//e"></iframe><p style="x">t</p>'
    )
    assert "<form" not in out and "<iframe" not in out and "style" not in out and "<p>t</p>" in out


def test_empty_input():
    assert clean_html("") == "" and clean_html(None) == ""
