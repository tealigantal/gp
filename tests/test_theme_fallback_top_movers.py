from __future__ import annotations


def test_theme_pool_impl_is_archived_comments_only():
    import gp_assistant.selection_engine.theme_pool_impl as impl

    assert not hasattr(impl, "build_themes_impl")
