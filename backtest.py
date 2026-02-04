import sys
import runpy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

if __name__ == '__main__':
    # Equivalent of: gp backtest --strategy S1 --start --end
    runpy.run_module('gp.cli', run_name='__main__')

