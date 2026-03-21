def test_strategy_glossary_in_system_prompt():
    from gp_assistant.chat.deepseek_agent import SYSTEM_PROMPT
    # ensure representative entries exist
    assert "策略术语表" in SYSTEM_PROMPT
    assert "s07" in SYSTEM_PROMPT
    assert "NR7" in SYSTEM_PROMPT or "最小实体收缩" in SYSTEM_PROMPT

