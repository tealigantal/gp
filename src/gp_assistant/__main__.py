# 简介：包运行入口（python -m gp_assistant）。当前依赖 .cli.main，
# 若未提供 CLI 可忽略该入口。
from .cli import main
import sys


if __name__ == "__main__":
    sys.exit(main())
