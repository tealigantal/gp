from __future__ import annotations

"""Parse announcement facts, then evaluate their trading-session validity.

No transport, ledger access, or provider-empty inference belongs here. Limits
are evidence policy bounds, not forecasts that a stock will remain suspended.
"""

from dataclasses import dataclass
from datetime import date
import re
from typing import Literal

from ..serenity.text import normalize_cn_text
from .trading_calendar import CnATradingCalendar


POLICY_REVISION = "official-suspension.v3"
MAX_HALT_SESSIONS = 10
CONTINUATION_SESSIONS = 5
_DATE = r"20\d{2}年\d{1,2}月\d{1,2}日"
_ISSUER = r"(?:本公司|公司)(?:A股)?(?:股票|股份)"
_UNCERTAIN = re.compile(r"无法|未能|尚未|不能|不得|不会|无需|不必|不再|不予|不在|不于|不自|预计|计划|拟|可能|争取|若|如果|待")


def _issuer_assertion(text: str, start: int, end: int, *, state: str) -> bool:
    """Bind the action to the issuer and reject negated/conditional assertions.

    Coordinated clauses may inherit the preceding issuer subject. A later
    foreign subject breaks that inheritance. A notice's listing identity alone
    cannot make its statements about another company's shares issuer facts.
    """
    # Semicolons inside stock-code/name annotations are not clause boundaries.
    # Strip only balanced parenthetical annotations for subject analysis;
    # original text and offsets remain intact in the audited excerpts.
    before = re.sub(r"[（(][^（）()]*[）)]", "", text[:start])
    left = max(before.rfind("。"), before.rfind("；")) + 1
    before = before[left:]
    clause = re.split(r"[，,]", before)[-1]
    action = text[start:end]
    if _UNCERTAIN.search(clause + action) or re.search(r"不(?:再)?停牌|无需停牌|不(?:再)?复牌", clause + action):
        return False
    if re.search(r"若|如果|待", before):
        return False
    if "申请" in clause and not re.search(r"批准|同意|核准", clause):
        return False
    # Standard issuer-owned explicit fields do not repeat the subject.
    if re.search(r"(?:^|[，,])停牌日期(?:为|：|:)?$", before):
        # A foreign subject earlier in the same sentence prevents a field
        # from using the announcement issuer as its implicit subject.
        return state == "halted" and "公司" not in before
    subjects = list(re.finditer(r"(?:本公司|公司)(?:A股)?(?:股票|股份|证券)|股票", before))
    if not subjects:
        # One-day disclosures often coordinate a resume date after a comma;
        # same-day actual resumes are still checked if there is an issuer
        # subject before the immediately preceding sentence boundary.
        return False
    subject = subjects[-1]
    prefix = before[:subject.start()]
    if subject.group().startswith(("本公司", "公司")):
        return (not prefix or not re.search(r"[\u4e00-\u9fff]$", prefix)
                or prefix.endswith(("期间", "批准", "同意", "核准")))
    return not prefix or prefix[-1] in "，,：:"


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", normalize_cn_text(text))


def _date(value: str) -> date:
    try:
        return date(*(int(part) for part in re.findall(r"\d+", value)))
    except ValueError as exc:
        raise ValueError(f"invalid_announcement_date:{value}") from exc


