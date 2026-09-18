from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from gp_assistant.application.official_suspension import OfficialSuspensionEvidenceCollector
from gp_assistant.application.suspension_facts import parse_status_facts
from gp_assistant.serenity.sources import ExchangeVerifier


# Short text-layer excerpts from the actual official PDFs, captured 2026-09-18.
# These are parser regressions, not price data or provider-empty evidence.
XINHUA = (
    "公司股票（证券简称：新华传媒，证券代码：600825）自2026年9月7日（星期一）开市起停牌，"
    "并于2026年9月8日（星期二）开市起继续停牌，预计停牌（累计）时间不超过10个交易日。"
    "公司股票将继续停牌，待上述事项确定后，公司将及时披露相关公告并申请公司股票复牌。"
)
CICC = (
    "公司A股股票将自2026年9月15日2（即A股异议股东收购请求权申报首日）开市起连续停牌，"
    "并将于刊登A股异议股东收购请求权申报结果公告当日复牌。"
)
INTERVAL = "申报期间：2026年9月15日至2026年9月17日。申报期间公司A股股票停牌。"
ALICE = "本公司股票将于2026年8月3日（星期一）开市起停牌，自披露核查公告后复牌。"


def test_condition_bound_halt_real_notice_and_chronology(suspension_calendar):
    # Actual 1225452030 PDF, page 1, published 2026-08-01. This is
    # retrospective parser evidence, not a point-in-time price backtest.
    halt = record("1225452030", symbol="603221", text=ALICE, published="2026-08-01T00:00:00+08:00")
    older_unreadable = record("1225439758", symbol="603221", title="股东会法律意见书",
                              text="", state="unparsed", published="2026-07-24T00:00:00+08:00")
    result = resolve([halt, older_unreadable], suspension_calendar, date(2026, 8, 4))
    evidence = result.evidence_by_symbol["603221"]
    assert evidence["elapsed_sessions"] == 2
    assert evidence["policy_revision"] == "official-suspension.v3"
    assert evidence["status_fact"]["resumption_condition"] == "自披露核查公告后复牌"
    assert evidence["status_fact"]["ends_on"] is None
    assert effective(ALICE, date(2026, 8, 7), suspension_calendar)
    assert not effective(ALICE, date(2026, 8, 10), suspension_calendar)
    resume = record("resume", symbol="603221", title="核查完成及复牌公告",
                    text="本公司股票自2026年8月4日起复牌。", published="2026-08-04T00:00:00+08:00")
    assert not resolve([halt, resume], suspension_calendar, date(2026, 8, 4)).evidence_by_symbol
    unresolved = dict(resume, _text="", _state="unparsed")
    assert not resolve([halt, unresolved], suspension_calendar, date(2026, 8, 4)).evidence_by_symbol
    outcome = record("outcome", symbol="603221", title="股票交易异常波动核查结果公告",
                     text="本公司已完成相关核查，不存在应披露而未披露的重大事项。",
                     published="2026-08-04T00:00:00+08:00")
    conflict = resolve([halt, outcome], suspension_calendar, date(2026, 8, 4))
    assert not conflict.evidence_by_symbol
    assert conflict.diagnostics_by_symbol["603221"]["reason"] == "resumption_condition_may_be_fulfilled"
    assert conflict.diagnostics_by_symbol["603221"]["conflicting_record_ids"] == ["outcome"]
    ancillary_trigger = dict(outcome, title="专项核查报告书", _text="", _state="page_limit")
    assert not resolve([halt, ancillary_trigger], suspension_calendar, date(2026, 8, 4)).evidence_by_symbol
    earlier = dict(outcome, published_at="2026-07-31T00:00:00+08:00")
    assert resolve([halt, earlier], suspension_calendar, date(2026, 8, 4)).evidence_by_symbol
    # A fresh explicit halt in the result notice is new evidence, not an
    # indefinite extension of the old condition.
    ongoing = dict(outcome, _text="公司股票自2026年8月4日开市起停牌。")
    assert resolve([halt, ongoing], suspension_calendar, date(2026, 8, 4)).evidence_by_symbol["603221"]["source_record_id"] == "outcome"


