#!/usr/bin/env python3
"""Collect git commits + typed chat prompts per local day for a date range.

Output is human/LLM-readable, grouped by day, intended to be summarised into a
worklog. It does NOT summarise — it only gathers the raw signal.
"""
import argparse, json, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

# --- prompt noise filters -------------------------------------------------
SKIP_PREFIXES = (
    "<local-command", "<command-name", "<command-message", "<command-args",
    "Caveat:", "Base directory for this skill", "<system-reminder",
    "[Request interrupted", "[Request cancelled",
)

def is_noise(text):
    t = text.strip()
    if not t:
        return True
    if t.startswith(SKIP_PREFIXES):
        return True
    # local-command stdout wrappers
    if t.startswith("<") and ("command-name" in t[:60] or "local-command" in t[:60]):
        return True
    return False

def user_text(obj):
    """Return typed user text, or None if this is a tool_result / non-text turn."""
    if obj.get("type") != "user":
        return None
    msg = obj.get("message", {})
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        # a turn that contains any tool_result part is a tool response, not typed input
        if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in c):
            return None
        parts = [p.get("text", "") for p in c
                 if isinstance(p, dict) and p.get("type") == "text"]
        return "".join(parts) if parts else None
    return None

def local_date(ts):
    # ts like 2026-06-01T22:47:02.885Z (UTC) -> local date string
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")

def encode_path(p):
    # Claude Code encodes the project dir name by replacing every non-alphanumeric
    # character (/, ., +, …) with "-", not just slashes — must match exactly or
    # paths with dots (GeoBis.Mobile, .claude) or worktrees (feature+741) won't resolve.
    return re.sub(r"[^a-zA-Z0-9]", "-", str(Path(p).resolve()))

def projects_root():
    return Path.home() / ".claude" / "projects"

def git_common_dir(path):
    """Absolute .git common dir for `path`, or None. All worktrees of one repo
    share this value, so it's a casing-/location-proof identity for the repo."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--git-common-dir"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    if not out:
        return None
    # `out` is relative to `path` (e.g. ".git") for the main checkout and
    # absolute for linked worktrees; os.path.join keeps absolute paths intact.
    return str(Path(os.path.join(str(path), out)).resolve())

def git_worktree_paths(project_root):
    """Paths of worktrees git currently knows about (incl. ones living outside
    the repo tree). Trusted directly — git already vouches for them."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(project_root), "worktree", "list", "--porcelain"],
            text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        return []
    return [ln[len("worktree "):].strip()
            for ln in out.splitlines() if ln.startswith("worktree ")]

def recorded_cwd(jsonl_dir):
    """The cwd a session dir's history was recorded in (first record carrying
    one). Used to verify which repo/worktree a dir actually belongs to, since
    the encoded dir NAME is lossy (repo/x and repo-x collide) and case-variant."""
    for jf in sorted(jsonl_dir.glob("*.jsonl")):
        try:
            with jf.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i > 50:            # cwd appears in the opening records
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cwd = json.loads(line).get("cwd")
                    except json.JSONDecodeError:
                        continue
                    if cwd:
                        return cwd
        except OSError:
            continue
    return None

def _same_repo(cwd, root, root_common):
    """Does a recorded cwd belong to the repo at `root`?"""
    cwd_path = Path(cwd)
    if cwd_path.exists() and root_common:
        gc = git_common_dir(cwd_path)
        if gc is not None:
            return gc == root_common      # definitive — survives casing/relocation
    # cwd gone (deleted worktree) or git unavailable: best-effort path containment
    c = str(cwd_path).rstrip("/").lower()
    r = str(root).rstrip("/").lower()
    return c == r or c.startswith(r + "/")

def session_dirs_for(project_root):
    """All ~/.claude/projects/* dirs holding chat history for this repo and any
    of its worktrees, as a deduped list. Union of two sources:
      1. prefix-glob on the encoded repo path (catches the main checkout plus
         worktrees nested in the repo — e.g. .claude/worktrees/… — including
         ones since deleted), each VERIFIED against its recorded cwd; and
      2. `git worktree list` (catches currently-existing worktrees stored
         outside the repo tree that the prefix can't reach).
    Known gap: a worktree that lived OUTSIDE the repo tree AND was deleted before
    runtime is unrecoverable — its dir shares no prefix and git no longer lists it.
    """
    root = Path(project_root).resolve()
    pr = projects_root()
    root_common = git_common_dir(root)
    found = {}  # resolved dir path -> dir (dedupes the two sources)

    # source 1: prefix-glob, then verify by recorded cwd (name alone is untrusted)
    enc_low = encode_path(root).lower()
    if pr.is_dir():
        for d in pr.iterdir():
            if not d.is_dir():
                continue
            n = d.name.lower()
            if n != enc_low and not n.startswith(enc_low + "-"):
                continue
            cwd = recorded_cwd(d)
            if cwd is not None and _same_repo(cwd, root, root_common):
                found[d.resolve()] = d

    # source 2: worktrees git currently knows about (trusted, may be external)
    for wt in git_worktree_paths(root):
        d = pr / encode_path(wt)
        if d.is_dir():
            found[d.resolve()] = d

    return sorted(found.values(), key=lambda p: p.name)

