import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
sys.path.append(str(root))
from gpbt.integrations.deepseek import DeepSeekClient


titles = [
    "关于公司回购股份的进展公告",
    "关于收到立案调查通知书的公告",
    "关于持股5%以上股东减持计划的公告",
    "关于股票交易异常波动的公告",
    "关于签订重大合同的公告",
    "关于控股股东增持公司股份的公告",
]

prompt = (
    "请将以下公告标题逐条做情绪判定与打分。"
    "要求：仅输出JSON数组；每个元素包含title,label,score；label取positive/neutral/negative，score取-1到1；"
    "严格原样回显title（不要改变或转码title中的字符）。\n\n"
    + "\n".join(titles)
)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # 强制UTF-8输出
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    client = DeepSeekClient()
    text = client.chat([
        {"role": "system", "content": "你是量化助手。"},
        {"role": "user", "content": prompt},
    ], temperature=0.0, max_tokens=800)
    # 按用户要求：不做任何兜底或规则处理，直接输出模型原始回复
    print(text)


if __name__ == "__main__":
    main()