@dataclass(frozen=True)
class TradingStatusFact:
    state: Literal["halted", "resumed"]
    starts_on: date
    ends_on: date | None
    session_limit: int
    kind: str
    excerpt: str
    resumption_condition: str | None = None
    resumption_trigger: Literal["investigation_disclosure", "result_disclosure", "further_disclosure"] | None = None

    def may_fulfil_resumption(self, *, title: str, text: str) -> bool:
        """A later possible trigger withdraws proof; it does not prove trading.

        Even an undated investigation/result notice can satisfy the original
        condition. Ambiguity must not preserve a no-bar exclusion. An explicit
        newer halt is resolved separately by the collector's chronology.
        """
        if self.resumption_trigger == "investigation_disclosure":
            return bool(re.search(r"核查|核实", normalize(title) + normalize(text)))
        if self.resumption_trigger == "result_disclosure":
            return "结果" in normalize(title) + normalize(text)
        return self.resumption_trigger == "further_disclosure"

    def validity(self, target: date, calendar: CnATradingCalendar) -> str:
        if not calendar.is_open(target):
            return "target_not_open"
        if not calendar.is_open(self.starts_on):
            return "effective_date_not_open"
        if target < self.starts_on:
            return "not_yet_effective"
        if self.state == "resumed":
            return "effective"
        if self.ends_on is not None and target > self.ends_on:
            return "interval_ended"
        if self.session_limit <= 0 or self.session_limit > MAX_HALT_SESSIONS:
            return "unsupported_duration"
        # Inclusive: the initial suspension session consumes one session.
        if len(calendar.open_days_between(self.starts_on, target)) > self.session_limit:
            return "session_limit_exceeded"
        return "effective"

    def payload(self) -> dict[str, object]:
        return {
            "state": self.state, "starts_on": self.starts_on.isoformat(),
            "ends_on": self.ends_on.isoformat() if self.ends_on else None,
            "session_limit": self.session_limit, "duration_unit": "trading_session",
            "kind": self.kind, "excerpt": self.excerpt,
            "resumption_condition": self.resumption_condition,
            "resumption_trigger": self.resumption_trigger,
        }


