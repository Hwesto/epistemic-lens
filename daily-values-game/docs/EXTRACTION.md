# Extracting this into its own repository

This scaffold lives under `daily-values-game/` inside the `epistemic-lens` repo
only because the session that created it could not provision a standalone GitHub
repo (the integration token lacked repo-creation permission and pushes were proxy-
locked to `epistemic-lens`). It is self-contained and meant to be lifted out.

## Option A — fresh repo, preserve history (recommended)

```bash
# from a full clone of epistemic-lens
git subtree split --prefix=daily-values-game -b daily-values-game-only

# create the empty repo on github.com first (private), then:
git clone <this-repo> dvg && cd dvg
git checkout daily-values-game-only
git remote add dvg git@github.com:<you>/daily-values-game.git
git push dvg daily-values-game-only:main
```

## Option B — clean start, drop history

```bash
cp -r daily-values-game /path/to/daily-values-game
cd /path/to/daily-values-game
git init && git add . && git commit -m "Initial import: v1 foundation scaffold"
git remote add origin git@github.com:<you>/daily-values-game.git
git push -u origin main
```

After extraction, delete `daily-values-game/` from `epistemic-lens` so the two
projects don't drift.
