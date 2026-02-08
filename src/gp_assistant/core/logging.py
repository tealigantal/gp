# 简介：日志封装。基于 loguru 提供简单统一的日志记录接口与默认配置。
from __future__ import annotations

import logging
import os


def setup_logging() -> None:
    level_name = os.getenv("GP_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


logger = logging.getLogger("gp_assistant")
