"""End-to-end test of the factory scripts in a throwaway repo.

GitHub is faked (the job module's gh() is replaced in-process); git, the
worktree, the gate, checks.sh, locking, ports and cost are all real. It covers
the Windows port (line endings, UTF-8, msvcrt locks, Git Bash, paths, ports)
and the no-merge rule: the factory has no merge command, the approver only
recommends, and a job reaches `merged` only when a person merges its PR.

Run from anywhere:  python3 -X utf8 factory/tests/run_test.py [<sandbox dir>]
Exit 0 when every check passes.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]  # the folder holding factory/
BOX = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="factory-test-"))
ok = fail = 0


def find_bash():
    """Git Bash on Windows (never System32's WSL bash); plain bash elsewhere."""
    if os.name != "nt":
        return "bash"
    exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip()
    candidate = Path(exec_path).parents[2] / "bin" / "bash.exe"
    if candidate.exists():
        return str(candidate)
    sys.exit("Git Bash not found")


BASH = find_bash()


def check(name, cond, detail=""):
    global ok, fail
    ok += bool(cond)
    fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"\n     {detail}"))


def sh(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


# ---- sandbox: bare origin + project checkout with the factory installed ----
if BOX.exists():
    shutil.rmtree(BOX, ignore_errors=True)
BOX.mkdir(parents=True)
origin, proj = BOX / "origin.git", BOX / "project"
sh(["git", "init", "-q", "--bare", "-b", "main", str(origin)], BOX)
sh(["git", "clone", "-q", str(origin), str(proj)], BOX)
for rel in ["factory/bin/job", "factory/bin/gate", "factory/bin/route", "factory/bin/port",
            "factory/config.json", "factory/.gitattributes"]:
    (proj / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / rel, proj / rel)
(proj / "factory/checks.sh").write_text(
    '#!/usr/bin/env bash\nset -euo pipefail\n'
    'echo "checks ok ✓ ünïcode"\n'
    'if [ -f FAIL_CHECKS ]; then echo "lint failed ✗"; exit 1; fi\n', encoding="utf-8", newline="\n")
(proj / ".gitignore").write_text("/factory/jobs/\n/.worktrees/\n")
(proj / "app.txt").write_text("hello\n")
sh(["git", "add", "-A"], proj)
sh(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], proj)
sh(["git", "push", "-q", "origin", "main"], proj)
check("LF endings kept in copied scripts", b"\r\n" not in (proj / "factory/bin/job").read_bytes())

env = dict(os.environ, CLAUDE_CONFIG_DIR=str(BOX / "claude-config"))

# ---- 1. scripts run by path from Git Bash (shebang -S python3 -X utf8) ----
r = sh([BASH, "-lc", "factory/bin/job --help | head -1; factory/bin/port pid 1; echo rc=$?"], proj, env=env)
check("job runs via shebang in Git Bash", "The only writer" in r.stdout, r.stdout + r.stderr)
check("port runs via shebang", "rc=0" in r.stdout, r.stdout + r.stderr)
r = sh([BASH, "-lc", "factory/bin/job summary"], proj, env=env)
check("job summary with no jobs", r.returncode == 0 and "total $0.00" in r.stdout, r.stdout + r.stderr)
r = sh([BASH, "-lc", "factory/bin/job --help"], proj, env=env)
check("usage lists no merge command", "job merge" not in r.stdout and "never merges" in r.stdout, r.stdout)

# ---- load job in-process with a fake gh ----
loader = importlib.machinery.SourceFileLoader("factory_job", str(proj / "factory/bin/job"))
spec = importlib.util.spec_from_loader("factory_job", loader)
job = importlib.util.module_from_spec(spec)
loader.exec_module(job)
check("job imports without fcntl on Windows", job.WINDOWS is (os.name == "nt"))
check("no merge stage or command in the state machine",
      "merging" not in job.TRANSITIONS and job.TRANSITIONS["approve"] == {"needs-human"}
      and not hasattr(job, "cmd_merge"), job.TRANSITIONS)

ISSUE = {"number": 15, "title": "Add a dark/light théme toggle ☀", "body": "Sun/moon button — saves choice 🌙",
         "author": {"login": "someone"}, "labels": [{"name": "factory"}], "state": "OPEN",
         "url": "https://github.com/o/r/issues/15", "comments": []}
gh_calls, pr_state = [], {"state": "OPEN"}


def fake_gh(*args):
    gh_calls.append(args)
    if args[:2] == ("api", "user"):
        return "someone\n"
    if args[:2] == ("issue", "view"):
        return json.dumps(ISSUE)
    if args[:2] == ("pr", "list"):
        return json.dumps([{"number": 7, "url": "https://github.com/o/r/pull/7"}])
    if args[:2] == ("pr", "view"):
        return json.dumps({"state": pr_state["state"], "isDraft": False})
    return ""


