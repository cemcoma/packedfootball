# Godot web export -- a TEST BUILD ONLY.
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

.PHONY: web serve-web deploy-web clean-web

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
