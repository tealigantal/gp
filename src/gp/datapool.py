from __future__ import annotations

import io
import time
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Dict, Iterable, List, Optional

import duckdb
import pandas as pd
import requests

from .config import Config, load_config
from .utils import ensure_dir, hash_key, save_json, load_json


@dataclass
class FetchResult:
    ok: bool
    status: int
    url: str
    params: Dict
    source: str
    reason: Optional[str]
    json: Optional[Dict]
    fetched_at: str


class RawCache:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.path = cfg.cache / "raw"
        ensure_dir(self.path)

    def put(self, source: str, url: str, params: Dict, status: int, payload: Dict | None, reason: str | None) -> FetchResult:
        key = hash_key(source, {"url": url, "params": params})
        rec = {
            "source": source,
            "url": url,
            "params": params,
            "status": status,
            "ok": status == 200 and payload is not None,
            "json": payload,
            "reason": reason,
            "fetched_at": datetime.utcnow().isoformat(),
        }
        save_json(self.path / f"{key}.json", rec)
        return FetchResult(
            ok=rec["ok"],
            status=status,
            url=url,
            params=params,
            source=source,
            reason=reason,
            json=payload,
            fetched_at=rec["fetched_at"],
        )

    def get(self, source: str, url: str, params: Dict) -> Optional[FetchResult]:
        key = hash_key(source, {"url": url, "params": params})
        rec = load_json(self.path / f"{key}.json")
        if rec is None:
            return None
        return FetchResult(
            ok=rec.get("ok", False),
            status=rec.get("status", 0),
            url=rec.get("url"),
            params=rec.get("params", {}),
            source=rec.get("source", "unknown"),
            reason=rec.get("reason"),
            json=rec.get("json"),
            fetched_at=rec.get("fetched_at", ""),
        )


