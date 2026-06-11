from app.services.extraction import ExtractionStats, route_decision


def test_route_text_when_chars_dense_and_no_images():
    """Text-layer PDFs with low image area should route to the text lane."""
    stats = ExtractionStats(text="x" * 1000, pages=2, chars_per_page=500.0, image_area_ratio=0.1)
    assert route_decision(stats) == "text"


def test_route_ocr_when_chars_sparse():
    """Scanned-style PDFs with sparse text should route to the OCR lane."""
    stats = ExtractionStats(text="", pages=2, chars_per_page=10.0, image_area_ratio=0.0)
    assert route_decision(stats) == "ocr"


def test_route_vision_when_image_area_huge():
    """Text-layer PDFs with image-as-resume should route to the vision lane."""
    stats = ExtractionStats(text="x" * 1000, pages=1, chars_per_page=500.0, image_area_ratio=0.9)
    assert route_decision(stats) == "vision"
