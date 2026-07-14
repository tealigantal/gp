import pytest

from gp_assistant.serenity.parser import build_verified_evidence
from gp_assistant.serenity.sources import CNInfoClient, SourceError


class _Response:
    def __init__(self, *, payload=None, content=b"", status=200, headers=None):
        self._payload = payload
        self.content = content
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.encoding = None

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, chunk_size=65536):
        yield self.content


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}

    def request(self, method, url, timeout=None, **kwargs):
        return self.responses.pop(0)


def _build(title: str, text: str):
    bound_text = f"证券代码：000001。{text}" if text else ""
    return build_verified_evidence(
        symbol="000001",
        title=title,
        text=bound_text,
        published_at="2026-07-10T00:00:00+08:00",
        effective_available_at="2026-07-10T15:00:00+08:00",
        source_document_id="serdoc_1",
        source_version_id="server_1",
        source_url="https://static.cninfo.com.cn/example.pdf",
        content_hash="a" * 64,
        source_verified=True,
        backfill_only=False,
    )


def test_numeric_earnings_guidance_produces_verified_positive_fact():
    facts, hypotheses = _build("2026年半年度业绩预告", "预计归属于股东的净利润同比增长 35% 至 50%。")
    assert len(facts) == 1
    assert facts[0].direction == 1
    assert facts[0].numeric_values["percent_values"] == [35.0, 50.0]
    assert hypotheses[0].status == "verified"


def test_correction_scope_is_limited_to_matching_event_family():
    facts, _ = _build(
        "2026年半年度业绩预告更正公告",
        "公司对前期业绩预告进行更正。",
    )
    assert facts[0].numeric_values["relation_type"] == "correction"
    assert facts[0].numeric_values["relation_fact_types"] == ["earnings_guidance"]
    assert facts[0].numeric_values["relation_target_keys"] == [
        "earnings_guidance:2026:H1"
    ]

    generic, _ = _build("董事会决议更正公告", "公司对董事会决议公告进行更正。")
    assert generic[0].numeric_values["relation_fact_types"] == []
    assert generic[0].numeric_values["relation_target_keys"] == []


def test_ambiguous_reference_is_neutral_and_textless_is_rejected():
    facts, _ = _build("关于股份回购进展的公告", "公司披露股份回购进展，具体影响仍需结合规模判断。")
    assert facts[0].direction == 0
    assert facts[0].fact_type == "reference_only"
    empty, hypotheses = _build("关于收到行政处罚的公告", "")
    assert empty == []
    assert hypotheses == []


def test_earnings_amount_without_percentage_is_not_promoted_to_directional_fact():
    facts, hypotheses = _build("2026年半年度业绩预告", "预计归属于股东的净利润为人民币3500万元。")
    assert facts == []
    assert hypotheses == []


def test_loss_narrowing_is_improvement_not_high_confidence_negative():
    facts, _ = _build(
        "2026年半年度业绩预告",
        "预计仍为亏损，但亏损同比收窄 35%。",
    )
    assert len(facts) == 1
    assert facts[0].direction == 1
    assert facts[0].confidence < 0.92
    assert facts[0].numeric_values["still_loss_making"] is True


def test_pdf_heading_can_route_when_cninfo_title_is_corrupted():
    facts, _ = build_verified_evidence(
        symbol="000001",
        title="���",
        text="证券代码000001。2026年半年度业绩预告。预计净利润同比增长35%。",
        published_at="2026-07-10T00:00:00+08:00",
        effective_available_at="2026-07-10T15:00:00+08:00",
        source_document_id="serdoc_pdf_heading",
        source_version_id="server_pdf_heading",
        source_url="https://static.cninfo.com.cn/example.pdf",
        content_hash="c" * 64,
        source_verified=True,
        backfill_only=False,
    )
    assert len(facts) == 1
    assert facts[0].direction == 1


def test_unverified_or_negated_documents_cannot_create_scored_facts():
    facts, _ = _build("关于未被立案调查的说明公告", "公司未被立案调查，也未收到行政处罚。")
    assert facts == []
    facts, _ = _build("重大诉讼进展公告", "相关案件已经胜诉并撤诉，不会产生重大不利影响。")
    assert facts == []
    facts, _ = _build(
        "股票交易异常波动公告",
        "公司前期披露的信息不存在需要更正、补充之处。",
    )
    assert facts == []

    facts, hypotheses = build_verified_evidence(
        symbol="000001",
        title="2026年半年度业绩预告",
        text="证券代码000001，预计净利润同比增长35%。",
        published_at="2026-07-10T00:00:00+08:00",
        effective_available_at="2026-07-10T15:00:00+08:00",
        source_document_id="serdoc_unverified",
        source_version_id="server_unverified",
        source_url="https://static.cninfo.com.cn/example.pdf",
        content_hash="b" * 64,
        source_verified=False,
        backfill_only=False,
    )
    assert facts[0].verification_state == "unverified"
    assert facts[0].source_quality == 0.0
    assert hypotheses[0].status == "unverified"


