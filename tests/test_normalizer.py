from app.telegram.normalizer import normalize_text, strip_tracking_query, text_sha256


def test_normalize_text_keeps_ukrainian_and_removes_noise():
    text = "  ПрилЁт\u200b  біля Києва   https://x.test/a?utm_source=t&ok=1  "
    assert normalize_text(text) == "прилет біля києва https://x.test/a?ok=1"


def test_sha256_is_stable():
    assert text_sha256("abc") == text_sha256("abc")
    assert len(text_sha256("abc")) == 64


def test_strip_tracking_query():
    assert strip_tracking_query("https://e.test/a?utm_campaign=x&gclid=y&q=1") == "https://e.test/a?q=1"