class DataPool:
    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or load_config()
        ensure_dir(self.cfg.store)
        ensure_dir(self.cfg.cache)
        self.raw = RawCache(self.cfg)
        self.db_path = self.cfg.store / "gp.duckdb"
        self._con = duckdb.connect(str(self.db_path))
        self._init_tables()

    @property
    def con(self):
        return self._con

    def _init_tables(self):
        # Create basic tables if not exist
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS bars_daily (
                date DATE,
                code VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                amount DOUBLE,
                adj DOUBLE
            );
            """
        )
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS index_daily (
                date DATE,
                index_code VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                amount DOUBLE
            );
            """
        )
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS features_daily (
                date DATE,
                code VARCHAR,
                atrp DOUBLE,
                ma20 DOUBLE,
                bias6 DOUBLE,
                bias12 DOUBLE,
                bias24 DOUBLE,
                rsi2 DOUBLE,
                bbwidth DOUBLE,
                nr7 BOOLEAN,
                volratio DOUBLE,
                slope20 DOUBLE
            );
            """
        )
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                date DATE,
                code VARCHAR,
                title VARCHAR,
                type VARCHAR,
                source VARCHAR,
                risk_level VARCHAR,
                tags VARCHAR
            );
            """
        )
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS market_breadth (
                date DATE,
                total_amount DOUBLE,
                up_limit INT,
                down_limit INT,
                broken_limit INT,
                seal_ratio DOUBLE,
                max_consecutive INT,
                advancers INT,
                decliners INT
            );
            """
        )

    # -------------------------------------------------
    # Eastmoney daily kline fetcher (primary), AkShare fallback
    # -------------------------------------------------
    def _eastmoney_daily(self, code: str, begin: str, end: str) -> Optional[pd.DataFrame]:
        # Map code to secid: 1.SH, 0.SZ
        if code.endswith(".SH"):
            secid = f"1.{code[:6]}"
        elif code.endswith(".SZ"):
            secid = f"0.{code[:6]}"
        else:
            return None
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "klt": 101,
            "fqt": 1,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56",
            "beg": begin,
            "end": end,
        }
        cached = self.raw.get("eastmoney_kline", url, params)
        if cached and cached.ok:
            data = cached.json
        else:
            headers = {"User-Agent": self.cfg.raw["fetch"]["user_agent"]}
            proxies = self.cfg.raw["fetch"].get("proxies") or None
            try:
                resp = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=self.cfg.raw["fetch"]["timeout_sec"])
                status = resp.status_code
                payload = resp.json() if status == 200 else None
                result = self.raw.put("eastmoney_kline", url, params, status, payload, None if status == 200 else f"HTTP {status}")
                data = result.json
            except Exception as e:
                self.raw.put("eastmoney_kline", url, params, 0, None, str(e))
                data = None
        if not data or data.get("data") is None:
            return None
        kl = data["data"].get("klines") or []
        if not kl:
            return None
        # f51,f52,f53,f54,f55,f56 -> date, open, close, high, low, volume
        rows = []
        for line in kl:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            dt, o, c, h, l, v = parts[:6]
            rows.append({
                "date": pd.to_datetime(dt).date(),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v) * 100.0,  # hands->shares approx
                "amount": None,
            })
        df = pd.DataFrame(rows)
        df["code"] = code
        df["adj"] = 1.0
        return df[["date", "code", "open", "high", "low", "close", "volume", "amount", "adj"]]

    def _akshare_daily(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            sec = code.replace(".SH", "sh").replace(".SZ", "sz")
            df = ak.stock_zh_a_daily(symbol=sec, adjust="")
            df = df.reset_index().rename(columns={"index": "date"})
            df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
            df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
            df["code"] = code
            df["amount"] = None
            df["adj"] = 1.0
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[["date", "code", "open", "high", "low", "close", "volume", "amount", "adj"]]
        except Exception:
            return None

    def update_bars_daily(self, codes: Iterable[str], until: date, lookback_days: int = 60) -> pd.DataFrame:
        # Incrementally fetch recent N days per code, append missing rows
        begin = (until - timedelta(days=max(lookback_days, 5))).strftime("%Y%m%d")
        end = until.strftime("%Y%m%d")
        frames: List[pd.DataFrame] = []
        for code in codes:
            df = self._eastmoney_daily(code, begin, end)
            if df is None or df.empty:
                df = self._akshare_daily(code, begin, end)
            if df is None or df.empty:
                continue
            frames.append(df)
            # rudimentary rate limit
            time.sleep(1.0 / max(1, int(self.cfg.raw["fetch"]["rate_limit_per_host_per_sec"])) )
        if not frames:
            return pd.DataFrame(columns=["date","code","open","high","low","close","volume","amount","adj"])
        batch = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["date","code"]).sort_values(["code","date"]) 
        # Insert with dedup within DuckDB
        self.con.unregister("batch") if "batch" in [x[0] for x in self.con.execute("PRAGMA show_tables").fetchall()] else None
        self.con.register("batch", batch)
        self.con.execute("CREATE OR REPLACE TEMP TABLE _new_bars AS SELECT * FROM batch")
        self.con.execute(
            """
            INSERT INTO bars_daily
            SELECT * FROM _new_bars nb
            WHERE NOT EXISTS (
                SELECT 1 FROM bars_daily b WHERE b.code = nb.code AND b.date = nb.date
            )
            """
        )
        return batch

    def read_bars(self, code: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        conds = ["code = ?"]
        args = [code]
        if start:
            conds.append("date >= ?")
            args.append(start)
        if end:
            conds.append("date <= ?")
            args.append(end)
        q = f"SELECT * FROM bars_daily WHERE {' AND '.join(conds)} ORDER BY date"
        return self.con.execute(q, args).fetch_df()

    # Index daily update for SH000001 / SZ399001
    def update_index_daily(self, indices: Optional[List[str]] = None, until: Optional[date] = None, lookback_days: int = 120) -> pd.DataFrame:
        idx = indices or ["SH000001", "SZ399001"]
        if until is None:
            until = date.today()
        begin = (until - timedelta(days=max(lookback_days, 5))).strftime("%Y%m%d")
        end = until.strftime("%Y%m%d")
        frames: List[pd.DataFrame] = []
        for ic in idx:
            if ic.startswith("SH"):
                secid = f"1.{ic[2:]}"
            elif ic.startswith("SZ"):
                secid = f"0.{ic[2:]}"
            else:
                continue
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": secid,
                "klt": 101,
                "fqt": 1,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56",
                "beg": begin,
                "end": end,
            }
            cached = self.raw.get("eastmoney_kline", url, params)
            if cached and cached.ok:
                data = cached.json
            else:
                headers = {"User-Agent": self.cfg.raw["fetch"]["user_agent"]}
                proxies = self.cfg.raw["fetch"].get("proxies") or None
                try:
                    resp = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=self.cfg.raw["fetch"]["timeout_sec"])
                    status = resp.status_code
                    payload = resp.json() if status == 200 else None
                    result = self.raw.put("eastmoney_kline", url, params, status, payload, None if status == 200 else f"HTTP {status}")
                    data = result.json
                except Exception as e:
                    self.raw.put("eastmoney_kline", url, params, 0, None, str(e))
                    data = None
            if not data or data.get("data") is None:
                continue
            kl = data["data"].get("klines") or []
            rows = []
            for line in kl:
                parts = line.split(",")
                if len(parts) < 6:
                    continue
                dt, o, c, h, l, v = parts[:6]
                rows.append({
                    "date": pd.to_datetime(dt).date(),
                    "open": float(o),
                    "high": float(h),
                    "low": float(l),
                    "close": float(c),
                    "volume": float(v) * 100.0,
                    "amount": None,
                })
            df = pd.DataFrame(rows)
            df["index_code"] = ic
            frames.append(df[["date","index_code","open","high","low","close","volume","amount"]])
        if not frames:
            return pd.DataFrame(columns=["date","index_code","open","high","low","close","volume","amount"])
        batch = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["date","index_code"]).sort_values(["index_code","date"]) 
        self.con.unregister("batch") if "batch" in [x[0] for x in self.con.execute("PRAGMA show_tables").fetchall()] else None
        self.con.register("batch", batch)
        self.con.execute("CREATE OR REPLACE TEMP TABLE _new_idx AS SELECT * FROM batch")
        self.con.execute(
            """
            INSERT INTO index_daily
            SELECT * FROM _new_idx nb
            WHERE NOT EXISTS (
                SELECT 1 FROM index_daily b WHERE b.index_code = nb.index_code AND b.date = nb.date
            )
            """
        )
        return batch

    def update_simple_breadth(self, d: date) -> None:
        # Approximate breadth from bars_daily for same-day advance/decline within stored universe
        df = self.con.execute(
            """
            WITH x AS (
                SELECT code, date, close, LAG(close) OVER (PARTITION BY code ORDER BY date) AS prev_close
                FROM bars_daily WHERE date <= ?
            )
            SELECT SUM(CASE WHEN date = ? AND close > prev_close THEN 1 ELSE 0 END) AS adv,
                   SUM(CASE WHEN date = ? AND close < prev_close THEN 1 ELSE 0 END) AS dec
            FROM x
            """,
            [d, d, d],
        ).fetch_df()
        if df.empty or pd.isna(df.iloc[0]["adv"]) or pd.isna(df.iloc[0]["dec"]):
            adv = 0
            dec = 0
        else:
            adv = int(df.iloc[0]["adv"])
            dec = int(df.iloc[0]["dec"])
        self.con.execute(
            """
            INSERT INTO market_breadth(date, total_amount, up_limit, down_limit, broken_limit, seal_ratio, max_consecutive, advancers, decliners)
            SELECT ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM market_breadth WHERE date = ?)
            """,
            [d, adv, dec, d],
        )
