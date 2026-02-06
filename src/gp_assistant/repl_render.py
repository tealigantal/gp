from __future__ import annotations
import sys

VERBOSE = False


def set_verbose(enabled: bool) -> None:
    global VERBOSE
    VERBOSE = bool(enabled)


def _prefix_lines(prefix: str, text: str) -> str:
    lines = text.splitlines() or ['']
    return "\n".join([f"{prefix} {ln}" for ln in lines])


def render_user_prompt() -> str:
    return 'user> '


def print_agent(text: str) -> None:
    print(_prefix_lines('agent>', text))


def print_tool(text: str) -> None:
    if VERBOSE:
        sys.stderr.write(_prefix_lines('tool>', text) + "\n")


def print_exec(text: str) -> None:
    if VERBOSE:
        sys.stderr.write(_prefix_lines('exec>', text) + "\n")


def print_warn(text: str) -> None:
    if VERBOSE:
        sys.stderr.write(_prefix_lines('warn>', text) + "\n")
