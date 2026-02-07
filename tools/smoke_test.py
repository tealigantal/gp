"""Minimal smoke tests for the refactored single-entry architecture.

Run with:
  python tools/smoke_test.py
"""
from __future__ import annotations

import json
import subprocess
import sys

from src.gp_assistant.providers.factory import provider_health


def check_health():
    info = provider_health()
    assert "selected" in info and "ok" in info, f"bad health: {info}"
    print("[ok] provider.healthcheck()", json.dumps(info, ensure_ascii=False))


def run_cmd(args: list[str]):
    env = dict(**os.environ)
    # Ensure local run can import from src without installation
    env["PYTHONPATH"] = (env.get("PYTHONPATH", "") + (";" if os.name == "nt" else ":") + "src").strip(";:")
    proc = subprocess.run([sys.executable, "-m", "gp_assistant", *args], capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def check_data():
    code, out, err = run_cmd(["data", "--symbol", "000001"])
    # Should not crash; either ok or readable error
    assert code in (0, 1), f"unexpected code: {code}"
    assert out, "no output"
    print("[ok] gp data --symbol 000001", out)


def check_pick():
    code, out, err = run_cmd(["pick"])
    assert code in (0, 1)
    assert out
    print("[ok] gp pick", out)


def main():
    check_health()
    check_data()
    check_pick()
    print("Smoke tests completed.")


if __name__ == "__main__":
    main()
