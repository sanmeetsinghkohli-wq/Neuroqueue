# NeuroQueue tasks. On Windows without make, use: ./dev.ps1 <target>
PY ?= .venv/Scripts/python
ifeq ($(wildcard $(PY).exe),)
PY = .venv/bin/python
endif

.PHONY: dev api web test train sim seed
dev:            ## API on :8000 and web on :3000
	$(MAKE) -j2 api web
api:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000
web:
	cd frontend && npm run dev
test:           ## offline test suite (mock mode)
	cd backend && ../$(PY) -m pytest tests -q
train:          ## dedupe, split, train, calibrate, tune thresholds, evaluate, export
	$(PY) -m ml.train
sim:            ## FCFS vs NeuroQueue wait-time simulation
	$(PY) sim/queue_simulation.py
seed:           ## admin + demo doctor + demo patient from backend/.env
	cd backend && ../$(PY) seed.py
