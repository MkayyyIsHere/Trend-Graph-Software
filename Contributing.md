# Contributing guide

## Branch rules

| Branch | Purpose | Who pushes here |
|---|---|---|
| `main` | Stable release. Every commit = a new .exe | Nobody directly — merge only via PR from develop |
| `develop` | Shared WIP. Internal testing happens here | Team members via PR from feature branches |
| `feature/<your-name>-<topic>` | Your personal sandbox | You only |

## Day-to-day workflow

### Starting new work
```bash
git checkout develop
git pull origin develop          # always sync first
git checkout -b feature/myname-new-chart
```

### Saving your work
```bash
git add .
git commit -m "short description of what you did"
git push origin feature/myname-new-chart
```

### Merging your work into develop
1. Go to GitHub → Pull Requests → New Pull Request
2. base: `develop`  ←  compare: `feature/myname-new-chart`
3. Add a short description, request review from a teammate
4. Merge after approval

### Releasing a new version (maintainer only)
1. Update `version.txt`  (e.g. 1.0.0 → 1.1.0)
2. Update `CHANGELOG.md` with what changed
3. Commit: `git commit -m "release v1.1.0"`
4. Open PR: `develop` → `main`, get approval, merge
5. Tag the release:
   ```bash
   git checkout main
   git pull origin main
   git tag v1.1.0
   git push origin v1.1.0
   ```
6. Run `python build.py`
7. Upload `8_dist/TrendGraph_v1.1.0.exe` to SharePoint:
   - Copy into `Releases/latest/` (overwrite previous)
   - Copy into `Releases/archive/v1.1.0/` (keep for rollback)
   - Update `CHANGELOG.txt` in SharePoint

## Commit message style
Keep it short and factual:
- `add voltage chart export`
- `fix frequency axis label bug`
- `update batch profile config`

Do not write: `changed stuff`, `updates`, `fix`