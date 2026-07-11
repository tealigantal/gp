from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any, Callable, Dict, List
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from .text import normalize_cn_text


CNINFO_BASE = "https://www.cninfo.com.cn/"
CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCKS = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_STATIC = "https://static.cninfo.com.cn/"


class SourceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retry_after: float | None = None, schema_error: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.schema_error = schema_error


_ANNOUNCEMENT_SCHEMA_CONTRACT = {
    "envelope": ["announcements", "totalpages"],
    "row_required": [
        "announcementId|id",
        "adjunctUrl",
        "secCode",
        "announcementTitle",
        "announcementTime",
    ],
    "version": 1,
}


def _schema_fingerprint(items: List[Dict[str, Any]]) -> str | None:
    if not items:
        return None
    return sha256(
        json.dumps(
            _ANNOUNCEMENT_SCHEMA_CONTRACT,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:16]


def _published_at(value: Any) -> str | None:
    text = str(value or "").strip()
    try:
        if text.isdigit():
            raw = int(text)
            seconds = raw / 1000.0 if raw > 10_000_000_000 else float(raw)
            return datetime.fromtimestamp(seconds, tz=ZoneInfo("Asia/Shanghai")).isoformat()
        if text:
            parsed = datetime.fromisoformat(text.replace("/", "-"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            return parsed.isoformat()
    except Exception:
        return None
    return None


class CNInfoClient:
    def __init__(
        self,
        *,
        timeout_sec: float = 15.0,
        page_size: int = 30,
        page_budget: int = 10,
        spacing_sec: float = 1.0,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout_sec = float(timeout_sec)
        self.page_size = max(1, min(100, int(page_size)))
        self.page_budget = max(1, int(page_budget))
        self.spacing_sec = max(0.0, float(spacing_sec))
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; GP-Serenity/1.0; local-research)",
                "Referer": "https://www.cninfo.com.cn/",
                "Accept": "application/json,text/plain,*/*",
            }
        )
        self.sleeper = sleeper
        self.request_count = 0

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if self.request_count and self.spacing_sec:
            self.sleeper(self.spacing_sec)
        self.request_count += 1
        try:
            response = self.session.request(method, url, timeout=self.timeout_sec, **kwargs)
        except requests.RequestException as ex:
            raise SourceError(f"cninfo_request_failed:{type(ex).__name__}:{ex}") from ex
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            try:
                retry_after = float(retry) if retry is not None else None
            except Exception:
                try:
                    parsed = parsedate_to_datetime(str(retry))
                    retry_after = max(0.0, (parsed - datetime.now(parsed.tzinfo)).total_seconds())
                except Exception:
                    retry_after = None
            raise SourceError("cninfo_rate_limited", status_code=429, retry_after=retry_after)
        if response.status_code in {401, 403}:
            raise SourceError("cninfo_access_blocked", status_code=response.status_code, schema_error=True)
        try:
            response.raise_for_status()
        except requests.RequestException as ex:
            raise SourceError(f"cninfo_http_{response.status_code}", status_code=response.status_code) from ex
        return response

    def load_stock_map(self) -> Dict[str, Dict[str, str]]:
        response = self._request("GET", CNINFO_STOCKS)
        response.encoding = "utf-8"
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("stock_payload_not_object")
            rows = payload["stockList"]
            if not isinstance(rows, list):
                raise TypeError("stock_list_not_array")
            if any(not isinstance(row, dict) for row in rows):
                raise TypeError("stock_row_not_object")
        except Exception as ex:
            raise SourceError("cninfo_stock_schema_changed", schema_error=True) from ex
        out: Dict[str, Dict[str, str]] = {}
        for row in rows:
            code = str(row.get("code") or "").strip()
            org_id = str(row.get("orgId") or "").strip()
            if code and org_id:
                out[code] = {
                    "symbol": code,
                    "org_id": org_id,
                    "name": str(row.get("zwjc") or ""),
                    "category": str(row.get("category") or ""),
                }
        if not out:
            raise SourceError("cninfo_stock_map_empty", schema_error=True)
        return out

    def fetch_symbol(
        self,
        symbol: str,
        org_id: str,
        *,
        start: date,
        end: date,
        start_page: int = 1,
    ) -> Dict[str, Any]:
        column = "sse" if str(symbol).startswith("6") else "szse"
        announcements: List[Dict[str, Any]] = []
        complete = True
        has_more = False
        total_pages = 1
        last_page = max(1, int(start_page)) - 1
        for page in range(max(1, int(start_page)), max(1, int(start_page)) + self.page_budget):
            last_page = page
            form = {
                "pageNum": page,
                "pageSize": self.page_size,
                "column": column,
                "tabName": "fulltext",
                "plate": "",
                "stock": f"{symbol},{org_id}",
                "searchkey": "",
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": f"{start.isoformat()}~{end.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            response = self._request("POST", CNINFO_QUERY, data=form)
            response.encoding = "utf-8"
            try:
                payload = response.json()
                if not isinstance(payload, dict) or "announcements" not in payload or "totalpages" not in payload:
                    raise KeyError("required_top_level_fields_missing")
                rows_value = payload.get("announcements")
                if not isinstance(rows_value, list):
                    raise TypeError("announcements_not_array")
                if any(not isinstance(row, dict) for row in rows_value):
                    raise TypeError("announcement_row_not_object")
                rows = list(rows_value)
                total_pages = max(1, int(payload.get("totalpages") or 1))
                has_more = bool(payload.get("hasMore")) or page < total_pages
            except Exception as ex:
                raise SourceError("cninfo_announcement_schema_changed", schema_error=True) from ex
            for row in rows:
                record_id = str(row.get("announcementId") or row.get("id") or "").strip()
                if not record_id:
                    raise SourceError("cninfo_announcement_id_missing", schema_error=True)
                adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
                row_symbol = str(row.get("secCode") or "").strip()
                title = str(row.get("announcementTitle") or "").strip()
                published_at = _published_at(row.get("announcementTime"))
                if not row_symbol or row_symbol != str(symbol):
                    raise SourceError("cninfo_announcement_symbol_invalid", schema_error=True)
                if not title or not adjunct or published_at is None:
                    raise SourceError("cninfo_announcement_required_field_missing", schema_error=True)
                announcements.append(
                    {
                        "source": "cninfo",
                        "source_record_id": record_id,
                        "symbol": row_symbol,
                        "name": normalize_cn_text(row.get("secName")),
                        "org_id": str(row.get("orgId") or org_id),
                        "title": normalize_cn_text(title).strip(),
                        "published_at": published_at,
                        "source_url": urljoin(CNINFO_STATIC, adjunct),
                        "announcement_type": str(row.get("announcementType") or ""),
                        "raw_metadata": row,
                    }
                )
            if not has_more:
                break
        if has_more and last_page < total_pages:
            complete = False
        return {
            "records": announcements,
            "complete": complete,
            "backlog": not complete,
            "schema_fingerprint": _schema_fingerprint([row.get("raw_metadata") or {} for row in announcements]),
            "total_pages": total_pages,
            "next_page": (last_page + 1 if not complete else None),
            "start_page": max(1, int(start_page)),
        }

    def download_pdf(self, url: str, *, max_bytes: int) -> bytes:
        response = self._request("GET", url, stream=True, headers={"Accept": "application/pdf,*/*"})
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "pdf" not in content_type and not str(url).lower().endswith(".pdf"):
            raise SourceError("cninfo_attachment_not_pdf", schema_error=True)
        chunks: List[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise SourceError("cninfo_pdf_size_limit")
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data.startswith(b"%PDF"):
            raise SourceError("cninfo_pdf_signature_invalid", schema_error=True)
        return data


class ExchangeVerifier:
    def __init__(self, *, timeout_sec: float = 15.0, session: requests.Session | None = None) -> None:
        self.timeout_sec = timeout_sec
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; GP-Serenity/1.0; local-research)"})

    def verify(self, record: Dict[str, Any], *, start: date, end: date) -> bool:
        symbol = str(record.get("symbol") or "")
        return self._verify_sse(record, start=start, end=end) if symbol.startswith("6") else self._verify_szse(record, start=start, end=end)

    def _verify_szse(self, record: Dict[str, Any], *, start: date, end: date) -> bool:
        url = "https://www.szse.cn/api/disc/announcement/annList"
        try:
            wanted = str(record.get("source_record_id") or "")
            for page in range(1, 6):
                body = {
                    "seDate": [start.isoformat(), end.isoformat()],
                    "stock": [str(record.get("symbol") or "")],
                    "channelCode": ["listedNotice_disc"],
                    "pageSize": 100,
                    "pageNum": page,
                }
                response = self.session.post(
                    url,
                    params={"random": "0.314159"},
                    json=body,
                    headers={"Referer": "https://www.szse.cn/disclosure/listed/notice/index.html"},
                    timeout=self.timeout_sec,
                )
                response.raise_for_status()
                rows = list(response.json().get("data") or [])
                if any(str(row.get("annId") or "") == wanted for row in rows):
                    return True
                if len(rows) < 100:
                    break
            return False
        except Exception:
            return False

    def _verify_sse(self, record: Dict[str, Any], *, start: date, end: date) -> bool:
        url = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
        base_params = {
            "isPagination": "true",
            "productId": str(record.get("symbol") or ""),
            "keyWord": "",
            "securityType": "0101,120100,020100,020200,120200",
            "reportType2": "DQGG",
            "reportType": "ALL",
            "beginDate": start.isoformat(),
            "endDate": end.isoformat(),
            "pageHelp.pageSize": "100",
            "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": "5",
        }
        try:
            title = re.sub(r"[\s<>《》：:（）()\-—]", "", str(record.get("title") or ""))
            for page in range(1, 6):
                params = {**base_params, "pageHelp.pageNo": str(page)}
                response = self.session.get(
                    url,
                    params=params,
                    headers={"Referer": "https://www.sse.com.cn/disclosure/listedinfo/announcement/"},
                    timeout=self.timeout_sec,
                )
                response.raise_for_status()
                rows = list(((response.json().get("pageHelp") or {}).get("data") or []))
                for row in rows:
                    row_title = re.sub(
                        r"[\s<>《》：:（）()\-—]",
                        "",
                        str(row.get("TITLE") or ""),
                    )
                    if (
                        str(row.get("SECURITY_CODE") or "") == str(record.get("symbol") or "")
                        and title
                        and row_title
                        and (row_title == title or row_title.endswith(title) or title.endswith(row_title))
                    ):
                        return True
                if len(rows) < 100:
                    break
            return False
        except Exception:
            return False
