try:
 import pytest
 print('pytest_ok')
except Exception as e:
 print('pytest_import_error:', e)
