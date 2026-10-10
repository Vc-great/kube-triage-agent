.PHONY: up down logs ps check reset
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
