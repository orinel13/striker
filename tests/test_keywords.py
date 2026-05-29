from app.nlp.keywords import find_keywords, keyword_score, load_keywords


def test_keywords_load_and_match():
    keywords = load_keywords("data/keywords.yml")
    matches = find_keywords("Шахед, вибух і пожежа", keywords)
    categories = {category for category, _ in matches}
    assert {"uav", "impact", "fire"} <= categories


def test_keyword_score_high_for_attack_and_impact():
    assert keyword_score("ракета удар пожар", has_place=True, has_time=True, has_media=True) > 0.7