@pytest.mark.parametrize("text", [
    ALICE.replace("将于", "拟于"),
    ALICE.replace("本公司", "其他公司"),
    ALICE.replace("停牌，", "停牌1天，"),
    ALICE.replace("，自披露", "。自披露"),
    ALICE.replace("，自披露", "，其他公司自披露"),
    ALICE.replace("后复牌", "后可能复牌"),
    ALICE.replace("后复牌", "后复牌的申请未获批准"),
    "本公司股票将于2026年8月3日开市起停牌。市场预计披露核查公告后复牌。",
])
def test_conditional_resume_does_not_extend_unbound_halts(suspension_calendar, text):
    assert not effective(text, date(2026, 8, 4), suspension_calendar)


def record(key="halt", *, symbol="601995", title="关于A股股票停牌的公告",
           published="2026-09-08T00:00:00+08:00", text=CICC, state="parsed"):
    return {"symbol": symbol, "title": title, "published_at": published,
            "source_record_id": key, "source_url": f"https://static.cninfo.com.cn/finalpage/2026-09-08/{key}.PDF",
            "_text": text, "_state": state}


class Client:
    def __init__(self, records, *, complete=True):
        self.records = records
        self.complete = complete
        self.calls = []

    def load_stock_map(self):
        return {r["symbol"]: {"org_id": "fixture"} for r in self.records}

    def fetch_symbol(self, symbol, _org, *, start, end):
        self.calls.append((start, end))
        return {"complete": self.complete, "backlog": not self.complete,
                "records": [r for r in self.records if r["symbol"] == symbol]}

    def download_pdf(self, url, **_kwargs):
        return url.encode()

    def parse(self, value, **kwargs):
        assert kwargs["max_pages"] == 40  # Do not fix relevance by raising caps.
        row = next(r for r in self.records if r["source_url"] == value.decode())
        return row["_text"], row["_state"]


class Verifier:
    def verify(self, *_args, **_kwargs):
        return True


def resolve(records, calendar, target=date(2026, 9, 18), **kwargs):
    client = Client(records)
    collector = OfficialSuspensionEvidenceCollector(client=client, verifier=Verifier(),
                                                    parser=client.parse, calendar=calendar, **kwargs)
    return collector.resolve(symbols=tuple({r["symbol"] for r in records}), trade_date=target,
                             observed_at=datetime(2026, 9, 18, 10, tzinfo=timezone.utc))


def effective(text, target, calendar):
    return [f for f in parse_status_facts(text) if f.validity(target, calendar) == "effective"]


def test_real_announcements_and_unrelated_long_reports(suspension_calendar):
    rows = [
        record("1225559328", symbol="600825", title="停牌进展公告", published="2026-09-12T00:00:00+08:00", text=XINHUA),
        record("1225552493"),
        record("1225552499", title="换股吸收合并暨关联交易报告书", text="", state="page_limit"),  # 497 pages
        record("1225552496", title="独立财务顾问报告", text="", state="page_limit"),  # 399 pages
        record("1225552495", title="换股吸收合并报告书摘要", text="", state="page_limit"),  # 87 pages
        record("1225567560", title="收购请求权第三次提示性公告", published="2026-09-17T00:00:00+08:00", text=INTERVAL),
    ]
    result = resolve(rows, suspension_calendar)
    assert set(result.evidence_by_symbol) == {"600825", "601995"}
    first = result.evidence_by_symbol["600825"]
    assert first["elapsed_sessions"] == 10
    assert first["status_fact"]["starts_on"] == "2026-09-07"
    assert first["status_fact"]["session_limit"] == 10
    assert first["calendar"]["revision"] == "suspension-fixture"
    second = result.evidence_by_symbol["601995"]
    assert second["source_record_id"] == "1225552493" and second["elapsed_sessions"] == 4
    failures = [d for d in result.diagnostics_by_symbol["601995"]["documents"] if d["reason"] == "parse_page_limit"]
    assert len(failures) == 3 and all(not d["blocking"] for d in failures)
    # Cumulative maximum may not restart on the second 'continue' date.
    assert "600825" not in resolve(rows, suspension_calendar, date(2026, 9, 21)).evidence_by_symbol


