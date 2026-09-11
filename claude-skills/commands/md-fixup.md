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
6. **Reversed parentheses and brackets fixed** (common in RTL Hebrew OCR output)
7. **English citation ordering fixed** (year-first reversed citations corrected)

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

## Step 6: Fix reversed parentheses and brackets (Hebrew RTL OCR)

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
