# Claude Code skills

Personal skills and slash commands synced across machines via this repo, since Claude Code loads them from a local folder per machine rather than an account-wide store.

## Setup on a new machine

```bash
git clone https://github.com/zurkin1/Python.git
cp -r Python/claude-skills/*/ ~/.claude/skills/    # skill folders (name/SKILL.md)
cp Python/claude-skills/commands/*.md ~/.claude/commands/    # slash commands
```

(On Windows: `~/.claude/skills` and `~/.claude/commands` are under `C:\Users\<you>\.claude\`.)

## Keeping in sync

Skills are edited directly under `~/.claude/skills/<name>/`, and slash commands directly under `~/.claude/commands/<name>.md`, day to day. To publish a change here:

```bash
cp -r ~/.claude/skills/pdf-to-epub claude-skills/
cp -r ~/.claude/skills/i-have-adhd claude-skills/
cp ~/.claude/commands/*.md claude-skills/commands/
git add claude-skills && git commit -m "Update skills" && git push
```

Then on the other machine: `git pull` and copy again.

## Contents

Skills (`~/.claude/skills/<name>/SKILL.md`):
- **pdf-to-epub** — convert a PDF book to EPUB, or fix an existing EPUB's scroll/paging direction (RTL-aware).
- **i-have-adhd** — output-formatting style for ADHD-friendly responses (`/i-have-adhd`).

Slash commands (`~/.claude/commands/<name>.md`):
- **fix-docx** — diagnose and fix slow-opening/saving `.docx` files bloated by PDF-to-Word conversion.
- **md-fixup** — clean up a PDF-extracted/OCR'd book's markdown into readable, well-structured text (RTL-aware).
- **txt-to-epub** — convert a plain-text/markdown/docx/pdf book into a clean EPUB with chapter structure and RTL support.
- **txt-to-md** — convert a markdown book specifically into a clean EPUB (chapters, metadata, images, RTL).
