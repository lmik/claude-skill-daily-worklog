---
name: daily-worklog
description: Use ONLY when the user explicitly invokes /daily-worklog or explicitly asks to generate their daily work documentation / Tagesdokumentation / "doings" for this project from its git and chat history. Never trigger automatically or infer this from unrelated work.
---

# Daily Worklog (Tagesdokumentation)

## Overview

Generates a German daily worklog ("Tagesdokumentation") for the current project
by mining two sources of truth — the **git commit history** and the **Claude Code
chat history** (the project's `*.jsonl` session files) — and writing one or two
short German lines per active day.

**Human-invoked only.** This skill is a manual reporting tool. Do not run it on
your own initiative; only when the user explicitly asks for the worklog.

## Inputs (3 arguments)

Invoke as: `/daily-worklog <from> <to> [prefix]`

| Arg | Meaning | Example |
|-----|---------|---------|
| `from` | start date, inclusive (`YYYY-MM-DD`) | `2026-05-12` |
| `to` | end date, inclusive (`YYYY-MM-DD`) | `2026-06-02` |
| `prefix` | the lead-in string for each doings line | `<Kunde> // <Projekt>` |

If the user gives loose dates ("from 12 May to today"), normalize them to
`YYYY-MM-DD` yourself (today's date is in the environment context). If `prefix`
is omitted, ask the user for it — do not guess. If `from`/`to` are missing, ask.

## Workflow

1. **Gather raw signal** — run the helper from the project root:
   ```bash
   python3 <skill-directory>/scripts/collect.py --from <from> --to <to>
   ```
   It prints, grouped by **local-time day**, the commits and the user's typed
   prompts in range. (It auto-derives the project root via `git rev-parse` and
   maps it to `~/.claude/projects/<path-with-slashes-as-dashes>/`. Pass
   `--project-root <path>` to override.)

   **Multi-author repos:** by default the helper filters `git log` to the
   **current git user** (`git config user.email`, falling back to `user.name`),
   so in a shared repo you only document *your own* commits. The chat history is
   already local to you. The header line `# commit author filter: …` shows who
   was matched — confirm it's right. Use `--all-authors` to include everyone, or
   `--authors <name-or-email> [<name-or-email> …]` to target one or more specific
   people (values are OR'd, so you get commits by *any* of them). If the header
   says `NONE (could not resolve current git user)`, set `git config user.email`
   or pass `--authors` before trusting the commit list.

2. **Read each day's signal.** Commit subjects are the most reliable source;
   typed prompts add intent and the work that produced no commit. The helper
   does light noise-filtering, but some pasted command output / XML may still
   appear as "prompts" — recognize those as tool output, not user intent, and
   ignore them.

3. **Summarize per active day** into one or two German lines. Output format,
   one entry per day:
   ```
   **DD.MM.** <prefix>: <doings auf Deutsch>
   ```

4. **Omit dead days.** Skip any day whose only activity is session noise
   (`/exit`, `/clear`, interrupted requests, no real commit or substantive
   prompt). The helper flags days as `[EMPTY]`; also drop days where the only
   prompts are trivial (e.g. "ja", "continue") with no commit.

5. **Wrap** the entries with a short German header, e.g.:
   ```
   # Tagesdokumentation – <project>

   Tägliche Doings <from> … <to> (Basis: Commit-Historie + Chatverlauf).
   Tage ohne echte Arbeit (… – nur `/exit`) sind ausgelassen.
   ```
   If the user asks for a file (e.g. "generate a md in Templates"), write it
   there; otherwise print the worklog in the reply.

## Style rules for the doings text

- German, concise, past/neutral technical tone — one or two lines max per day.
- Describe **what was investigated/built/fixed**, not the play-by-play.
- Group a day's threads into a single coherent sentence when they relate;
  separate distinct topics with "; zusätzlich …".
- Use the real subsystem/site names from commits and prompts (e.g.
  "<Subsystem>", "<Komponente>", "<Version>").

## Quick Reference

| Need | Command |
|------|---------|
| Raw signal for a range | `python3 <skill-directory>/scripts/collect.py --from 2026-05-12 --to 2026-06-02` |
| Different project | add `--project-root /path/to/repo` |
| Only my commits (default) | current git user is auto-detected; nothing to do |
| Everyone's commits | add `--all-authors` |
| Specific people's commits | add `--authors "alice@x.com" "Bob"` (OR'd) |

## Common Mistakes

- **Grouping by UTC.** The helper groups by **local time** on purpose — a prompt
  at 22:47 UTC belongs to the next local day. Don't second-guess its dates.
- **Treating pasted output as intent.** Long XML/REST/console blobs in the
  prompt list are things the user pasted *to* Claude, not their doings.
- **Inventing activity for empty days.** If a day has no commit and no
  substantive prompt, leave it out.
- **Auto-running.** This skill is explicit-invocation only.
