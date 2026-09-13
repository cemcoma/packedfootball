PYTHON   ?= python3
GAME_DIR := packedfootball
MAIN     := $(GAME_DIR)/main.py
BUILD_WEB:= $(GAME_DIR)/build/web
WIDTH    := 1280
HEIGHT   := 800
BRANCH   := gh-pages
PAGES_URL:= https://cemcoma.github.io/packedfootball/

.PHONY: build-web deploy-web clean-web

########
#
# DEPRECEATED. THIS WEB BUILD IS FOR THE PYGAME DEMO.
# NEW VERSION IS BUILT ON GODOT.
#
#######

# Build the pygbag web bundle into $(BUILD_WEB).
# --width/--height must match main.py's WINDOW_SIZE or the canvas gets
# stretched to the wrong aspect ratio in the browser.
build-web:
	$(PYTHON) -m pygbag --build --width $(WIDTH) --height $(HEIGHT) $(MAIN)

# Build, then publish $(BUILD_WEB) to the gh-pages branch without touching
# your current branch or working tree (uses a throwaway git worktree).
deploy-web: build-web
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
		git commit -q -m "Deploy web build $$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
		git push -q origin $(BRANCH); \
		echo "Deployed: $(PAGES_URL)"; \
	fi; \
	cd - >/dev/null; \
	git worktree remove --force "$$tmp"

clean-web:
	rm -rf $(GAME_DIR)/build