job.gh = fake_gh
_main = job.main


def jmain(argv):
    """Run a job command in-process like a real process: return its exit code,
    then drop its locks the way a process exit would."""
    try:
        _main(argv)
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    finally:
        for f in job._locks.values():
            f.close()
        job._locks.clear()


os.chdir(proj)

# ---- 2. create → issue.md with non-ASCII text ----
jmain(["create", "15"])
jid = next(p.name for p in (proj / "factory/jobs").iterdir())
jd = proj / "factory/jobs" / jid
check("create: job id", jid == "001-add-a-dark-light", jid)
check("create: issue.md keeps unicode", "théme toggle ☀" in (jd / "issue.md").read_text(encoding="utf-8"))
wt = json.loads((jd / "job.json").read_text())["worktree"]
check("worktree path uses forward slashes", "\\" not in wt and wt.endswith("/.worktrees/" + jid), wt)

# ---- 3. route via shebang → calls job sync/agents through sys.executable ----
(jd / "intake.md").write_text("DECISION: ACCEPT\nRESCOPED: no\nRISK: low\nSURFACES: ui\n\nGood idea — build it.\n",
                              encoding="utf-8")
r = sh([BASH, "-lc", f"factory/bin/route {jid}"], proj, env=env)
check("route runs and records reviewers", r.returncode == 0 and "reviewers code haiku, ux sonnet, ui haiku" in r.stdout,
      r.stdout + r.stderr)

# ---- 4. advance → spec creates the real worktree from origin/main ----
jmain(["advance", jid, "spec"])
check("advance spec: worktree created", Path(wt).is_dir() and (Path(wt) / "app.txt").exists(), wt)
(jd / "spec.md").write_text("# Spec\n")
jmain(["advance", jid, "build"])

# builder's work in the worktree: commit + push, build.md READY
(Path(wt) / "app.txt").write_text("hello, dark mode 🌙\n", encoding="utf-8")
sh(["git", "add", "-A"], wt)
sh(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "theme"], wt)
sh(["git", "push", "-q", "-u", "origin", f"factory/{jid}"], wt)
(jd / "build.md").write_text("STATUS: READY\n\nDone.\n")
jmain(["advance", jid, "gate"])
check("advance gate: PR found", json.loads((jd / "job.json").read_text())["pr"] == 7)

# ---- 5. gate via shebang: Git Bash runs checks.sh, unicode output ----
r = sh([BASH, "-lc", f"factory/bin/gate {jid}"], proj, env=env)
checks_md = (jd / "round-1/checks.md").read_text(encoding="utf-8")
check("gate PASS", r.returncode == 0 and "GATE: PASS" in r.stdout, r.stdout + r.stderr)
check("gate log keeps unicode", "checks ok ✓ ünïcode" in checks_md)
r = sh([BASH, "-lc", f"factory/bin/gate {jid} --merge"], proj, env=env)
check("gate has no --merge mode", r.returncode != 0 and not (jd / "round-1/merge-checks.md").exists(),
      r.stdout + r.stderr)

# ---- 6. builder Stop hook, run the way Claude Code runs it, with a Windows-style project dir ----
transcript = BOX / "transcript.jsonl"
transcript.write_text(json.dumps({"message": {"content": f"Job: {jid}. Job folder: x/. Build round 1."}}) + "\n")
event = json.dumps({"stop_hook_active": False, "agent_transcript_path": str(transcript)})
hook_env = dict(env, CLAUDE_PROJECT_DIR=str(proj))  # backslashes, like Claude Code on Windows
hook_cmd = '"$CLAUDE_PROJECT_DIR"/factory/bin/gate --hook'
r = subprocess.run([BASH, "-c", hook_cmd], input=event, capture_output=True, text=True, env=hook_env, cwd=proj)
check("hook passes when checks pass", r.returncode == 0, f"rc={r.returncode} {r.stdout}{r.stderr}")
(Path(wt) / "FAIL_CHECKS").write_text("x")
r = subprocess.run([BASH, "-c", hook_cmd], input=event, capture_output=True, text=True, env=hook_env, cwd=proj)
check("hook blocks (exit 2) when checks fail", r.returncode == 2 and "lint failed ✗" in r.stderr,
      f"rc={r.returncode} {r.stderr[-300:]}")
r = sh([BASH, "-lc", f"factory/bin/gate {jid}"], proj, env=env)
check("gate FAIL on failing checks", r.returncode == 1 and "GATE: FAIL" in r.stdout, r.stdout + r.stderr)
(Path(wt) / "FAIL_CHECKS").unlink()
sh([BASH, "-lc", f"factory/bin/gate {jid}"], proj, env=env)

