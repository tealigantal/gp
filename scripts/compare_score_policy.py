"""Read-only frozen-evidence ablation, not a return backtest or new-memory replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import statistics

from gp_assistant.decision_engine.scoring import score_candidate


def summary(values):
    return dict(count=len(values), mean=statistics.mean(values), minimum=min(values),
                maximum=max(values), stddev=statistics.pstdev(values)) if values else dict(count=0)


def compare(database: Path):
    conn = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        plans = [json.loads(row[0]) for row in conn.execute('SELECT payload_json FROM recommendation_plans')]
    finally:
        conn.close()
    daily = {}
    for plan in sorted(plans, key=lambda p: (p['generated_at'], p['plan_id'])):
        if plan['producer']['name'] == 'real_daily_producer' and plan['producer']['revision'] == '2' and plan['evaluated_candidates']:
            daily[plan['market_session_date']] = plan
    rows, old_scores, new_scores = [], [], []
    rejected_selected = 0
    for day, plan in sorted(daily.items()):
        rescored = []
        for c in plan['evaluated_candidates']:
            prob, confidence, risk = c['probability']['probability'], c['probability']['confidence'], c['risk']['score']
            contribution = sum(e['contribution'] for e in c['experts'] if e['expert'] == 'serenity')
            old_execution = (c['adaptive_score'] - contribution - .5*prob - .2*confidence + .2*(1-risk))/.3
            assert -1e-8 <= old_execution <= 1+1e-8, (day,c['symbol'],old_execution)
            physical = max(0., min(1., (old_execution-.2*confidence)/.8))
            factor = prob * old_execution * confidence * risk
            # A zero old product only establishes non-positive edge where all
            # other factors are positive; otherwise its sign is unidentified.
            if factor <= 0:
                raise ValueError('unidentified_expected_return:' + c['symbol'])
            expected = c['ranking']['score']/factor
            result = score_candidate(probability=prob, execution_quality=physical, confidence=confidence,
                drawdown_probability=1-risk, expected_return=expected)
            rescored.append((result['score'],c['symbol'],not result['reason_codes']))
            if c['disposition'] == 'selected':
                old_scores.append(c['adaptive_score']*100)
                rejected_selected += bool(result['reason_codes'])
        # Zero Serenity lane: a changed Top30 would require a new exact batch.
        finalists = sorted(rescored, key=lambda r: (-r[0],r[1]))[:30]
        chosen = [r for r in finalists if r[2] and r[0]>=.5][:3]
        new_scores.extend(r[0]*100 for r in chosen)
        rows.append(dict(day=day,plan_id=plan['plan_id'],scored=len(rescored),
            old_selected=[c['symbol'] for c in plan['evaluated_candidates'] if c['disposition']=='selected'],
            new_selected=[dict(symbol=r[1],score=100*r[0]) for r in chosen]))
    return dict(method='Frozen old probability/confidence/risk; algebraically recover old execution and positive expected return; new physical execution and net-edge gate; zero Serenity lane. No outcomes or new-memory estimates replayed. Not performance acceptance.',
        sessions=len(rows), scored=sum(r['scored'] for r in rows), old_selected=summary(old_scores),
        new_selected=summary(new_scores), old_selected_failing_net_edge=rejected_selected, plans=rows)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    print(json.dumps(compare(parser.parse_args().database),ensure_ascii=False,indent=2,allow_nan=False))
