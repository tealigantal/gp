from datetime import date, datetime, timezone

from gp_assistant.application.official_suspension import OfficialSuspensionEvidenceCollector, _halt_evidence, _resume_effective_by


def test_bounded_continuous_and_explicit_halt_interval():
    continuous = '公司股票自2026年9月15日开市起连续停牌，刊登申报结果公告当日复牌。'
    assert _halt_evidence(continuous, trade_date=date(2026, 9, 17))[1] == 'continuation_halt'
    assert not _resume_effective_by(continuous, trade_date=date(2026, 9, 17))
    assert _halt_evidence(continuous, trade_date=date(2026, 9, 25)) is None
    interval = '申报期间：2026年9月15日至2026年9月17日。申报期间公司A股股票停牌。'
    assert _halt_evidence(interval, trade_date=date(2026, 9, 17))[1] == 'explicit_halt_interval'
    assert _halt_evidence(interval, trade_date=date(2026, 9, 18)) is None


def test_all_preopen_documents_checked_for_conflicting_resume():
    texts = {'a': '申报期间：2026年9月15日至2026年9月17日。期间公司股票停牌。',
             'b': '公司股票自2026年9月17日开市起恢复交易。'}
    class Client:
        def load_stock_map(self):
            return {'601995': {'org_id': 'fixture'}}
        def fetch_symbol(self, *_args, **_kwargs):
            return {'complete': True, 'backlog': False, 'records': [
                {'symbol': '601995', 'title': '申报实施公告', 'published_at': '2026-09-17T08:00:00+08:00',
                 'source_record_id': key, 'source_url': key} for key in texts]}
        def download_pdf(self, url, **_kwargs):
            return url.encode()
    class Verifier:
        def verify(self, *_args, **_kwargs):
            return True
    collector = OfficialSuspensionEvidenceCollector(client=Client(), verifier=Verifier(),
        parser=lambda value, **_: (texts[value.decode()], 'parsed'))
    args = dict(symbols=('601995',), trade_date=date(2026, 9, 17), observed_at=datetime.now(timezone.utc))
    assert collector.resolve(**args) == {}
    texts['b'] = '公司股票自2026年9月16日开市起恢复交易。'
    assert collector.resolve(**args) == {}
    texts['b'] = '公司股票自2026年9月16日起复牌。'
    assert collector.resolve(**args) == {}
    del texts['b']
    assert collector.resolve(**args)['601995']['evidence_kind'] == 'explicit_halt_interval'
