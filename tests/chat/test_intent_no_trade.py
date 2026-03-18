from gp_assistant.chat.intent import detect_intent


def test_no_trade_phrases_map_to_ask_no_trade_reason():
    cases = [
        "为什么空仓",
        "为什么今天不操作",
        "为什么不行",
        "为什么建议观望",
        "为什么当前建议空仓",
        "为什么不给买",
    ]
    for s in cases:
        got = detect_intent(s)
        assert got.get('name') == 'ask_no_trade_reason', s

