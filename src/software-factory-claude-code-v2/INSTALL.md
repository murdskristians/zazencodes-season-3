# Install the software factory

You are a coding agent installing this factory into the user's project. Copy
what's generic, adapt what's repo-specific, verify it, and report. Work in the
project's root. Don't clone this repository.

The source is the folder the user pointed you at. On GitHub, read files from
`https://raw.githubusercontent.com/murdskristians/zazencodes-season-3/main/src/software-factory-claude-code-v2/<path>`.
(This fork adds Windows support to the reference; upstream is
`zazencodes/zazencodes-season-3`.)

## 0. Check the project

Stop and tell the user if any of these fail:

- It's a git repo with an `origin` on GitHub, and `gh auth status` shows a user
  who can push to it and manage its labels.
- Its default branch (`gh repo view --json defaultBranchRef`) exists on
  `origin`.
- `claude --version` is 2.1.257 or later (the intake agent runs on Fable).
- `python3 --version` is 3.10 or later. The scripts use only the standard
  library.
- `agent-browser --version` works. The builder and the UX and UI reviewers look
  at pages with it. If it's missing, ask the user before installing it:
  `npm install -g agent-browser && agent-browser install`.
- **On Windows**, also check these, in Git Bash (the factory's scripts and
  `checks.sh` run under Git Bash, which Claude Code uses there):
  - `python3 --version` prints a version. If it prints "Python was not found",
    the Microsoft Store alias is shadowing Python: run
    `uv python install 3.14 --default` (puts `python3` in `~/.local/bin`), or
    turn off the python aliases in Settings → Apps → Advanced app settings →
    App execution aliases.
  - `/usr/bin/env -S true` succeeds. The scripts' shebang is
    `#!/usr/bin/env -S python3 -X utf8` (UTF-8 mode, so issue text with
    non-ASCII characters can't crash them).
- None of the files in step 1 already exist. If one does, show the user the
  clash and ask before overwriting.

## 1. Copy

Copy these files to the same paths in the project, unchanged:

```
.claude/skills/factory/SKILL.md
.claude/agents/intake.md
.claude/agents/spec-writer.md
.claude/agents/builder.md
.claude/agents/reviewer-code.md
.claude/agents/reviewer-security.md
.claude/agents/reviewer-ux.md
.claude/agents/reviewer-ui.md
.claude/agents/approver.md
factory/config.json
factory/checks.sh
factory/bin/job
factory/bin/gate
factory/bin/route
factory/bin/port
factory/dashboard.html
factory/.gitattributes
```

```bash
SRC=https://raw.githubusercontent.com/zazencodes/zazencodes-season-3/main/src/software-factory-claude-code-v2
for f in <the paths above>; do
  mkdir -p "$(dirname "$f")" && curl -fsSL "$SRC/$f" -o "$f"
done
chmod +x factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route factory/bin/port
git add --chmod=+x factory/checks.sh factory/bin/*   # keeps them executable on Windows too
```

`factory/.gitattributes` keeps the scripts' LF line endings: with
`core.autocrlf=true` (the Git for Windows default) a CRLF shebang or
`set -euo pipefail` breaks under Git Bash.

Don't copy `README.md`, `DESIGN.md`, `INSTALL.md`, `LICENSE`, `examples/` or
`docs/`. They describe the reference, not the user's project.

## 2. Adapt

**`factory/checks.sh`.** Replace the placeholder with the project's real
checks: install dependencies if a fresh worktree needs them, then lint,
typecheck, tests and build, whichever the project has. Find them in
`AGENTS.md`, `CLAUDE.md`, `package.json` scripts, `Makefile`, `pyproject.toml`
and CI config. The script runs with a job's worktree as its working directory.
It must be non-interactive, must not rewrite files (no `--fix`, no
`--update-snapshots`), and must exit non-zero on any failure. Keep
`set -euo pipefail`. Watch for lint scripts that fix by default (e.g.
`"lint": "eslint . --fix"`): call the tool directly without the fix flag
instead (`pnpm exec eslint .`). On Windows the gate runs this script with Git
Bash.

**`factory/config.json`.**

- `base_branch`: the default branch.
- `protected_paths`: keep the two factory entries and don't add the project's
  tests. Features legitimately change existing tests (a new required field
  changes every fixture), and a protected test blocks the job with no way
  through. The code reviewer catches weakened or special-cased tests instead.
  Add a path only when no job should ever change it. They are fnmatch
  patterns, so `*` also matches `/`.
- `ports`: move `base` if the project already uses ports 5100–5199.
- Leave `concurrency`, `max_rounds`, `routing`, `surface_reviewers` and
  `prices_usd_per_mtok` as they are unless the user asks.

**Agents.** The checklists are general on purpose. Tailor them to the stack
without changing their structure, file names, first-line formats or one-line
replies:

- `reviewer-security.md`: this project's hot spots (its auth, its data access
  rules, its payment and webhook code, where user input meets queries or HTML).
