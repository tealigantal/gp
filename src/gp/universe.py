from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .config import Config, load_config


@dataclass
class Universe:
    cfg: Config

    def candidate_codes_for(self, d: date) -> List[str]:
        # Prefer explicit candidate_pool_YYYYMMDD*.csv under universe/
        ymd = d.strftime("%Y%m%d")
        uni_dir = self.cfg.universe
        if not uni_dir.exists():
            return []
        files = sorted(uni_dir.glob(f"candidate_pool_{ymd}*.csv"))
        if not files:
            return []
        # Expect a column 'code' or the first column to be code
        df = pd.read_csv(files[0])
        if "code" in df.columns:
            code_col = "code"
        elif "ts_code" in df.columns:
            code_col = "ts_code"
        else:
            code_col = df.columns[0]
        codes = (
            df[code_col]
            .astype(str)
            .str.upper()
            .str.replace(".XSHE", ".SZ")
            .str.replace(".XSHG", ".SH")
            .tolist()
        )
        return [c for c in codes if c.endswith((".SH", ".SZ"))]