def test_calendar_session_boundaries_and_discovery(suspension_calendar):
    holiday = "公司股票自2026年9月28日开市起连续停牌，刊登结果公告当日复牌。"
    assert effective(holiday, date(2026, 10, 9), suspension_calendar)[0].session_limit == 5
    assert not effective(holiday, date(2026, 10, 12), suspension_calendar)
    client = Client([record(text=holiday, published="2026-09-27T00:00:00+08:00")])
    collector = OfficialSuspensionEvidenceCollector(client=client, verifier=Verifier(), parser=client.parse,
                                                    calendar=suspension_calendar)
    result = collector.resolve(symbols=("601995",), trade_date=date(2026, 10, 9), observed_at=datetime.now(timezone.utc))
    assert result.evidence_by_symbol
    assert client.calls == [(date(2026, 9, 18), date(2026, 10, 9))]
    assert not effective(INTERVAL, date(2026, 9, 18), suspension_calendar)
    assert effective(INTERVAL, date(2026, 9, 17), suspension_calendar)[0].kind == "explicit_halt_interval"


@pytest.mark.parametrize("title", ["关于复牌的公告", "报告书更正公告", "报告书（修订稿）", "报告书（更新稿）", "未识别公告类别"])
@pytest.mark.parametrize("state", ["page_limit", "zero_text", "unparsed"])
def test_relevant_or_unknown_unreadable_document_still_blocks(suspension_calendar, title, state):
    result = resolve([record(), record("later", title=title, text="", state=state)], suspension_calendar)
    assert not result.evidence_by_symbol
    assert result.diagnostics_by_symbol["601995"]["reason"] == "unresolved_status_disclosure"


@pytest.mark.parametrize("resume", [
    "公司股票自2026年9月17日开市起恢复交易。",
    "公司股票自2026年9月16日起复牌。",
    "公司股票将于2026年9月18日开市起复牌。",
    "经申请批准公司股票自2026年9月18日开市起复牌。",
])
def test_parsed_resume_conflicts_even_without_status_title(suspension_calendar, resume):
    result = resolve([record(), record("resume", title="申报实施公告", text=resume)], suspension_calendar)
    assert not result.evidence_by_symbol
    assert result.diagnostics_by_symbol["601995"]["reason"] == "effective_resumption_conflict"


@pytest.mark.parametrize("resume", [
    "此前预计2026年9月18日开市起复牌。",
    "公司股票预计无法在2026年9月18日开市起复牌。",
    "待刊登申报结果公告当日复牌。",
    "公司股票自2026年9月14日起复牌。",  # Before this new suspension started.
    "公司股票将于2026年9月21日开市起复牌。",  # Not effective on target.
])
def test_non_effective_resumption_is_not_a_conflict(suspension_calendar, resume):
    assert resolve([record(), record("other", title="申报实施公告", text=resume)], suspension_calendar).evidence_by_symbol


def test_newer_halt_supersedes_old_unknown_but_not_effective_resume(suspension_calendar):
    halt = record(published="2026-09-15T08:00:00+08:00")
    old = record("old", published="2026-09-14T00:00:00+08:00", state="unparsed")
    assert resolve([halt, old], suspension_calendar).evidence_by_symbol
    old.update(_text="公司股票自2026年9月16日起复牌。", _state="parsed")
    assert not resolve([halt, old], suspension_calendar).evidence_by_symbol


