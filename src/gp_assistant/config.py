from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class LLMSettings:
    llm_config_file: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    stream: bool = False


@dataclass
class RAGSettings:
    index_db: str
    include_globs: List[str]
    exclude_globs: List[str]


@dataclass
class ToolsSettings:
    enable_gpbt_runner: bool = True
    gpbt_allow_subcommands: List[str] = None  # type: ignore
    enable_gp_runner: bool = True
    gp_allow_subcommands: List[str] = None  # type: ignore
    enable_shell: bool = False


@dataclass
class AssistantConfig:
    workspace_root: Path
    llm: LLMSettings
    rag: RAGSettings
    tools: ToolsSettings
    raw: Dict[str, Any]

    @classmethod
    def load(cls, path: str = "configs/assistant.yaml") -> "AssistantConfig":
        p = Path(path)
        if not p.exists():
            # create a minimal default
            defaults = {
                "workspace_root": ".",
                "llm": {
                    "llm_config_file": "configs/llm.yaml",
                    "temperature": 0.0,
                    "max_tokens": 1200,
                    "timeout": 60,
                    "stream": False,
                },
                "rag": {
                    "index_db": "store/assistant/index.sqlite",
                    "include_globs": [
                        "README.md",
                        "configs/**/*.yaml",
                        "src/**/*.py",
                        "项目计划.txt",
                    ],
                    "exclude_globs": [
                        "data/**",
                        "results/**",
                        "EMQuantAPI_Python/**",
                        "cache/**",
                    ],
                },
                "tools": {
                    "enable_gpbt_runner": True,
                    "gpbt_allow_subcommands": [
                        "init","fetch","build-candidates","build-candidates-range",
                        "doctor","backtest","llm-rank","tune","llm-run","fetch-min5-range","fetch-min5-for-pool"
                    ],
                    "enable_gp_runner": True,
                    "gp_allow_subcommands": ["run","backtest","serve","update"],
                    "enable_shell": False,
                },
            }
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(yaml.safe_dump(defaults, allow_unicode=True, sort_keys=False), encoding="utf-8")
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        llm = raw.get("llm", {})
        rag = raw.get("rag", {})
        tools = raw.get("tools", {})
        return cls(
            workspace_root=Path(raw.get("workspace_root", ".")).resolve(),
            llm=LLMSettings(
                llm_config_file=str(llm.get("llm_config_file", "configs/llm.yaml")),
                temperature=llm.get("temperature"),
                max_tokens=llm.get("max_tokens"),
                timeout=llm.get("timeout"),
                stream=bool(llm.get("stream", False)),
            ),
            rag=RAGSettings(
                index_db=str(rag.get("index_db", "store/assistant/index.sqlite")),
                include_globs=list(rag.get("include_globs", [])),
                exclude_globs=list(rag.get("exclude_globs", [])),
            ),
            tools=ToolsSettings(
                enable_gpbt_runner=bool(tools.get("enable_gpbt_runner", True)),
                gpbt_allow_subcommands=list(tools.get("gpbt_allow_subcommands", [])),
                enable_gp_runner=bool(tools.get("enable_gp_runner", True)),
                gp_allow_subcommands=list(tools.get("gp_allow_subcommands", [])),
                enable_shell=bool(tools.get("enable_shell", False)),
            ),
            raw=raw,
        )

