from gp_assistant.chat import session_store as store
from gp_assistant.chat.slot_resolver import resolve_targets


def test_resolve_ordinal_and_collection():
    sid = store.ensure_session(None)
    # Seed state with active symbols
    store.update_state(sid, {"active_symbols": ["AAA", "BBB", "CCC"]})

    r1 = resolve_targets(sid, "第二只为什么更强")
    assert r1["kind"] == "symbol"
    assert r1["symbol"] == "BBB"

    r2 = resolve_targets(sid, "这三只都重新算")
    assert r2["kind"] == "collection"
    assert r2["symbols"] == ["AAA", "BBB", "CCC"]

    r3 = resolve_targets(sid, "都重新给买点")
    assert r3["kind"] in {"collection", "none"}  # collection when context exists
    if r3["kind"] == "collection":
        assert r3["symbols"] == ["AAA", "BBB", "CCC"]


def test_resolve_focus_pronoun():
    sid = store.ensure_session(None)
    store.set_focus(sid, "ZZZ")
    r = resolve_targets(sid, "这个合理吗")
    assert r["kind"] == "symbol"
    assert r["symbol"] == "ZZZ"

