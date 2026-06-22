# claude-skill-daily-worklog

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that generates a German daily worklog ("Tagesdokumentation") for a project by mining its git commit history and Claude Code chat history.

## What it does

For a given date range, it gathers two sources of truth — **git commits** and the project's **Claude Code session logs** (`~/.claude/projects/`) — groups the activity by local-time day, and writes one or two concise German lines per active day. Dead days (only `/exit`, `/clear`, or trivial prompts with no commit) are omitted.

### Example output

```
# Tagesdokumentation – <Projekt>

Tägliche Doings 2026-05-12 … 2026-06-02 (Basis: Commit-Historie + Chatverlauf).
Tage ohne echte Arbeit (… – nur `/exit`) sind ausgelassen.

**12.05.** <Kunde> // <Projekt> // <Doings>
**14.05.** <Kunde> // <Projekt> // <Doings>
```

## Installation

Add to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "skills": [
    "/path/to/claude-skill-daily-worklog"
  ]
}
```

## Usage

This skill is **explicit-invocation only** — it never triggers automatically. Invoke it with a date range and a prefix:

```
/daily-worklog <from> <to> [prefix]
```

| Arg | Meaning | Example |
|-----|---------|---------|
| `from` | start date, inclusive (`YYYY-MM-DD`) | `2026-05-12` |
| `to` | end date, inclusive (`YYYY-MM-DD`) | `2026-06-02` |
| `prefix` | lead-in string for each doings line | `<Kunde> // <Projekt>` |

### Direct script usage

```bash
python3 scripts/collect.py --from 2026-05-12 --to 2026-06-02   # current repo
python3 scripts/collect.py --from 2026-05-12 --to 2026-06-02 --project-root /path/to/repo
```

By default the helper filters `git log` to the **current git user** so you document only your own commits in a shared repo. Use `--all-authors` for everyone, or `--authors "alice@x.com" "Bob"` to target specific people.

## Requirements

Python 3.7+ (standard library only — no dependencies).

## License

MIT