- `reviewer-ui.md`: where the design tokens, theme and shared components live.
- `reviewer-ux.md`: the kinds of users the app has.
- `approver.md`: what a human must always see in this project, added to the
  ESCALATE list.
- `intake.md`: one line under **Decide** saying what the project is for, so
  intake can tell what belongs.

**`AGENTS.md`** (or `CLAUDE.md`, whichever the project uses; create `AGENTS.md`
if neither exists). Every agent reads it. Make sure it says:

- how to set up a fresh checkout (install dependencies, env files to copy);
- how to start the dev server on a given port, if the project has one;
- the validation commands, matching `factory/checks.sh`.

Then add a short section:

```markdown
## Software factory

`/factory run` builds every open GitHub issue labeled `factory` through
intake → spec → build → gate → review → approve, one PR per issue. State is in
`factory/jobs/` (gitignored); `factory/bin/job` is its only writer. Checks:
`factory/checks.sh`. Dashboard: `cd factory && python3 -m http.server`, then
open http://localhost:8000/dashboard.html.

Each job works in its own git worktree, a full checkout of the repo at
`.worktrees/<job-id>` (gitignored). A tool run from the repo root that doesn't
read `.gitignore` sees those copies too; exclude `.worktrees/` in its config.
```

**`.gitignore`.** Append these two lines:

```gitignore
/factory/jobs/
/.worktrees/
```

`factory/jobs/` is runtime state (job metadata, specs, reviews, check logs)
local to the machine running the factory. Each job's worktree is a full
checkout in `.worktrees/<job-id>`. Neither belongs in the repo. Everything you
copied in step 1 does: the skill in `.claude/skills/factory/`, the agents in
`.claude/agents/` and the rest of `factory/` are part of the project and get
committed, so ignore only these two paths, never `.claude/` or `factory/`.

**Labels.** Create them on GitHub:

```bash
gh label create factory --color 5319E7 --description "Build this with the software factory"
gh label create factory:needs-info --color FBCA04 --description "The factory asked the author a question"
gh label create factory:needs-human --color D93F0B --description "A person reviews and merges this PR"
```

**No merges.** The factory never merges a PR: its scripts have no merge
command, and a person merges every PR. Make that hold for every agent too. In
`.claude/settings.json` (create it if missing, keep anything already there),
add `"Bash(gh pr merge:*)"` to `permissions.deny`:

```json
{ "permissions": { "deny": ["Bash(gh pr merge:*)"] } }
```

## 3. Verify

1. In the project root, on the current branch, `bash factory/checks.sh` exits 0.
   If it fails there, the factory can never pass a job: fix the
   script (not the project) or tell the user what's broken.
2. `factory/bin/job queue` runs without an error.
3. Each file in `.claude/agents/` has only these frontmatter keys: `name`,
   `description`, `tools`, `model`, and `hooks` on the builder. Claude Code
   ignores unknown keys without a warning, so a typo silently changes behaviour.
4. `python3 -m json.tool factory/config.json` succeeds.
5. On Windows: `file factory/bin/* factory/checks.sh` mentions no "CRLF", and
   `factory/bin/port pid 1` runs without an error.
6. `git check-ignore factory/jobs/x .worktrees/x` prints both paths, and
   `git status --porcelain --untracked-files=all` lists every file from step 1
   (the skill, the agents and `factory/`) as committable.
7. `.claude/settings.json` denies `Bash(gh pr merge:*)`.

## 4. Hand over

Stay on the branch the user is on: don't create or check out another branch.
Commit the install there with a one-line message and show the user the diff.
Ask before pushing: the factory branches every job from `origin/<base_branch>`,
so the install must be on that branch there before the first run.

Then tell the user, in a few lines:

- Label one or two small issues `factory`, then run `/factory run` in Claude
  Code from the project root.
- Every job ends as a PR labeled `factory:needs-human`, with the approver's
  READY or ESCALATE recommendation posted on it. The factory never merges:
  they review the PR and merge it on GitHub, or tell the factory what to
  change with `/factory <anything>`.
- Intake runs on Fable, once per issue. Depending on their plan, Fable can
  bill to usage credits rather than the plan's included usage.
- To start carefully, set `concurrency` to 1 in `factory/config.json` and read
  every PR until they trust it.
