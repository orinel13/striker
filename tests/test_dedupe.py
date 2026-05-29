from app.nlp.dedupe import DedupeCandidate, find_canonical


def test_exact_hash_duplicate():
    existing = [DedupeCandidate(id=1, text_hash="a", normalized_text="ракета удар")]
    assert find_canonical(DedupeCandidate(id=2, text_hash="a", normalized_text="other"), existing) == 1


def test_tme_duplicate():
    existing = [DedupeCandidate(id=1, text_hash="a", normalized_text="x", url="https://t.me/test/10")]
    candidate = DedupeCandidate(id=2, text_hash="b", normalized_text="y", url="https://t.me/s/test/10")
    assert find_canonical(candidate, existing) == 1


def test_fuzzy_duplicate():
    existing = [DedupeCandidate(id=1, text_hash="a", normalized_text="ракета удар по місту пожежа")]
    candidate = DedupeCandidate(id=2, text_hash="b", normalized_text="ракета удар по місту пожежа!")
    assert find_canonical(candidate, existing) == 1

