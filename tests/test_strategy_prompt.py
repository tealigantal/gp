def test_strategy_glossary_in_system_prompt():
    from gp_assistant.chat_compat.deepseek_agent import SYSTEM_PROMPT
    # ensure representative entries exist
    assert "缁涙牜鏆愰張顖濐嚔鐞? in SYSTEM_PROMPT
    assert "s07" in SYSTEM_PROMPT
    assert "NR7" in SYSTEM_PROMPT or "閺堚偓鐏忓繐鐤勬担鎾存暪缂? in SYSTEM_PROMPT