def test_cninfo_exact_symbol_paginates_and_detects_backlog():
    row1 = {"announcementId": "1", "secCode": "000001", "announcementTitle": "A", "announcementTime": 1_700_000_000_000, "adjunctUrl": "a.pdf"}
    row2 = {"announcementId": "2", "secCode": "000001", "announcementTitle": "B", "announcementTime": 1_700_000_100_000, "adjunctUrl": "b.pdf"}
    session = _Session(
        [
            _Response(payload={"announcements": [row1], "totalpages": 2, "hasMore": True}),
            _Response(payload={"announcements": [row2], "totalpages": 2, "hasMore": False}),
        ]
    )
    client = CNInfoClient(page_budget=2, spacing_sec=0, session=session)
    result = client.fetch_symbol("000001", "gssz0000001", start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 1, 31))
    assert result["complete"] is True
    assert [row["source_record_id"] for row in result["records"]] == ["1", "2"]

    limited = CNInfoClient(
        page_budget=1,
        spacing_sec=0,
        session=_Session([_Response(payload={"announcements": [row1], "totalpages": 2, "hasMore": True})]),
    )
    result = limited.fetch_symbol("000001", "gssz0000001", start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 1, 31))
    assert result["complete"] is False
    assert result["backlog"] is True


def test_cninfo_accepts_real_null_empty_result_as_complete_coverage():
    client = CNInfoClient(
        spacing_sec=0,
        session=_Session(
            [
                _Response(
                    payload={
                        "announcements": None,
                        "totalpages": 0,
                        "hasMore": False,
                    }
                )
            ]
        ),
    )

    result = client.fetch_symbol(
        "000001",
        "gssz0000001",
        start=__import__("datetime").date(2026, 1, 1),
        end=__import__("datetime").date(2026, 1, 31),
    )

    assert result == {
        "records": [],
        "complete": True,
        "backlog": False,
        "schema_fingerprint": None,
        "total_pages": 0,
        "next_page": None,
        "start_page": 1,
    }


def test_cninfo_429_is_structured():
    client = CNInfoClient(spacing_sec=0, session=_Session([_Response(status=429, headers={"Retry-After": "17"})]))
    with pytest.raises(SourceError) as caught:
        client.load_stock_map()
    assert caught.value.status_code == 429
    assert caught.value.retry_after == 17


def test_cninfo_rejects_partial_row_schema_before_cursor_can_advance():
    bad = {
        "announcementId": "1",
        "secCode": "000001",
        "announcementTitle": "业绩预告",
        "announcementTime": 1_700_000_000_000,
        "adjunctUrl": "",
    }
    client = CNInfoClient(
        page_budget=1,
        spacing_sec=0,
        session=_Session(
            [_Response(payload={"announcements": [bad], "totalpages": 1, "hasMore": False})]
        ),
    )
    with pytest.raises(SourceError, match="required_field_missing"):
        client.fetch_symbol(
            "000001",
            "gssz0000001",
            start=__import__("datetime").date(2026, 1, 1),
            end=__import__("datetime").date(2026, 1, 31),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"announcements": {}, "totalpages": 1},
        {"announcements": ["not-an-object"], "totalpages": 1},
    ],
)
def test_cninfo_rejects_invalid_announcement_container_and_rows(payload):
    client = CNInfoClient(
        spacing_sec=0,
        session=_Session([_Response(payload=payload)]),
    )
    with pytest.raises(SourceError) as caught:
        client.fetch_symbol(
            "000001",
            "gssz0000001",
            start=__import__("datetime").date(2026, 1, 1),
            end=__import__("datetime").date(2026, 1, 31),
        )
    assert caught.value.schema_error is True


@pytest.mark.parametrize("stock_list", [{}, ["not-an-object"]])
def test_cninfo_rejects_invalid_stock_map_container_and_rows(stock_list):
    client = CNInfoClient(
        spacing_sec=0,
        session=_Session([_Response(payload={"stockList": stock_list})]),
    )
    with pytest.raises(SourceError) as caught:
        client.load_stock_map()
    assert caught.value.schema_error is True


def test_schema_fingerprint_is_independent_of_rows_and_empty_results():
    row = {
        "announcementId": "1",
        "secCode": "000001",
        "announcementTitle": "业绩预告",
        "announcementTime": 1_700_000_000_000,
        "adjunctUrl": "a.pdf",
    }
    first = CNInfoClient(
        spacing_sec=0,
        session=_Session(
            [_Response(payload={"announcements": [row], "totalpages": 1})]
        ),
    ).fetch_symbol(
        "000001",
        "gssz0000001",
        start=__import__("datetime").date(2026, 1, 1),
        end=__import__("datetime").date(2026, 1, 31),
    )
    second = CNInfoClient(
        spacing_sec=0,
        session=_Session(
            [
                _Response(
                    payload={
                        "announcements": [{**row, "optionalNewField": "allowed"}],
                        "totalpages": 1,
                    }
                )
            ]
        ),
    ).fetch_symbol(
        "000001",
        "gssz0000001",
        start=__import__("datetime").date(2026, 1, 1),
        end=__import__("datetime").date(2026, 1, 31),
    )
    empty = CNInfoClient(
        spacing_sec=0,
        session=_Session(
            [_Response(payload={"announcements": [], "totalpages": 1})]
        ),
    ).fetch_symbol(
        "000001",
        "gssz0000001",
        start=__import__("datetime").date(2026, 1, 1),
        end=__import__("datetime").date(2026, 1, 31),
    )

    assert first["schema_fingerprint"] == second["schema_fingerprint"]
    assert empty["schema_fingerprint"] is None
