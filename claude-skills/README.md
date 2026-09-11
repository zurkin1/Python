# Claude Code skills

Personal skills synced across machines via this repo, since Claude Code loads skills from a local folder per machine rather than an account-wide store.

## Setup on a new machine

```bash
git clone https://github.com/zurkin1/Python.git
cp -r Python/claude-skills/* ~/.claude/skills/
```

(On Windows: `~/.claude/skills` is `C:\Users\<you>\.claude\skills`.)

## Keeping in sync

Skills are edited directly under `~/.claude/skills/<name>/` day to day. To publish a change here:

```bash
cp -r ~/.claude/skills/pdf-to-epub claude-skills/
cp -r ~/.claude/skills/i-have-adhd claude-skills/
git add claude-skills && git commit -m "Update skills" && git push
```

Then on the other machine: `git pull` and copy again.

## Contents

- **pdf-to-epub** — convert a PDF book to EPUB, or fix an existing EPUB's scroll/paging direction (RTL-aware).
- **i-have-adhd** — output-formatting style for ADHD-friendly responses (`/i-have-adhd`).
