from __future__ import annotations

import io

from pypdf import PdfWriter

from gp_assistant.serenity.parser import (
    PdfParseResult,
    _evidence_signature,
    _extract_pdf_document_sync,
    _extract_text_layer_sync,
    _ocr_languages_available,
    _ocr_pixels_exceeded,
    _ocr_text_validation_state,
    supported_title_family,
)


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_generic_legal_revision_is_filtered_but_earnings_revision_is_relevant():
    assert supported_title_family("关于发行股份购买资产的补充法律意见书（二）（修订稿）") is None
    assert supported_title_family("2026年半年度业绩预告修订公告") == "earnings_guidance"


def test_only_structurally_valid_zero_text_pdf_enters_ocr(monkeypatch):
    called = []

    def fake_ocr(*_args, **_kwargs):
        called.append(True)
        return PdfParseResult("证券代码000001，业绩预告。" + "有效文字" * 60, "parsed", "tesseract_ocr", ocr_confidence=90.0)

    monkeypatch.setattr("gp_assistant.serenity.parser._ocr_pdf_sync", fake_ocr)
    result = _extract_pdf_document_sync(
        _blank_pdf(), symbol="000001", title="2026年半年度业绩预告", max_pages=40,
        max_chars=250_000, primary_dpi=200, verify_dpi=300,
        max_page_pixels=20_000_000, max_total_pixels=160_000_000, page_timeout_sec=8.0,
    )
    assert result.state == "parsed"
    assert called == [True]

    called.clear()
    corrupt = _extract_pdf_document_sync(
        b"not-a-pdf", symbol="000001", title="2026年半年度业绩预告", max_pages=40,
        max_chars=250_000, primary_dpi=200, verify_dpi=300,
        max_page_pixels=20_000_000, max_total_pixels=160_000_000, page_timeout_sec=8.0,
    )
    assert corrupt.state == "unparsed"
    assert called == []


def test_page_limit_is_rejected_before_ocr(monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    output = io.BytesIO()
    writer.write(output)
    monkeypatch.setattr("gp_assistant.serenity.parser._ocr_pdf_sync", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("OCR must not run")))
    result = _extract_text_layer_sync(output.getvalue(), max_pages=1, max_chars=250_000)
    assert result.state == "page_limit"


def test_ocr_identity_topic_confidence_language_and_pixel_gates():
    valid = "证券代码000001。2026年半年度业绩预告，预计归属于股东的净利润同比增长35%。" + "公司说明" * 60
    assert _ocr_text_validation_state(symbol="000001", family="earnings_guidance", text=valid, median_confidence=80.0) is None
    assert _ocr_text_validation_state(symbol="600000", family="earnings_guidance", text=valid, median_confidence=80.0) == "ocr_symbol_mismatch"
    assert _ocr_text_validation_state(symbol="000001", family="major_litigation", text=valid, median_confidence=80.0) == "ocr_topic_mismatch"
    assert _ocr_text_validation_state(symbol="000001", family="earnings_guidance", text=valid, median_confidence=59.9) == "ocr_low_confidence"
    assert _ocr_languages_available({"chi_sim", "eng"}) is True
    assert _ocr_languages_available({"eng"}) is False
    assert _ocr_pixels_exceeded(page_pixels=20_000_001, total_pixels=20_000_001, max_page_pixels=20_000_000, max_total_pixels=160_000_000) is True
    assert _ocr_pixels_exceeded(page_pixels=10_000_000, total_pixels=160_000_001, max_page_pixels=20_000_000, max_total_pixels=160_000_000) is True


def test_ocr_validation_tolerates_spaces_inserted_between_chinese_characters():
    text = "证券代码 000001 业 绩 预 告 净 利 润 增 长 35 % " + ("经营情况稳定 " * 50)

    assert _ocr_text_validation_state(symbol="000001", family="earnings_guidance", text=text, median_confidence=90.0) is None
    assert _evidence_signature("2026年半年度业绩预告", "earnings_guidance", text) == (1, (35.0,))


def test_directional_percent_signature_requires_exact_second_pass_match():
    title = "2026年半年度业绩预告"
    primary = _evidence_signature(title, "earnings_guidance", "预计净利润同比增长35%至50%。")
    matching = _evidence_signature(title, "earnings_guidance", "净利润增长35%至50%。")
    disagreement = _evidence_signature(title, "earnings_guidance", "净利润增长36%至50%。")
    assert primary == (1, (35.0, 50.0))
    assert matching == primary
    assert disagreement != primary
