PY=python

.PHONY: test
test:
	$(PY) -m compileall src/gp_assistant
	STRICT_REAL_DATA=0 pytest -q

