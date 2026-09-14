# Two things live here: 
# the Python engine test suite (make test) and 
# the Godot web export (make web).
#
# --- Engine tests ----------------------------------------------------------
#
#   make test          everything (~3 min -- 35 of these simulate whole
#                      matches, the only honest way to test an engine)
#   make test-fast     108 tests, ~3s. Everything except those simulations,
#                      which is what you want while editing.
#   make test-slow     only the full-match simulations, stdout shown
#   make test-gap      icon XI vs bronze XI, prints the scoreline table
#   make test-one T=tests/test_goalkeeper.py            one file
#   make test-one T=tests/test_goalkeeper.py::test_name one test
#   make test-k K=keeper                                by name substring
#   make sim                    10 matches, prints the shooting/keeper table
#   make sim MATCHES=30 SEED=5  more matches, different seeds
#
# `sim` is the calibration harness, not a test: it prints shots, shots on
# target, save rate, goals and how long the ball spends airborne, which is
# what the balance constants in gameEngine.py are tuned against.
#
# --- Godot web export -- a TEST BUILD ONLY.
#
# Real-money purchases are deliberately absent on web: there is no
# RevenueCat (or any other) payment path on that platform, so the Shop's
# Cash tab hides itself when OS.has_feature("web") is true (see
# mobile/scripts/components/CurrencyPanel.gd). Everything else is
# backend-driven and behaves the same as on device -- packs, matches,
# squad, deals, leaderboards.
#
# The export preset is "Web" in mobile/export_presets.cfg, with
# thread_support disabled on purpose: threaded Godot web builds need
# cross-origin isolation (COOP/COEP response headers) for SharedArrayBuffer,
# and GitHub Pages cannot set headers. Leave it off or the deployed page
# will fail to boot.

GODOT      ?= /Users/cemtarkantekcan/Desktop/Godot.app/Contents/MacOS/Godot
MOBILE_DIR := mobile
PRESET     := Web
BUILD_WEB  := $(MOBILE_DIR)/build/web
PORT       ?= 8060
BRANCH     := gh-pages
PAGES_URL  := https://cemcoma.github.io/packedfootball/

PYTHON  ?= python3
PYTEST  := $(PYTHON) -m pytest
MATCHES ?= 10
SEED    ?= 1

.PHONY: test test-fast test-slow test-gap test-one test-k sim \
        web serve-web deploy-web clean-web

## Everything. Config (testpaths, sys.path) comes from pytest.ini.
test:
	$(PYTEST)

## Skip anything marked `slow` -- i.e. every test that simulates full matches.
test-fast:
	$(PYTEST) -m "not slow"

## Only the full-match simulations. -s so their printed summaries show up.
test-slow:
	$(PYTEST) -m slow -s

## Icon XI vs bronze XI. The printed table is the point, hence -s.
test-gap:
	$(PYTEST) -s tests/test_quality_gap.py

## One file, or one test: make test-one T=tests/test_goalkeeper.py::test_name
test-one:
	@test -n "$(T)" || { echo 'usage: make test-one T=tests/test_goalkeeper.py[::test_name]'; exit 1; }
	$(PYTEST) -s $(T)

## Every test whose name contains K: make test-k K=save
test-k:
	@test -n "$(K)" || { echo 'usage: make test-k K=<name substring>'; exit 1; }
	$(PYTEST) -s -k "$(K)"

## Balance harness -- simulate matches and print the shooting/keeper table.
sim:
	$(PYTHON) packedfootball/scripts/simulate_matches.py --matches $(MATCHES) --seed $(SEED)

## Export the Godot client to $(BUILD_WEB).
# --headless so it never opens the editor window. Godot creates the output
# directory itself, but not reliably on a first run, so mkdir -p first.
web:
	@test -x "$(GODOT)" || { \
		echo "Godot binary not found at: $(GODOT)"; \
		echo "Override it, e.g.: make web GODOT=/path/to/Godot.app/Contents/MacOS/Godot"; \
		exit 1; \
	}
	mkdir -p $(BUILD_WEB)
	"$(GODOT)" --headless --path $(MOBILE_DIR) --export-release "$(PRESET)" build/web/index.html
	@touch $(BUILD_WEB)/.nojekyll
	@echo "Exported to $(BUILD_WEB)"

## Serve the export locally -- a Godot web build cannot run from file://.
serve-web: web
	@echo "Serving $(BUILD_WEB) at http://localhost:$(PORT)/  (ctrl-c to stop)"
	@cd $(BUILD_WEB) && python3 -m http.server $(PORT)

## Build, then publish $(BUILD_WEB) to the gh-pages branch without touching
## your current branch or working tree (uses a throwaway git worktree).
deploy-web: web
	@set -e; \
	tmp=$$(mktemp -d); \
	git fetch origin $(BRANCH) >/dev/null 2>&1 || true; \
	if git show-ref --verify --quiet refs/remotes/origin/$(BRANCH); then \
		git worktree add --quiet "$$tmp" $(BRANCH) >/dev/null; \
	else \
		git worktree add --quiet "$$tmp" main --detach >/dev/null; \
		(cd "$$tmp" && git checkout --orphan $(BRANCH) >/dev/null); \
	fi; \
	(cd "$$tmp" && git rm -rf . >/dev/null 2>&1 || true); \
	cp -R $(BUILD_WEB)/. "$$tmp"/; \
	touch "$$tmp/.nojekyll"; \
	cd "$$tmp" && git add -A && \
	if git diff --cached --quiet; then \
		echo "No changes to deploy."; \
	else \
		git commit -q -m "Deploy web test build $$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
		git push -q origin $(BRANCH); \
		echo "Deployed: $(PAGES_URL)"; \
	fi; \
	cd - >/dev/null; \
	git worktree remove --force "$$tmp"

clean-web:
	rm -rf $(MOBILE_DIR)/build
