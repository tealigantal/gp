# 简介：项目路径工具。统一定位 data/results/universe/store/cache/configs 等目录，
# 供各子模块读写数据与缓存。
from __future__ import annotations

from pathlib import Path
import os


def project_root() -> Path:
    # Assume this file is under src/gp_assistant/core
    return Path(__file__).resolve().parents[3]


def src_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return _ensure_dir(os.getenv("GP_DATA_DIR") or str(project_root() / "data"))


def results_dir() -> Path:
    return _ensure_dir(os.getenv("GP_RESULTS_DIR") or str(project_root() / "results"))


def universe_dir() -> Path:
    return _ensure_dir(os.getenv("GP_UNIVERSE_DIR") or str(project_root() / "universe"))


def store_dir() -> Path:
    return _ensure_dir(os.getenv("GP_STORE_DIR") or str(project_root() / "store"))


def cache_dir() -> Path:
    return _ensure_dir(os.getenv("GP_CACHE_DIR") or str(project_root() / "cache"))


def configs_dir() -> Path:
    return _ensure_dir(os.getenv("GP_CONFIGS_DIR") or str(project_root() / "configs"))


def _ensure_dir(path_str: str) -> Path:
    p = Path(path_str)
    p.mkdir(parents=True, exist_ok=True)
    return p
