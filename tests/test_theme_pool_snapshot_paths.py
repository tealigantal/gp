from __future__ import annotations


def test_theme_pool_module_is_archived_comments_only():
    import gp_assistant.selection_engine.theme_pool as pool

    assert not hasattr(pool, "build_themes")
