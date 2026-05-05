from __future__ import annotations


def test_theme_concept_module_is_archived_comments_only():
    import gp_assistant.selection_engine.theme_concept as concept

    assert not hasattr(concept, "build_concept_themes")
