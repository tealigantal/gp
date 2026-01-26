import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
sys.path.append(str(root))
from gpbt.integrations.deepseek import DeepSeekClient, _load_api_key


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    prompt = sys.argv[1] if len(sys.argv) > 1 else "请只回复：OK"
    # debug
    print('key?', bool(_load_api_key()))
    client = DeepSeekClient()
    text = client.chat([
        {"role": "system", "content": "你是测试助手。"},
        {"role": "user", "content": prompt},
    ], temperature=0.0, max_tokens=64)
    print(text)


if __name__ == "__main__":
    main()
