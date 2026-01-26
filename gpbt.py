import sys
import runpy
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

if __name__ == '__main__':
    runpy.run_module('gpbt.cli', run_name='__main__')