@pytest.mark.parametrize("text", [
    "公司股票自2026年9月31日开市起连续停牌。",
    "申报期间：2026年9月18日至9月15日。期间公司股票停牌。",
])
def test_bad_dates_are_diagnostic_and_do_not_abort_other_symbol(suspension_calendar, text):
    result = resolve([record(text=text), record("good", symbol="600825", text=XINHUA)], suspension_calendar)
    assert set(result.evidence_by_symbol) == {"600825"}
    doc = result.diagnostics_by_symbol["601995"]["documents"][0]
    assert doc["reason"] == "invalid_status_fact" and doc["error"]


@pytest.mark.parametrize("target,reason", [
    (date(2026, 9, 19), "target_not_open"),
    (date(2027, 1, 1), "calendar_unavailable"),
    (date(2026, 7, 2), "calendar_unavailable"),  # Incomplete lookback coverage.
])
def test_calendar_errors_do_not_default_to_weekdays(suspension_calendar, target, reason):
    result = resolve([record()], suspension_calendar, target)
    assert not result.evidence_by_symbol
    assert result.diagnostics_by_symbol["601995"]["reason"] == reason


def test_missing_calendar_and_discovery_failure_are_explained(monkeypatch):
    def unavailable():
        raise ValueError("trading_calendar_unavailable")
    monkeypatch.setattr("gp_assistant.application.official_suspension.load_cn_a_calendar", unavailable)
    result = resolve([record()], None)
    assert result.diagnostics_by_symbol["601995"]["reason"] == "calendar_unavailable"


def test_preopen_identity_verification_and_complete_discovery(suspension_calendar):
    future = record("future", published="2026-09-18T09:31:00+08:00", text="公司股票自2026年9月18日起复牌。")
    assert resolve([record(), future], suspension_calendar).evidence_by_symbol
    assert not resolve([future], suspension_calendar).evidence_by_symbol
    invalid = record("bad", published="not-a-date")
    assert not resolve([record(), invalid], suspension_calendar).evidence_by_symbol
    client = Client([record()], complete=False)
    collector = OfficialSuspensionEvidenceCollector(client=client, verifier=Verifier(), parser=client.parse, calendar=suspension_calendar)
    args = dict(symbols=("601995",), trade_date=date(2026, 9, 18), observed_at=datetime.now(timezone.utc))
    assert collector.resolve(**args).diagnostics_by_symbol["601995"]["reason"] == "discovery_incomplete"
    client.complete = True
    collector.verifier.verify = lambda *_a, **_k: False
    result = collector.resolve(**args)
    assert not result.evidence_by_symbol
    assert result.diagnostics_by_symbol["601995"]["documents"][0]["reason"] == "exchange_unverified"
    collector.verifier = Verifier()
    client.fetch_symbol = lambda *_a, **_k: {"complete": True, "records": [record(symbol="600825")]}
    result = collector.resolve(**args)
    assert not result.evidence_by_symbol
    assert result.diagnostics_by_symbol["601995"]["documents"][0]["reason"] == "issuer_mismatch"


def test_no_bare_duration_or_unrecognized_status_proof(suspension_calendar):
    assert not resolve([record(text="公司股票自2026年9月15日开市起停牌，预计停牌不超过10个交易日。")], suspension_calendar).evidence_by_symbol
    result = resolve([record(), record("update", published="2026-09-17T00:00:00+08:00", text="新的停复牌安排尚未确定。")], suspension_calendar)
    assert not result.evidence_by_symbol
    assert result.diagnostics_by_symbol["601995"]["reason"] == "unresolved_status_disclosure"