def parse_status_facts(text: str) -> tuple[TradingStatusFact, ...]:
    """Extract dated assertions, keeping conditional resumption non-effective.

    Recognized language is shared across issuers. Unrecognized language yields
    no positive proof; malformed recognized dates reject the document.
    """
    text = normalize(text)
    facts: list[TradingStatusFact] = []

    # Check all parsed documents, including ones whose title omits 停复牌.
    resume = re.compile(
        rf"(?P<day>{_DATE})(?:[^。；，,]{{0,48}}?(?:开市|开盘)(?:起|后|时)?|"
        r"(?:[（(]星期[一二三四五六日天][）)])?起)(?:复牌|恢复交易)"
    )
    for match in resume.finditer(text):
        if not _issuer_assertion(text, match.start(), match.end(), state="resumed"):
            continue
        facts.append(TradingStatusFact("resumed", _date(match["day"]), None, 0,
                                       "dated_resumption", text[max(0, match.start()-64):match.end()+48]))

    interval = re.compile(
        rf"(?P<start>{_DATE})至(?:(?P<y>20\d{{2}})年)?(?:(?P<m>\d{{1,2}})月)?(?P<d>\d{{1,2}})日"
        rf"[^。]{{0,120}}?[。；]?[^。]{{0,60}}?期间[^。；]{{0,40}}?{_ISSUER}[^。；]{{0,15}}?停牌"
    )
    for match in interval.finditer(text):
        # An interval's subject may occur after its dates. Evaluate the
        # assertion at the action, while retaining the interval's context.
        halt_at = match.end() - len("停牌")
        if not _issuer_assertion(text, halt_at, match.end(), state="halted"):
            continue
        start = _date(match["start"])
        end = _date(f"{match['y'] or start.year}年{match['m'] or start.month}月{match['d']}日")
        if end < start:
            raise ValueError("invalid_suspension_interval")
        facts.append(TradingStatusFact("halted", start, end, MAX_HALT_SESSIONS,
                                       "explicit_halt_interval", match.group()))

    starts = list(re.finditer(
        rf"(?:自|于)(?P<day>{_DATE})(?P<tail>[^。；，,]{{0,48}}?(?:开市|开盘)(?:起|后|时)?(?:开始|继续|连续)?|"
        r"(?:[（(]星期[一二三四五六日天][）)])?起(?:开始|继续|连续)?)停牌", text
    ))
    continuations = [item for item in re.finditer(r"继续停牌|仍停牌|连续停牌", text)
                     if _issuer_assertion(text, item.start(), item.end(), state="halted")]
    # A cumulative duration starts at the first suspension, never at a later
    # '继续停牌' restatement, including when separated by sentence punctuation.
    asserted_starts = [match for match in starts
                       if _issuer_assertion(text, match.start(), match.end(), state="halted")]
    for match in asserted_starts:
        if re.search(_DATE, match["tail"]):
            continue
        start = _date(match["day"])
        left = text.rfind("。", 0, match.start()) + 1
        right = text.find("。", match.end())
        paragraph = text[left:right if right >= 0 else len(text)]
        window = text[max(left, match.start()-100):match.end()+240]
        declared = re.search(r"(?:停牌[^。；]{0,30}?)不超过(?P<n>\d{1,2})个交易日", paragraph)
        if declared is None:
            # A reconstruction notice may put its bounded disclosure/resume
            # undertaking in the next sentence, after the dated halt assertion.
            declared = re.search(
                r"。公司预计在不超过(?P<n>\d{1,2})个交易日内[^。]{0,240}申请复牌",
                text[match.end():match.end()+400],
            )
        continuing = any(match.start() <= item.start() < match.end()+240 for item in continuations)
        period = ("停牌期间" in text or "停牌期限" in text) and "复牌" in text
        limit = int(declared["n"]) if declared else CONTINUATION_SESSIONS
        if declared and "累计" in paragraph:
            # Punctuation cannot reset a cumulative start. Earlier issuer halt
            # assertions remain part of the cumulative episode, even across
            # sentences. Ambiguous historical episodes fail conservatively.
            start = min(_date(other["day"]) for other in asserted_starts if other.start() <= match.start())
        one_day = re.match(r"(?:1天|一天|1个交易日|一个交易日)", text[match.end():])
        # An affirmative halt can end on a future disclosure rather than a
        # known date. Bind that condition to the immediately coordinated
        # issuer clause, never to another sentence/company or a forecast.
        condition = re.match(
            r"[，,](?:并)?(?:自|待)(?:披露|刊登)(?P<topic>核查|核查结果|相关|结果)公告(?:后|当日)(?:复牌|恢复交易)(?=[。；，,]|$)",
            text[match.end():],
        )
        if not one_day and condition:
            facts.append(TradingStatusFact(
                "halted", start, None, limit, "conditional_resumption_halt", window,
                condition.group()[1:],
                "investigation_disclosure" if condition["topic"].startswith("核查")
                else "result_disclosure" if condition["topic"] == "结果" else "further_disclosure",
            ))
        elif not one_day and (continuing or (declared and period)):
            facts.append(TradingStatusFact("halted", start, None, limit, "continuation_halt", window))
        else:
            facts.append(TradingStatusFact("halted", start, start, 1, "exact_target_date", window))

    for pattern in (
        rf"停牌日期(?:为|：|:)?(?P<day>{_DATE})",
        rf"(?:公司)?股票(?:将)?于(?P<day>{_DATE})停牌(?:1天|一天|全天)",
    ):
        for match in re.finditer(pattern, text):
            date_at = match.start("day")
            if not _issuer_assertion(text, date_at, match.end(), state="halted"):
                continue
            start = _date(match["day"])
            facts.append(TradingStatusFact("halted", start, start, 1, "exact_target_date",
                                           text[max(0, match.start()-64):match.end()+144]))
    return tuple(facts)


def disclosure_role(title: str) -> Literal["status_notice", "ancillary_document", "unknown"]:
    """Only positively identified ancillary reports may be non-blocking.

    This is NOT a title filter on parsed facts. Unknown titles and status,
    correction or progress notices remain blocking when unreadable/unverified.
    """
    title = normalize(title)
    if re.search(r"停牌|复牌|恢复交易|更正|补充|修订|更新|进展|提示", title):
        return "status_notice"
    if re.search(r"报告书(?:摘要)?|财务顾问报告|审计报告|审阅报告|评估报告|(?:年度|季度)报告|公司章程", title):
        return "ancillary_document"
    return "unknown"
