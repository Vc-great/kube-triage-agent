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
