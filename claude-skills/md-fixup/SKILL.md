---
name: md-fixup
description: Clean up and reformat a PDF-extracted or OCR'd book's markdown into a readable, well-structured file — builds a title/author header and cover image, reformats the table of contents, inserts chapter/section headers, strips OCR garbage (running page headers, stray symbols, page numbers), and fixes reversed word order, reversed parentheses/brackets, and reversed citation order common in Hebrew RTL PDF extraction and OCR output. Use when the user has a raw OCR- or PDF-extracted .md file they want cleaned up and structured.
---

# md-fixup

Clean up and reformat a PDF-extracted or OCR'd book into a readable, well-structured Markdown file.

The user invoked this skill with these arguments: $ARGUMENTS

Parse the arguments as: `<input.md> [source.pdf] [--lang he|en]`
- First positional arg = input markdown file (required)
- Second positional arg = original PDF for cover extraction (optional)
- `--lang` = primary language (default: he for Hebrew)

If no arguments were provided, ask the user for the file path before proceeding.

## Usage

```
/md-fixup <input.md> [source.pdf]
```

---

## What this skill does

Transforms a raw OCR-extracted markdown (typically from a PDF) into a clean, readable book with:

1. **Front cover image** extracted from the PDF first page
2. **Proper title/author header block**
3. **Reformatted Table of Contents**
4. **Chapter and section headers** at correct hierarchy levels
5. **OCR garbage removed** (page headers, footers, standalone numbers, symbol lines)
6. **Reversed word order fixed** (whole lines extracted in visual instead of logical order — seen with `pypdf` on vFlat-scanned PDFs; check for this before assuming it's just parens)
7. **Reversed parentheses and brackets fixed** (common in RTL Hebrew OCR output; the word-order fix above already corrects these as a side effect when it applies)
8. **English citation ordering fixed** (year-first reversed citations corrected)

Output: write to `<input>-clean.md` in the same directory.

---

## Step 1: Extract cover image from PDF

Use PyMuPDF (`fitz`) to render the first page at 2× resolution:

```python
import fitz
doc = fitz.open('book.pdf')
page = doc[0]
mat = fitz.Matrix(2, 2)
pix = page.get_pixmap(matrix=mat)
pix.save('cover.png')
```

If `fitz` is unavailable, try `pdf2image`. If neither works, skip the cover and note it.

---

## Step 2: Build the header block

```markdown
![עטיפת הספר](cover.png)

# Book Title
## Subtitle (if any)

**Author Name**
Institution

---
```

---

## Step 3: Reformat the Table of Contents

Find the TOC section (usually near the top) and rewrite it as a clean list under `## תוכן עניינים`. Remove page numbers and OCR artifacts from TOC entries.

---

## Step 4: Add chapter and section headers

Read the TOC to learn the structure. Then scan the body for lines that match chapter/section titles and insert markdown headers:

- `##` for top-level chapters (הקדמה, מבוא, ביבליוגרפיה, etc.)
- `###` for main sections
- `####` for subsections

**How to identify a title line:** it matches a TOC entry (after stripping digits and punctuation), appears after a page-break artifact or blank lines, and is short relative to surrounding paragraphs.

Because the file may be very large (1 MB+), read and process it in chunks of ~500 lines using `offset`/`limit` on the Read tool. Spawn a general-purpose subagent for the full pass if needed.

---

## Step 5: Remove OCR garbage

Delete or clean the following patterns:

| Pattern | Example | Action |
|---|---|---|
| Running page headers | `להציל את היכולת היצירתית של המוח - הקדמה 9` | Delete entire line |
| Author + page number lines | `12 \| ד״ר יצחק עזוז` | Delete entire line |
| Standalone page numbers | A line containing only digits | Delete |
| Symbol-only lines | `z ♦`, `»`, `f i * *`, `\` | Delete |
| Stray OCR fragments | `fJ5`, `iftf`, `fi8®`, `<1#`, `<ימס` | Delete |
| Markdown heading artifacts | `# .` or `## .` | Delete |

**Keep:** all actual prose (Hebrew or English), citations, bibliography entries.

Use regex passes in Python, reading the file in memory. For each line apply a filter that deletes it if it matches any garbage pattern.

Garbage-detection heuristics:
```python
import re

def is_garbage(line):
    s = line.strip()
    if not s:
        return False  # blank lines are fine
    # Only digits (page number)
    if re.fullmatch(r'\d+', s):
        return True
    # Page header pattern: Hebrew text + pipe/dash + digits
    if re.search(r'[\u0590-\u05ff].{0,40}[\|׀]\s*\d', s):
        return True
    # Very short line with mostly symbols/Latin noise (no real Hebrew word)
    hebrew_chars = len(re.findall(r'[\u0590-\u05ff]', s))
    if len(s) < 6 and hebrew_chars == 0:
        return True
    return False
```

---

## Step 5.5: Diagnose whether the source needs full word-order reversal (not just parens)

**Do this before Step 6.** Some PDF-text extractors (notably `pypdf`, confirmed on PDFs scanned with the "vFlat" app) don't just mirror parentheses — they emit each RTL line with its **words in visual (left-to-right screen) order** instead of logical (reading) order, while each individual word's own letters stay correctly spelled. The symptom looks like scrambled-but-not-garbled Hebrew: every word is real and correctly spelled, but the sentence reads backwards. Fixing only the parens on text like this still ships a broken book — the paren fix is cosmetic on top of a structurally reversed line.

**How to tell:** take a short recognizable phrase from the raw extracted text (a chapter title, a well-known quote) and read it aloud in the stored character order. If the *words* are in the wrong order but each word is spelled correctly, you have this bug. If words are already in correct reading order and only the parens/brackets look mirrored, skip to Step 6 as originally written — do NOT apply both fixes to the same text, since the reversal below already fixes paren placement as a side effect, and stacking the two double-corrects and re-breaks it.

**A cheap way to test it that doesn't require reading Hebrew:** if a `.pdf` of the same book is available, extract the same page with **PyMuPDF (`fitz`) `page.get_text()`** instead of `pypdf` and diff the word order against the `pypdf` output. Across every vFlat-scanned book seen so far, `fitz` returned correct logical order where `pypdf` returned visual order for the *identical* source file. When both are available, prefer `fitz` for extraction from the start and this whole step becomes unnecessary — cheaper than fixing it after the fact.

**The fix — reverse the line, then un-reverse each word (and each protected run):**

```python
import re

HEB_RE = re.compile(r'[֐-׿]')
# Runs of Latin letters/digits (numbers, English titles/citations) must stay in
# their own internal order — protect them as opaque tokens before reversing.
LATIN_PHRASE_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ,.\-\'"]*[A-Za-z0-9]|[A-Za-z0-9]')

def _protect_latin(line):
    spans = list(LATIN_PHRASE_RE.finditer(line))
    mapping = {}
    out = line
    for k, m in enumerate(reversed(spans)):
        idx = len(spans) - 1 - k
        placeholder = chr(0xE000 + idx)  # private-use area, single codepoint
        mapping[placeholder] = m.group(0)
        out = out[:m.start()] + placeholder + out[m.end():]
    return out, mapping

def visual_to_logical_line(line):
    """Fix a single line whose WORD ORDER is visual instead of logical.
    Do not apply to already-correct lines (see diagnosis above)."""
    if not line:
        return line
    protected, mapping = _protect_latin(line)
    rev = protected[::-1]
    out = []
    i, n = 0, len(rev)
    while i < n:
        c = rev[i]
        if HEB_RE.match(c):
            j = i
            while j < n and HEB_RE.match(rev[j]):
                j += 1
            out.append(rev[i:j][::-1])  # un-reverse this Hebrew run
            i = j
        else:
            out.append(c)  # neutral/punctuation chars just ride along with the reversal
            i += 1
    result = ''.join(out)
    for placeholder, original in mapping.items():
        result = result.replace(placeholder, original)
    return result
```

Apply `visual_to_logical_line()` to **every line** of the raw extracted text (before any heading/TOC/garbage detection — those all key off word content and will misfire on reversed text too). Do **not** additionally run the parens-fix regexes from Step 6 on text already passed through this function — the paren swap already happens correctly as a byproduct of the full-line reversal, so a second pass re-flips them back to wrong.

**Known limitation:** a multi-word *embedded* Latin/English phrase is protected as one atomic block, so its internal word order is preserved as-extracted — correct if the extractor already kept embedded LTR runs in logical order (the common case), but not independently verified for extractors that scramble those too. Spot-check any English citations after conversion.

---

## Step 6: Fix reversed parentheses and brackets only (no word-order issue)

Use this narrower fix only when Step 5.5 diagnosed that word order is already correct and just the parens/brackets are mirrored (a lighter-weight artifact than full visual-order reversal, seen in some other Hebrew RTL OCR pipelines).

In Hebrew RTL text, OCR often captures the visual glyph order, producing `)text(` instead of `(text)` and `]text[` instead of `[text]`.

**Fix Hebrew-content parens** — regex targeting content with Hebrew characters:

```python
import re

def fix_reversed_parens(text):
    pattern = r'\)([^()\n]*[\u0590-\u05ff][^()\n]*)\('
    def repl(m): return '(' + m.group(1) + ')'
    prev = None
    while prev != text:
        prev = text
        text = re.sub(pattern, repl, text)
    return text

def fix_reversed_brackets(text):
    pattern = r'\]([^\[\]\n]*[\u0590-\u05ff][^\[\]\n]*)\['
    def repl(m): return '[' + m.group(1) + ']'
    prev = None
    while prev != text:
        prev = text
        text = re.sub(pattern, repl, text)
    return text
```

**Fix English-content parens** (citations with no Hebrew):

```python
pattern = r'\)([^()\n]{1,80})\('
def repl(m):
    inner = m.group(1)
    if re.search(r'[a-zA-Z0-9,]', inner):
        return '(' + inner + ')'
    return m.group(0)
```

Run multiple passes until no more matches.

**Do NOT do a global swap** of all `(` ↔ `)` — this breaks correctly-formatted text (TOC entries written by the model, markdown image syntax, etc.).

Always protect markdown image syntax before any replacement:
```python
content = content.replace('![alt](img.png)', '___IMG___')
# ... fixes ...
content = content.replace('___IMG___', '![alt](img.png)')
```

---

## Step 7: Fix reversed English citations

Hebrew academic texts often place the year before the closing paren: `2012) .(Adobe.` instead of `(Adobe, 2012.)`.

Fix with:

```python
# Pattern: YEAR) .(Author,  →  (Author, YEAR.)
pattern1 = r'(\d{4}(?:-\d{4})?)\) \.\(?([A-Za-z>][A-Za-z\s,&.\-]+?)([,.])'
def repl1(m):
    year, author = m.group(1), m.group(2).strip().rstrip(',.')
    return f'({author}, {year}{m.group(3)})'

# Pattern: YEAR) .(Author  (no trailing punct)
pattern2 = r'(\d{4}(?:-\d{4})?)\) \.\(([A-Za-z][A-Za-z\s&.\->]+?)(\s)'
def repl2(m):
    return f'({m.group(2).strip()}, {m.group(1)}) '

# Pattern: YEAR) (Author  (no dot separator)
pattern3 = r'(\d{4}(?:-\d{4})?)\) \(([A-Za-z][A-Za-z\s,&.\->]+?)([,.])'
def repl3(m):
    year, author = m.group(1), m.group(2).strip()
    return f'({author}{m.group(3)} {year})'
```

Also fix known OCR garbling in author names, e.g. `E>e-Bono` → `De Bono`.

Remaining `) .(` patterns where the content after `(` is Hebrew are bibliography entries with Hebrew author names — leave them alone; they were handled in Step 6.

---

## Skill improvement protocol

When you encounter a new OCR artifact pattern, a new citation format, or a new garbage heuristic not covered above, add it to this skill file before finishing. Keep the skill up to date.
