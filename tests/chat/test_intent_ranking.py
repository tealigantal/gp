from gp_assistant.chat.intent import detect_intent


def test_ranking_phrases_hit_ranking_explain():
    assert detect_intent('为什么第一只排前面').get('name') == 'ranking_explain'
    assert detect_intent('第二只为什么不是第一只').get('name') == 'ranking_explain'

