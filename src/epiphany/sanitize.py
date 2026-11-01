from html import unescape

import nh3

# What a product listing needs. Everything else (scripts, iframes, event handlers, style, forms,
# javascript: links) is removed: the HTML comes from a model that was given supplier-written text,
# and it is published on a live store.
TAGS = {
    "p", "br", "hr", "ul", "ol", "li", "strong", "b", "em", "i", "u", "sub", "sup",
    "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "th", "td", "a", "span", "div",
}  # fmt: skip
ATTRIBUTES = {"a": {"href", "title"}}
SCHEMES = {"http", "https", "mailto"}


def clean_html(text):
    """Unescape (the model sometimes returns ``&lt;ul&gt;``, which the old code also undid), then
    keep only the allowed markup."""
    if not text:
        return ""
    return nh3.clean(
        unescape(text),
        tags=TAGS,
        attributes=ATTRIBUTES,
        url_schemes=SCHEMES,
        link_rel="noopener noreferrer",
    ).strip()
