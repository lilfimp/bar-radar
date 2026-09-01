from src.enrichment.menu_validator import _keyword_hit_ratio


def test_keyword_ratio_high_for_real_menu_text():
    text = """
    Our cocktail menu features gin, vodka, rum and whisky based drinks,
    plus a curated wein and bier selection. Try our signature longdrink.
    """
    assert _keyword_hit_ratio(text) >= 0.65


def test_keyword_ratio_low_for_unrelated_text():
    text = "Welcome to our restaurant. We serve pizza, pasta and salads."
    assert _keyword_hit_ratio(text) < 0.35


def test_keyword_ratio_zero_for_empty_text():
    assert _keyword_hit_ratio("") == 0.0
