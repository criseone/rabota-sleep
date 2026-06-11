# rabota sleep pipeline — shortcuts
# Use the venv's python directly so these work with or without `source .venv/bin/activate`.
PY := .venv/bin/python

# Override the commit message: make publish m="add Friday night"
m := update dashboard

.PHONY: help preview publish log

help:
	@echo "make preview   - build sleep-dashboard.html from REAL data (local only, git-ignored)"
	@echo "make publish   - build anonymized index.html and push it to GitHub Pages"
	@echo "make log       - start the overnight heart-rate logger"
	@echo ""
	@echo "  publish commit message: make publish m=\"your message\""

# Local real-data preview — never committed.
preview:
	$(PY) build_dashboard.py
	@echo "Open sleep-dashboard.html"

# Anonymized hosted build. --out index.html is required or the build writes the
# git-ignored sleep-dashboard.html and the push silently does nothing.
publish:
	$(PY) build_dashboard.py --anonymize --out index.html
	git add index.html
	@if git diff --cached --quiet -- index.html; then \
		echo "index.html already up to date — nothing to publish."; \
	else \
		git commit -m "$(m)" && git push && echo "Published. The hosted dashboard is now up to date."; \
	fi

log:
	./log_sleep.sh