# ---- 7. lock: a second process waits while the first holds the job ----
holder = subprocess.Popen([sys.executable, "-X", "utf8", "-c",
    "import importlib.machinery,importlib.util,sys,time;"
    f"l=importlib.machinery.SourceFileLoader('j',r'{proj / 'factory/bin/job'}');"
    "s=importlib.util.spec_from_loader('j',l);m=importlib.util.module_from_spec(s);l.exec_module(m);"
    f"m.load('{jid}');print('locked',flush=True);time.sleep(4)"], stdout=subprocess.PIPE, text=True)
holder.stdout.readline()
t = time.monotonic()
r = sh([BASH, "-lc", f"factory/bin/job sync {jid}"], proj, env=env)
waited = time.monotonic() - t
holder.wait()
check(f"lock: second process waited for the first ({waited:.1f}s)", waited >= 2.5 and r.returncode == 0,
      r.stdout + r.stderr)

# ---- 8. cost: transcript written with git-style path (c:/..., forward slashes) ----
proj_key = "".join(c if c.isalnum() else "-" for c in str(job.REPO))
sub = BOX / "claude-config/projects" / proj_key / "sess1/subagents"
sub.mkdir(parents=True)
folder = (jd.as_posix()[0].lower() + jd.as_posix()[1:]) + "/"
(sub / "agent-1.jsonl").write_text(
    json.dumps({"message": {"content": f"Job: {jid}. Job folder: {folder}. Main checkout: x."}}) + "\n"
    + json.dumps({"type": "assistant", "message": {"id": "m1", "model": "claude-haiku-5-5",
                  "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}}) + "\n"
    + json.dumps({"type": "user", "message": {"content": "non-cp1252 bytes: \u0081 \u2192 ✓"}}) + "\n",
    encoding="utf-8")
r = sh([sys.executable, str(proj / "factory/bin/job"), "summary", jid], proj, env=env)  # no -X utf8
check("cost found from a UTF-8 transcript, even without -X utf8 ($0.10)", "$0.10" in r.stdout, r.stdout + r.stderr)

# ---- 9. no merge: reviews pass, the approver recommends, the job waits for a person ----
check("advance review", jmain(["advance", jid, "review"]) == 0)
for reviewer in ("code", "ux", "ui"):
    (jd / f"round-1/review-{reviewer}.md").write_text("VERDICT: PASS\n\n## Summary\n- fine\n")
check("advance approve", jmain(["advance", jid, "approve"]) == 0)
check("approve → merging is illegal", jmain(["advance", jid, "merging"]) != 0)
(jd / "decision.md").write_text("APPROVE\n\n## Summary\n- old verdict\n")
check("an APPROVE verdict is refused (READY or ESCALATE only)", jmain(["advance", jid, "needs-human"]) != 0)
(jd / "decision.md").write_text("READY\n\n## Summary\n- would merge it\n\n## For the human\nLook at app.txt.\n")
gh_calls.clear()
check("READY → needs-human", jmain(["advance", jid, "needs-human"]) == 0
      and json.loads((jd / "job.json").read_text())["stage"] == "needs-human")
pr_comments = [c for c in gh_calls if c[:2] == ("pr", "comment")]
check("READY posts 'ready for your review' on the PR",
      pr_comments and "ready for your review (you merge)" in pr_comments[0][-1], gh_calls)
check("no gh pr merge was called", not any(c[:2] == ("pr", "merge") for c in gh_calls), gh_calls)
r = sh([BASH, "-lc", f"factory/bin/job merge {jid}"], proj, env=env)
check("`job merge` is refused as bad arguments", r.returncode != 0 and "bad arguments" in r.stderr,
      r.stdout + r.stderr)

# ---- 10. a person merges on GitHub: the job's dev server is stopped, then the worktree removed ----
port = 5100 + 10 * 1
server = subprocess.Popen([sys.executable, "-m", "http.server", str(port)], cwd=wt,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
r = sh([BASH, "-lc", f"factory/bin/port pid {port}"], proj, env=env)
# python3 may be a launcher: the listener can be its child process, not server.pid
check("port pid finds the dev server", r.returncode == 0 and r.stdout.split(), r.stdout + r.stderr)
pr_state["state"] = "MERGED"
jmain(["advance", jid, "merged"])
server.wait(timeout=10)
stage = json.loads((jd / "job.json").read_text())["stage"]
check("merged by a person: job stage", stage == "merged", stage)
check("merged: needs-human label removed",
      any(c[:2] == ("issue", "edit") and "--remove-label" in c for c in gh_calls), gh_calls)
check("merged: dev server stopped", server.poll() is not None)
check("merged: worktree removed", not Path(wt).exists(), wt)

os.chdir(BOX)
print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
