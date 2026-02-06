import os
import sys
import subprocess


def main() -> int:
    try:
        subprocess.check_call([sys.executable, 'assistant.py', 'index'])
    except Exception:
        pass
    try:
        subprocess.check_call([sys.executable, 'assistant.py', '--help'])
    except Exception:
        return 1
    try:
        subprocess.check_call([sys.executable, 'assistant.py', 'inspect'])
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