@pytest.mark.parametrize("text", [
    "公司股票自2026年9月18日开市起不停牌，正常交易。",
    "公司股票自2026年9月18日开市起不再停牌。",
    "公司股票自2026年9月18日开市起可能停牌。",
    "标的公司股票自2026年9月15日开市起连续停牌，本公司股票正常交易。",
    "标的公司申报期间为2026年9月15日至2026年9月18日。期间标的公司股票停牌，本公司股票正常交易。",
    "若获批准，公司股票自2026年9月18日开市起连续停牌。",
    "公司股票不于2026年9月18日停牌一天。",
    "公司股票无需自2026年9月18日开市起停牌。",
    "标的公司，停牌日期为2026年9月18日。本公司股票正常交易。",
    "公司股票自2026年9月15日开市起停牌一天。标的公司股票将连续停牌。",
    "公司股票自2026年9月15日开市起停牌一天。公司股票可能继续停牌。",
    "公司股票自2026年9月15日开市起停牌。标的公司股票将连续停牌。",
])
def test_only_affirmative_issuer_halts_are_evidence(suspension_calendar, text):
    assert not resolve([record(text=text)], suspension_calendar).evidence_by_symbol


def test_cumulative_duration_crosses_sentence_boundary(suspension_calendar):
    text = "公司股票自2026年9月7日开市起停牌。公司股票自2026年9月8日开市起继续停牌，预计停牌累计时间不超过10个交易日。"
    assert resolve([record(text=text)], suspension_calendar).evidence_by_symbol["601995"]["elapsed_sessions"] == 10
    assert not resolve([record(text=text)], suspension_calendar, date(2026, 9, 21)).evidence_by_symbol


def test_captured_historical_official_pdf_text(suspension_calendar):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/official_suspension_20260820.json").read_text(encoding="utf-8"))
    rows = [record(item["source_record_id"], symbol=item["symbol"], title=item["title"],
                   published=item["published_at"], text=item["text"]) for item in fixture["records"]]
    # Same captured batches also contained these unrelated >40-page documents.
    rows.extend([
        record("1225479230", symbol="002445", title="2026年半年度审阅报告", published="2026-08-19T00:00:00+08:00", text="", state="page_limit"),
        record("1225479228", symbol="002445", title="2026年半年度报告", published="2026-08-19T00:00:00+08:00", text="", state="page_limit"),
        record("1225482255", symbol="002906", title="公司章程（2026年8月）", published="2026-08-20T00:00:00+08:00", text="", state="page_limit"),
        record("1225482248", symbol="002906", title="2026年半年度报告", published="2026-08-20T00:00:00+08:00", text="", state="page_limit"),
    ])
    result = resolve(rows, suspension_calendar, date(2026, 8, 20))
    assert {symbol: evidence["source_record_id"] for symbol, evidence in result.evidence_by_symbol.items()} == {
        "002084": "1225479880", "002445": "1225476184", "002906": "1225481393", "600984": "1225477636",
    }
    assert {symbol: evidence["elapsed_sessions"] for symbol, evidence in result.evidence_by_symbol.items()} == {
        "002084": 2, "002445": 4, "002906": 1, "600984": 8,
    }


@pytest.mark.parametrize("symbol", ["601995", "000002"])
def test_exchange_transport_errors_survive_in_diagnostics(suspension_calendar, symbol):
    class Session:
        headers = {}
        def get(self, *_args, **_kwargs):
            raise TimeoutError("fixture_exchange_timeout")
        post = get
    verifier = ExchangeVerifier(session=Session())
    row = record(symbol=symbol)
    bounds = dict(start=date(2026, 9, 4), end=date(2026, 9, 18))
    assert verifier.verify(row, **bounds) is False  # Existing Serenity contract.
    with pytest.raises(TimeoutError, match="fixture_exchange_timeout"):
        verifier.verify(row, **bounds, raise_on_error=True)
    client = Client([row])
    collector = OfficialSuspensionEvidenceCollector(client=client, verifier=verifier,
                                                    parser=client.parse, calendar=suspension_calendar)
    result = collector.resolve(symbols=(symbol,), trade_date=date(2026, 9, 18), observed_at=datetime.now(timezone.utc))
    assert not result.evidence_by_symbol
    diagnostic = result.diagnostics_by_symbol[symbol]["documents"][0]
    assert diagnostic["reason"] == "exchange_failed"
    assert diagnostic["error"] == "TimeoutError:fixture_exchange_timeout"