def collect_prompts(jsonl_dirs, dfrom, dto):
    days = {}
    if not jsonl_dirs:
        return days, "(no chat history dirs found for this repo)"
    for jsonl_dir in jsonl_dirs:
        if not jsonl_dir.is_dir():
            continue
        for jf in sorted(jsonl_dir.glob("*.jsonl")):
            try:
                fh = jf.open(encoding="utf-8")
            except OSError:
                continue
            with fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = obj.get("timestamp", "")
                    if not ts:
                        continue
                    txt = user_text(obj)
                    if txt is None or is_noise(txt):
                        continue
                    try:
                        day, hm = local_date(ts)
                    except ValueError:
                        continue
                    if day < dfrom or day > dto:
                        continue
                    snippet = " ".join(txt.split())
                    if len(snippet) > 280:
                        snippet = snippet[:280] + " …[truncated]"
                    days.setdefault(day, []).append((hm, jf.name, snippet))
    for d in days:
        days[d].sort()
    return days, None

def current_git_author(project_root):
    """Return the current git user's email (preferred) or name, or None."""
    for key in ("user.email", "user.name"):
        try:
            val = subprocess.check_output(
                ["git", "-C", str(project_root), "config", key],
                text=True, stderr=subprocess.DEVNULL).strip()
            if val:
                return val
        except subprocess.CalledProcessError:
            continue
    return None

def collect_commits(project_root, dfrom, dto, authors):
    days = {}
    cmd = ["git", "-C", str(project_root), "log",
           "--since", f"{dfrom} 00:00", "--until", f"{dto} 23:59",
           "--date=format-local:%Y-%m-%d|%H:%M",
           "--pretty=format:%cd|%h|%s"]
    if authors:
        # Each --author matches against both author name and email (regex);
        # multiple --author values are OR'd by git. --use-mailmap so .mailmap
        # aliases of the same person are included.
        cmd.append("--use-mailmap")
        cmd += [f"--author={a}" for a in authors]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return days
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        day, hm, h, subj = parts
        if day < dfrom or day > dto:
            continue
        days.setdefault(day, []).append((hm, h, subj))
    for d in days:
        days[d].sort()
    return days

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", required=True)
    ap.add_argument("--to", dest="dto", required=True)
    ap.add_argument("--project-root", default=None)
    ap.add_argument("--authors", nargs="+", default=None, metavar="AUTHOR",
                    help="only include commits by these authors (name or email "
                         "regex; space-separated, OR'd together); "
                         "default: current git user")
    ap.add_argument("--all-authors", action="store_true",
                    help="include commits from everyone, not just the current user")
    args = ap.parse_args()

    root = args.project_root
    if not root:
        try:
            root = subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:
            root = os.getcwd()

    if args.all_authors:
        authors = None
    elif args.authors:
        authors = args.authors
    else:
        cur = current_git_author(root)
        authors = [cur] if cur else None

    jsonl_dirs = session_dirs_for(root)
    prompts, warn = collect_prompts(jsonl_dirs, args.dfrom, args.dto)
    commits = collect_commits(root, args.dfrom, args.dto, authors)

    all_days = sorted(set(prompts) | set(commits))
    print(f"# Raw signal {args.dfrom} … {args.dto}")
    print(f"# project root: {root}")
    if jsonl_dirs:
        print(f"# chat history ({len(jsonl_dirs)} worktree dir(s)):")
        for d in jsonl_dirs:
            print(f"#   {d}")
    else:
        print("# chat history: (none found)")
    if args.all_authors:
        print("# commit author filter: ALL authors")
    elif authors:
        print(f"# commit author filter: {', '.join(authors)}")
    else:
        print("# commit author filter: NONE (could not resolve current git user)")
    if warn:
        print(f"# WARNING {warn}")
    if not all_days:
        print("\n(no commits or chat prompts in range)")
        return
    for d in all_days:
        cs = commits.get(d, [])
        ps = prompts.get(d, [])
        flag = "" if (cs or ps) else "  [EMPTY]"
        print(f"\n## {d}{flag}")
        print(f"### commits ({len(cs)})")
        for hm, h, subj in cs:
            print(f"  {hm} {h} {subj}")
        print(f"### typed prompts ({len(ps)})")
        for hm, fn, snip in ps:
            print(f"  {hm} | {snip}")

if __name__ == "__main__":
    main()
