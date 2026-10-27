.PHONY: up down logs ps check reset dev dev-web dev-mock dev-deep-demo dev-memory-write dev-memory-read dev-memory dev-mock-window dev-mock-summary dev-stop dev-status
up:
	./scripts/start.sh
down:
	./scripts/compose.sh down
logs:
	./scripts/compose.sh logs -f --tail=100
ps:
	./scripts/compose.sh ps
check:
	./scripts/compose.sh config --quiet
	python3 scripts/acceptance.py
reset:
	./scripts/reset.sh
dev:
	python3 scripts/dev.py start real
dev-web:
	python3 scripts/dev.py start web
dev-mock:
	python3 scripts/dev.py start mock
dev-deep-demo:
	python3 scripts/dev.py start deep-demo
.PHONY: dev-deep-skills-demo
dev-deep-skills-demo:
	python3 scripts/skills_demo.py
dev-memory-write:
	python3 scripts/dev.py start memory-write
dev-memory-read:
	python3 scripts/dev.py start memory-read
dev-memory:
	python3 scripts/dev.py start memory
dev-mock-window:
	python3 scripts/dev.py start mock-window
dev-mock-summary:
	python3 scripts/dev.py start mock-summary
dev-stop:
	python3 scripts/dev.py stop
dev-status:
	python3 scripts/dev.py status

.PHONY: dev-deep-review-demo
dev-deep-review-demo:
	python3 scripts/review_demo.py

.PHONY: obs-lab-smoke obs-lab-phase-a
OBS_LAB_ENV ?= $(CURDIR)/.env
obs-lab-smoke:
	server/.venv/bin/python scripts/obs_lab.py --env-file "$(OBS_LAB_ENV)" --max-runs 1
obs-lab-phase-a:
	server/.venv/bin/python scripts/obs_lab.py --env-file "$(OBS_LAB_ENV)" --scenarios S01 S02 S03 --repeats 1 --max-runs 3
