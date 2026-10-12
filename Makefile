.PHONY: up down logs ps check reset dev dev-web dev-stop dev-status
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
	python3 scripts/dev.py start full
dev-web:
	python3 scripts/dev.py start web
dev-stop:
	python3 scripts/dev.py stop
dev-status:
	python3 scripts/dev.py status
