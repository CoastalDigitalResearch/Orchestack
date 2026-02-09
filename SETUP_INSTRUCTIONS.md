# Orchestack Repository Setup Instructions

These instructions are for Claude Code to execute with `--dangerously-skip-permissions`.

**Context:** The current git repo root is `/home/adam` (the home directory), not `/home/adam/Development/Orchestack`. The GitHub remote `CoastalDigitalResearch/Orchestack` has the wrong directory structure pushed to it. We need to reinitialize Orchestack as a standalone repo and fix the remote.

**GitHub Push Auth:** Use the CDR token from `/home/adam/.keys/CDR/.github-CDR` for pushing. After pushing, replace the remote URL to remove the embedded token.

---

## Step 1: Remove origin remote from home-level git repo

The home-level git repo at `/home/adam` currently has `origin` pointing to CoastalDigitalResearch/Orchestack. Remove it so it doesn't interfere.

```bash
git -C /home/adam remote remove origin
```

## Step 2: Initialize standalone git repo in Orchestack directory

```bash
cd /home/adam/Development/Orchestack
git init
git branch -m main
```

## Step 3: Create .gitignore

Write a `.gitignore` file at `/home/adam/Development/Orchestack/.gitignore` with:

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/

# Go
/vendor/

# Node
node_modules/
package-lock.json

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Secrets - NEVER commit
.env
.env.*
*.pem
*.key

# BMAD output (generated artifacts, not source-controlled by default)
# Uncomment if you want to track planning artifacts:
# _bmad-output/
```

## Step 4: Stage and commit all project files

```bash
cd /home/adam/Development/Orchestack
git add .gitignore
git add TASKS_v1.md
git add Orchestack_Architecture_Response.md
git add Orchestack_RFCs_001-004_Bundle.md
git add Orchestack_RFC-004_Onchain_Trust_and_Payments.md
git add Orchestack_RFC-005_Modularized_Extensibility.md
git add _bmad/
git add .claude/
git add _bmad-output/
git add docs/
git commit -m "$(cat <<'EOF'
Initial commit: RFCs, task list, and BMAD framework

- Architecture Response Document
- RFC-001: Event and State Model (NATS + Postgres + Object Storage)
- RFC-002: Isolation and Policy (OIDC/LDAP + SPIFFE + Vault + Daytona)
- RFC-003: Memory Plane (Hierarchical, File-Based, Cluster-Optimized)
- RFC-004: Onchain Trust and Payments (ERC-8004 + x402)
- RFC-005: Modularized Extensibility Framework
- TASKS_v1.md: Full developer task list (Phase 1 + Phase 2)
- BMAD Method v6 framework installed (agents, workflows, commands)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

## Step 5: Force-push to GitHub (replaces bad repo content)

Read the CDR token from `/home/adam/.keys/CDR/.github-CDR` (trim whitespace), then:

```bash
cd /home/adam/Development/Orchestack
TOKEN=$(cat /home/adam/.keys/CDR/.github-CDR | tr -d '[:space:]')
git remote add origin "https://x-access-token:${TOKEN}@github.com/CoastalDigitalResearch/Orchestack.git"
git push --force -u origin main
git remote set-url origin https://github.com/CoastalDigitalResearch/Orchestack.git
```

## Step 6: Set default branch on GitHub to `main`

```bash
gh api -X PATCH repos/CoastalDigitalResearch/Orchestack \
  -f default_branch=main \
  --header "Authorization: token $(cat /home/adam/.keys/CDR/.github-CDR | tr -d '[:space:]')"
```

Then delete the old `master` branch from remote:

```bash
TOKEN=$(cat /home/adam/.keys/CDR/.github-CDR | tr -d '[:space:]')
git remote set-url origin "https://x-access-token:${TOKEN}@github.com/CoastalDigitalResearch/Orchestack.git"
git push origin --delete master
git remote set-url origin https://github.com/CoastalDigitalResearch/Orchestack.git
```

## Step 7: Create worktree base directory

```bash
mkdir -p /home/adam/Development/Orchestack-worktrees
```

## Step 8: Verify

```bash
cd /home/adam/Development/Orchestack
git log --oneline
git remote -v
git branch -a
```

Expected: single commit on `main`, remote points to CoastalDigitalResearch/Orchestack, no `master` branch.

---

## Worktree Convention (for ongoing development)

When starting work on a task track, create a worktree:

```bash
cd /home/adam/Development/Orchestack
git checkout -b feature/<track-id>-<short-name>
git worktree add /home/adam/Development/Orchestack-worktrees/<track-id>-<short-name> feature/<track-id>-<short-name>
```

Example for Track A-001 (monorepo scaffold):
```bash
git checkout main
git checkout -b feature/A-001-monorepo-scaffold
git worktree add /home/adam/Development/Orchestack-worktrees/A-001-monorepo-scaffold feature/A-001-monorepo-scaffold
```

Parallel worktrees for independent tracks:
```bash
git worktree add /home/adam/Development/Orchestack-worktrees/A-002-envelope-libs feature/A-002-envelope-libs
git worktree add /home/adam/Development/Orchestack-worktrees/G-001-ext-manifest feature/G-001-ext-manifest
git worktree add /home/adam/Development/Orchestack-worktrees/H-001-otel-library feature/H-001-otel-library
```

When a feature is complete:
```bash
cd /home/adam/Development/Orchestack
git worktree remove /home/adam/Development/Orchestack-worktrees/<track-id>-<short-name>
# Then merge via PR or direct merge to main
```

### Branching Convention
- `main` — stable, reviewed code
- `feature/<task-id>-<short-name>` — feature branches per task
- PRs merge feature → main
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Keep commit messages under 72 characters
