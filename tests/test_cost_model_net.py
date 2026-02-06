import json
from pathlib import Path


def test_metrics_net_vs_gross(tmp_path: Path):
    # Simulate a metrics.json written by engine where fees_paid > 0
    strat_dir = tmp_path / 'results' / 'run_x' / 's1'
    strat_dir.mkdir(parents=True, exist_ok=True)
    m = {
        'gross_return': 0.015,
        'net_return': 0.010,
        'turnover': 0.50,
        'fees_paid': 500.0,
    }
    (strat_dir / 'metrics.json').write_text(json.dumps(m), encoding='utf-8')
    obj = json.loads((strat_dir / 'metrics.json').read_text(encoding='utf-8'))
    assert obj['gross_return'] != obj['net_return']

