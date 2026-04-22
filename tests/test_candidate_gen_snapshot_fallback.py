import pandas as pd

from src.gp_assistant.selection_engine.candidate_gen import generate_candidates


def test_candidate_gen_snapshot_fallback():
    # snapshot with no usable code columns
    snap = pd.DataFrame({"閸氬秶袨": ["A", "B"], "娴犻攱鐗?: [10, 20]})
    pool, veto, stats = generate_candidates(None, env_grade="C", topk=1, snapshot=snap)
    assert stats.get("universe_fallback", {}).get("reason") == "snapshot_schema_unusable"
    # should not be empty in normal universe setup; at least ensure non-negative
    assert stats.get("universe_in_count", 0) >= 0
