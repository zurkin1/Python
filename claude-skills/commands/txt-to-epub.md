# txt-to-epub

Convert a plain-text book file (OCR/extracted) into a clean, readable EPUB with proper chapter structure, headers, and RTL support for Hebrew books.

The user invoked this skill with these arguments: $ARGUMENTS

Parse the arguments as: `<input.txt|.md|.docx|.pdf> [output.epub] [--lang he|en] [--rtl]`
- First positional arg = input text file path (required)
- Second positional arg = output epub path (optional, default: `<book title>-<author last names separated by spaces>.epub` in the same directory as the input file — e.g. `לחשוב כמו פריק-לוויט דובנר.epub`)
- **Always leave the finished EPUB at its output path. Never copy it elsewhere** — the user handles distribution.
- `--lang` = language code (default: he)
- `--rtl` = enable right-to-left layout (default: true when --lang he)

If no arguments were provided, ask the user for the input file path before proceeding.

## Usage

```
/txt-to-epub <input.txt> [output.epub] [--lang he|en] [--rtl]
```

If no arguments are given, ask the user for the input file path and any options.

---

## Skill improvement protocol

While working on a specific book, you may encounter parsing patterns, edge cases, or techniques not yet documented in this skill (e.g. a new page-number bracket variant, a previously unseen running-header format, a new OCR artifact). When this happens:

1. **Solve it for the current book first** — get the EPUB working correctly.
2. **Then propose the addition**: write a short message to the user describing the new finding and asking whether to add it to the skill. Example:

   > "I handled `|12יעקב בורק` (no space between number and name) by extending `RUNNING_HEADER_RE`. Want me to add this variant to the skill's documented pitfalls?"

3. **Wait for approval** before editing the skill file. Do not silently update it.

---

## Workflow

**Source routing — check file extension before anything else:**

| Extension | Go to |
|---|---|
| `.md` | **Step 0.4** — Markdown sources |
| `.docx` | **Step 0.5** — DOCX sources |
| `.txt` | **Step 1** — Understand the source file |
| `.pdf` | **Step 0.1** — PDF source type detection |

---

### Step 0.1 — PDF source type detection (do this FIRST for any PDF)

Before doing anything else with a PDF source, run a **single triage command** to decide which extraction path to use. This is a one-shot check — do not iterate.

```python
python3 -X utf8 -c "
import fitz, re
doc = fitz.open('input.pdf')
page = doc[min(5, len(doc)-1)]
text = page.get_text('text')
words = page.get_text('words')
hebrew_in_text = len(re.findall(r'[֐-׿]', text))
hebrew_in_words = len([w for w in words if re.search(r'[֐-׿]', w[4])])
newlines = text.count('\n')
print(f'get_text: {hebrew_in_text} Hebrew chars, {newlines} newlines')
print(f'get_text words: {hebrew_in_words} Hebrew words')
print('Sample text:', repr(text[:300]))
"
```

**Decision tree — pick exactly one path and move on:**

| Result | Path |
|---|---|
| `get_text` has Hebrew chars AND text looks like coherent sentences | **Verify pdftotext works** (see below), then Steps 0–3 |
| `get_text` has Hebrew BUT newlines ≈ word count (one word per line) | **Step 0.6** — custom font encoding, word-by-word extraction |
| `get_text` has zero Hebrew chars (only spaces/Latin) | **Step 0.6** — custom font encoding, word-by-word extraction |
| `get_text` has zero Hebrew AND zero words from `get_text('words')` | **Pure scan — no text layer.** Cannot convert. Tell the user to OCR first (Google Docs or Adobe Acrobat), then rerun on the resulting `.docx`. |

**Critical: PyMuPDF `get_text()` working does NOT guarantee pdftotext works.** Some PDFs use font encodings that PyMuPDF resolves but pdftotext cannot. Before committing to the pdftotext pipeline, verify with one command:

```bash
pdftotext -layout input.pdf - | python3 -X utf8 -c "import sys,re; t=sys.stdin.read(); print(len(re.findall(r'[֐-׿]',t)),'Hebrew chars')"
```

- If output is `0 Hebrew chars` → **go to Step 0.6** (PyMuPDF word extraction), even though `get_text()` showed Hebrew
- If output has Hebrew chars → proceed with pdftotext pipeline (Steps 0–3)

The last two cases in the table happen when the PDF uses a **custom/proprietary font encoding**. **Do NOT run pdftotext.** Do NOT try `rawdict` or `blocks` extraction — they fail for the same reason. Go directly to Step 0.6.

---

### Step 0.6 — PyMuPDF word-position extraction (custom-encoded PDFs)

**Use when Step 0.1 routes here. Do not explore further before writing the script — all constants below are pre-calibrated.**

**Known constants — read from Command 1 output, do not measure further:**
- Running header y-threshold: the first 1–2 lines of body pages are headers; their y-values are the threshold. Typical: **y < 60** (when headers are at y=36–40) or **y < 85** (when headers are at y=52–60). Read from Command 1 — use the y of the first body line minus a small margin.
- Normal line spacing: **12–20 pt** (indentation-style books) or **36–40 pt** (spacing-style books)
- Paragraph break gap: **y-gap > 48 pt** (spacing-style only — see paragraph detection section)
- Chapter/section opener pages: first non-header line at **y > 140** (adjust threshold in Command 2 if needed)
- Opener page body start: **y > title_y + 16** — body starts just after the title line

**`page_lines` helper — copy as-is:**

```python
import fitz, re

doc = fitz.open('input.pdf')

def page_lines(page):
    """Extract RTL lines grouped by y-coordinate."""
    words = page.get_text('words')
    if not words:
        return []
    buckets = {}
    for w in words:
        y = round(w[1] / 4) * 4
        buckets.setdefault(y, []).append(w)
    result = []
    for y in sorted(buckets):
        line_words = sorted(buckets[y], key=lambda w: w[0], reverse=True)
        result.append((y, ' '.join(w[4] for w in line_words)))
    return result
```

**Exploration budget — TWO commands only, then write the script:**

```python
# Command 1: read TOC and first chapter pages (pages 6-10)
for pg in range(6, 11):
    print(f'=== PDF page {pg} ===')
    for y, t in page_lines(doc[pg])[:8]:
        print(f'  y={y}: {repr(t[:80])}')
    print()
```

```python
# Command 2: find all opener pages (chapter/section boundaries) in one pass
for pg in range(len(doc)):
    lines = page_lines(doc[pg])
    body = [(y, t) for y, t in lines if y >= 85]
    if body and body[0][0] > 150:
        print(f'PDF page {pg}: y={body[0][0]}: {repr(body[0][1][:70])}')
```

After these two commands, build `CHAPTER_PAGES` and `SECTION_PAGES` dicts from the output and write the script. **Do not run more exploration commands.**

**Paragraph detection — two strategies, pick one based on book style:**

| Book style | Detection method |
|---|---|
| Western-style spacing (blank line / extra gap between paragraphs) | y-gap > 48pt within page; flush at page-end only if sentence ends |
| Hebrew indentation style (no gap, first line indented from right) | **Flush at every page boundary** — page breaks are reliable paragraph breaks even if mid-sentence |

**How to tell which style:** look at Command 1 output. If y-gaps between consecutive lines are uniformly 12–20pt with no larger gaps in the body, it's indentation style → use page-boundary flush. If you see gaps of 50–80pt interspersed with the normal 36–40pt gaps, it's spacing style → use y-gap detection.

**Page-boundary flush (indentation style):**
```python
# At end of each page's loop — always flush, not conditionally:
flush()
```

**Y-gap flush (spacing style):**
```python
# Within page loop:
if prev_y is not None and (y - prev_y) > 48 and current_para_words:
    flush()
# At page end — only flush if sentence ends:
if current_para_words and current_para_words[-1].strip()[-1:] in '.!?:':
    flush()
```

**Default to page-boundary flush** when unsure — it produces more paragraphs but never loses text. Y-gap detection can silently merge entire chapters into one paragraph if the book uses indentation.

**Figure extraction — always do this, never skip it.**

Run this scan immediately after Command 2, before writing the script. It takes one command and reveals all figure pages:

```python
# Command 3 (mandatory): find all figure pages
HEADER_Y = 68   # adjust to match this book's header threshold
for pg_idx in range(len(doc)):
    page = doc[pg_idx]
    lines = page_lines(page)
    body = [(y, t) for y, t in lines if y >= HEADER_Y]
    captions = [(y, t) for y, t in body if re.match(r'^(איור|תרשים|גרף)\s*\d+', t)]
    if not captions:
        continue
    has_imgs = len(page.get_images()) > 0
    has_drawings = len(page.get_drawings()) > 5
    if has_imgs or has_drawings:
        cap_y, cap_t = captions[0]
        print(f'PDF {pg_idx}: cap_y={cap_y}, imgs={len(page.get_images())}, drawings={len(page.get_drawings())}: {cap_t[:60]}')
```

If this prints nothing → no figures in the book, proceed without image code.
If it prints results → add figure extraction to the script using the pattern below.

**Figure rendering pattern (copy into script):**

```python
def get_figure_bbox(page, HEADER_Y):
    """Return (y_top, y_bottom) of the figure area on this page."""
    imgs = page.get_images(full=True)
    if imgs:
        rects = page.get_image_rects(imgs[0][0])
        if rects:
            r = rects[0]
            return max(HEADER_Y, r.y0 - 4), r.y1 + 4
    drawings = page.get_drawings()
    if drawings:
        ys = [d['rect'].y0 for d in drawings if d.get('rect')] + \
             [d['rect'].y1 for d in drawings if d.get('rect')]
        if ys:
            return max(HEADER_Y, min(ys) - 4), max(ys) + 4
    return None, None

def render_figure(page, y_top, y_bottom, scale=1.8):
    clip = fitz.Rect(0, max(0, y_top), page.rect.width, min(page.rect.height, y_bottom))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    return pix.tobytes('png')

# Build FIGURE_PAGES dict before processing chapters
FIGURE_PAGES = {}
fig_counter = 0
for pg_idx in range(len(doc)):
    page = doc[pg_idx]
    lines = page_lines(page)
    body = [(y, t) for y, t in lines if y >= HEADER_Y_MAX]
    captions = [(y, t) for y, t in body if re.match(r'^(איור|תרשים|גרף)\s*\d+', t)]
    if not captions:
        continue
    if not page.get_images() and len(page.get_drawings()) <= 5:
        continue   # caption is a text reference, not an actual figure page
    cap_y, cap_text = captions[0]
    y_top, y_bottom = get_figure_bbox(page, HEADER_Y_MAX)
    if y_top is None:
        y_top, y_bottom = HEADER_Y_MAX, cap_y - 4
    if y_bottom - y_top < 50:   # sanity check
        continue
    fig_counter += 1
    fig_id = f'fig_{fig_counter:03d}'
    FIGURE_PAGES[pg_idx] = {
        'id': fig_id,
        'img_bytes': render_figure(page, y_top, y_bottom),
        'caption': cap_text,
        'cap_y': cap_y,
    }
```

**In process_pages — inject figure blocks and skip rendered lines:**

```python
for pg_idx in range(start_pdf_pg, end_pdf_pg):
    if pg_idx in FIGURE_PAGES:
        flush()
        fig = FIGURE_PAGES[pg_idx]
        blocks.append({'type': 'figure', 'id': fig['id'], 'caption': fig['caption']})
        cap_y = fig['cap_y']
    else:
        cap_y = None

    for y, text in page_lines(doc[pg_idx]):
        if y < HEADER_Y_MAX: continue
        if cap_y is not None and y <= cap_y: continue  # skip rendered figure area
        # ... rest of line processing
```

**Add figures to EPUB manifest before building chapters:**
```python
for fig in FIGURE_PAGES.values():
    book.add_item(epub.EpubItem(uid=f'img_{fig["id"]}',
                                file_name=f'Images/{fig["id"]}.png',
                                media_type='image/png', content=fig['img_bytes']))
```

**In build_chapter_html — render figure blocks:**
```python
if isinstance(block, dict) and block['type'] == 'figure':
    cap = escape_html(block['caption'])
    parts.append(f'<div class="figure"><img src="Images/{block["id"]}.png" alt="{cap}"/></div>'
                 f'<p class="caption">{cap}</p>')
```

**CSS to add:**
```css
div.figure { text-align: center; margin: 1.5em 0; page-break-inside: avoid; }
div.figure img { max-width: 100%; height: auto; }
p.caption { direction: rtl; text-align: right; font-size: 0.9em; color: #333;
            text-indent: 0; margin: 0.3em 0 1.2em 0; }
```

**This replaces Steps 0–3 entirely.** Skip pdftotext, skip rawdict, skip the text-file workflow.

**Known pitfalls:**
- Inline footnote numbers appear as a separate word at y+4 (e.g. `80)` one line below the text). Both y-values merge into the same paragraph since the gap is < 10pt.
- Running headers split across two close y-values (y=52 + y=60). Both < 85 → both stripped.
- Some section titles ONLY appear in running headers and never as a body heading. The opener-page scan won't find them. Accept this — they'll render as body paragraphs, which is readable.
- Do NOT auto-detect epigraphs with y-threshold heuristics. Epigraph mis-detection causes body text to be swallowed. Just render everything at y > 310 as body paragraphs on opener pages.

---

### Step 0.4 — Markdown sources (skip Steps 0–3 entirely)

When the source is a `.md` file, skip the entire PDF/txt pipeline. Markdown already encodes structure as headings, so extraction is straightforward.

**Detection:** input argument ends in `.md`.

#### Image extraction from markdown

Markdown books sometimes embed images as **base64 data URIs** in reference-style link definitions at the end of the file:

```
[ch1_img_1]: data:image/jpeg;base64,/9j/4SQu...
```

Extract all of these before parsing body text, then strip the definition lines so they don't appear as body content:

```python
import re, base64

def extract_images(text):
    images = {}
    for m in re.finditer(
            r'^\[([^\]]+)\]:\s*(data:image/([^;]+);base64,([^\s]+))',
            text, re.MULTILINE):
        ref, mime_type, b64data = m.group(1), m.group(3), m.group(4)
        ext = 'jpg' if mime_type in ('jpeg', 'jpg') else mime_type
        images[ref] = {'bytes': base64.b64decode(b64data),
                       'ext': ext, 'mime': f'image/{mime_type}'}
    return images

# Strip definitions before parsing paragraphs
text = re.sub(r'^\[[^\]]+\]:\s*data:image/[^\n]+', '', text, flags=re.MULTILINE)
```

The first image (often named `cover_img` or `ch1_img_1`, placed before any chapter content) is usually the book cover — pass its bytes to `book.set_cover(...)`.

#### Heading hierarchy and the `after_separator` flag

Hebrew markdown books often reuse the same heading level (`####`) for two different roles:

| Context | Role | EPUB output |
|---|---|---|
| `####` immediately after `###` (with ≤1 blank line) | Subtitle of the `###` chapter | `<h2>` under the `<h1>` |
| `####` after a `---` separator | New standalone chapter (הקדמה, מבוא, ביבליוגרפיה) | New EPUB chapter with `<h1>` |
| `####` in the middle of chapter body | In-chapter subsection | `<h3>` |

Disambiguate with an `after_separator` flag:

```python
after_separator = False

for line in lines:
    stripped = line.strip()

    if stripped.startswith('### '):         # numbered chapter
        save_chapter()
        ch_title = stripped[4:].strip()
        ch_sub = peek_next_h4(lines, i)    # look ahead for #### subtitle
        current_ch = {'title': ch_title, 'subtitle': ch_sub}
        after_separator = False

    elif stripped.startswith('#### '):
        if current_ch is None or after_separator:
            # Standalone chapter (front/back matter)
            save_chapter()
            current_ch = {'title': stripped[5:].strip(), 'subtitle': ''}
            after_separator = False
        else:
            # In-chapter subsection
            flush_para()
            blocks.append({'type': 'section', 'text': stripped[5:].strip()})
            after_separator = False

    elif stripped == '---':
        flush_para()
        after_separator = True             # next #### starts a new chapter

    elif not stripped:
        flush_para()
        # do NOT reset after_separator on blank lines — they sit between --- and ####

    else:
        after_separator = False            # real content resets the flag
        current_para_lines.append(stripped)
```

#### Section-number lines

Lines like `1.1  הַדמָיוֹת "ראי" וחיקוי` (section number + **two or more spaces** + title) are subsection headings, not body text. Detect and render as `<h3>`:

```python
SECTION_NUM_RE = re.compile(r'^\d+\.\d+(?:\.\d+)?\s{2,}(.+)')

if SECTION_NUM_RE.match(stripped):
    flush_para()
    blocks.append({'type': 'section', 'text': stripped})
```

#### Footnote blocks

Inline footnotes appear as `[*. text]` or `[N. text]` on their own line. Render with a distinct style rather than as body paragraphs:

```python
FOOTNOTE_RE = re.compile(r'^\[\*\.?\s*(.+)\]$|^\[\d+\.\s*(.+)\]$')

if FOOTNOTE_RE.match(stripped):
    flush_para()
    blocks.append({'type': 'footnote', 'text': FOOTNOTE_RE.match(stripped).group(1) or ...})
```

**CSS:**
```css
p.footnote { direction: rtl; text-align: right; font-size: 0.85em; color: #555;
             border-right: 3px solid #ccc; padding-right: 0.8em;
             text-indent: 0; margin: 0.8em 0; }
```

#### Known pitfalls (markdown sources)

- **Base64 lines are enormous** — do not try to `grep` or read them line by line for inspection; they will overflow any preview. Use the regex extraction above and check `len(images)` to confirm counts.
- **`---` resets the chapter boundary** — without the `after_separator` flag, a `####` after `---` (like ביבליוגרפיה) gets silently swallowed into the previous chapter's body as an `<h3>`.
- **Blank lines between `---` and `####`** — the flag must survive blank lines; only real content (non-empty, non-`---` lines) should reset it.
- **`###` subtitle look-ahead** — when a `###` chapter heading is immediately followed (within 1–2 lines) by `####`, that `####` is the subtitle, not a new chapter. Consume it during `###` processing so the parser's main loop never sees it.
- **`* * *` section breaks** — render as `<p class="separator">* * *</p>` (centered, no indent); do not reset `after_separator` on them (they're not chapter boundaries).

---

### Step 0.5 — DOCX sources (skip Steps 0–3 entirely)

When the source is a `.docx` file, the entire PDF→txt pipeline (Steps 0–3) is replaced by a direct `python-docx` extraction. There are no bidi marks, no niqqud artifacts, no running headers, and no pdftotext quirks to handle.

**Detection:** if the input argument ends in `.docx`, use this step instead of Steps 0–3.

**Prerequisites:** `pip install python-docx ebooklib`

#### Style mapping

`python-docx` preserves the original heading styles. Map them to EPUB elements:

| docx style | Role | EPUB output |
|---|---|---|
| `Heading 1` | Book title (front matter only) | skip |
| `Heading 2` | Chapter/essay boundary | `<h1>` — start a new chapter |
| `Heading 3` | Author name (anthology) | `<p class="author">` |
| `Heading 4` | Section header | `<h2>` |
| `Heading 5` | Page number marker (`]15[`) or running header | **skip** |
| `Heading 6` | Sub-section header | `<h3>` |
| `Body Text` | Main body paragraph | `<p>` |
| `Normal` | Multiple roles — see below | varies |
| `Title` | Book title on cover page | skip |

**`Normal` style disambiguation** — a single style is reused for footnotes, image captions, subtitles, and body-level text. Distinguish by content:

```python
FOOTNOTE_RE = re.compile(r'^\d{1,3}\s{1,3}')    # "1  footnote text"
CAPTION_RE  = re.compile(r'^(תמונה|איור|תרשים)\b')  # image caption
URL_RE      = re.compile(r'https?://|www\.|\.com|\.org|\.jpg|\.png')

def classify_normal(s):
    if not s:                      return 'empty'
    if FOOTNOTE_RE.match(s):       return 'footnote'   # render as p.footnote
    if CAPTION_RE.match(s):        return 'caption'    # image caption
    if URL_RE.search(s) and len(s.split()) <= 4:
                                   return 'url'        # skip
    return 'body'                                      # treat as paragraph
```

**`Heading 5` page-marker detection** — these appear as `]15[`, `]19[`, or as `Title   17` (title + many spaces + page number). Skip all `Heading 5` paragraphs unconditionally; they are always page markers or running headers in this style.

#### Subtitle detection

Some chapters have a subtitle line (Normal style) between the `Heading 2` title and the `Heading 3` author:

```python
# peek ahead from start+1 to find subtitle and author
idx = start + 1
while idx < end:
    p = paras[idx]
    s = p.text.strip()
    if not s:          idx += 1; continue
    if p.style.name == 'Heading 3':
        author = s; idx += 1; break
    if p.style.name == 'Normal' and not FOOTNOTE_RE.match(s) and has_hebrew(s):
        subtitle = s;  idx += 1; continue
    break
```

#### Image extraction from docx

Images in a docx appear in two forms — detect both with the same `a:blip` search:

```python
from docx.oxml.ns import qn

def has_image(p):
    return bool(p._element.findall('.//' + qn('a:blip')))

def get_img_bytes_and_ext(p, doc):
    blip = p._element.findall('.//' + qn('a:blip'))[0]
    rId  = blip.get(qn('r:embed'))
    rel  = doc.part.rels[rId]
    ext  = 'jpg' if 'jpeg' in rel.target_part.content_type else 'png'
    return rel.target_part.blob, ext
```

**Form 1 — block image** (paragraph is empty, image is the only content):
- `p.text.strip() == ''` and `has_image(p)` → standalone figure
- Look ahead up to 3 paragraphs for a `CAPTION_RE`-matching Normal paragraph → that is the caption; mark it as consumed so it isn't emitted again as body text
- URL-only Normal paragraphs after the caption (image attribution lines) → skip

**Form 2 — inline image** (paragraph has both image and caption text):
- `p.text.strip() != ''` and `has_image(p)` and `CAPTION_RE.match(p.text.strip())` → the paragraph text IS the caption; extract image and use text as caption

**Non-captioned images** — if neither form yields a `CAPTION_RE` match, render the image without a caption (or skip if it is clearly decorative, e.g. the cover painting on the title page).

**Cover extraction** — the cover image is usually the first image in the docx (the first `a:blip` relationship). Extract it directly:

```python
# Find the first image relationship by iterating rels in order
for rId, rel in doc.part.rels.items():
    if 'image' in rel.reltype:
        cover_bytes = rel.target_part.blob
        break
```

Then pass `cover_bytes` to `book.set_cover('cover.jpg', cover_bytes)` as usual.

#### Two-pass build loop

```python
# Pass 1: build image map and collect caption paragraph indices to skip
images, caption_paras = build_image_map(doc)   # {para_idx: fig_dict}

# Pass 2: process chapters
for ci, start in enumerate(CHAPTER_STARTS):
    end    = CHAPTER_STARTS[ci+1] if ci+1 < len(CHAPTER_STARTS) else len(paras)
    ch_name = paras[start].text.strip()   # the Heading 2 text
    blocks  = process_chapter(paras, start, end, images, caption_paras)
    ...
```

#### `CHAPTER_STARTS` for docx

Unlike the txt workflow (line numbers), `CHAPTER_STARTS` is a list of **paragraph indices** where each `Heading 2` starts a chapter. Build it by scanning:

```python
CHAPTER_STARTS = [i for i, p in enumerate(doc.paragraphs)
                  if p.style.name == 'Heading 2' and p.text.strip()]
# Then optionally trim front-matter entries (TOC, title page headings)
```

Or specify manually after inspecting headings:

```python
# quick heading dump:
for i, p in enumerate(doc.paragraphs):
    if 'Heading' in p.style.name and p.text.strip():
        print(f'{i:4}: [{p.style.name}] {p.text[:80]}')
```

#### Known pitfalls (docx sources)

- **`Normal` style overloaded** — the same style is used for footnotes, captions, subtitles, and body text. Always classify by content pattern (see above) rather than trusting the style name alone.
- **Inline images mixed with caption text** — `p.text` still returns the caption string even when an image is embedded mid-paragraph; `a:blip` detection finds it regardless of position. Check `p.text.strip()` to distinguish block vs inline form.
- **`Heading 5` page markers** — skip all of them unconditionally; they are never content.
- **Image at paragraph 0** is often the cover art (not a content figure) — skip it in the body but use it as the EPUB cover.
- **Multi-image paragraphs** — some paragraphs embed two or three images side by side (caption reads "תמונות 12, 13 ו-14"). `findall('.//' + qn('a:blip'))` returns all blips; extract only the first one per paragraph for simplicity, or loop over all blips to extract each image separately.
- **Garbled captions** in the last few paragraphs (author bios section) may contain non-Hebrew OCR garbage — the `CAPTION_RE` guard prevents them from matching, so those images are safely skipped.
- **No bidi/niqqud cleanup needed** — docx stores logical Unicode order; `p.text` is already correct. Do not apply `BIDI_RE` or `NIQQUD_RE` to docx content.
- **All-floating-textboxes DOCX** — some OCR'd Hebrew books (typically scanned and processed by Word) store every text fragment as a floating shape (`wp:anchor`) rather than a normal paragraph. Symptom: `doc.paragraphs` returns hundreds of entries all with `.text == ''`. The `python-docx` paragraph API is useless here. **Use the PDF source instead** — `pdftotext -layout` on the same book will give clean paragraph-structured text that works with the standard pipeline.

---

### Step 0 — Check PDF page order (PDF sources only)

Scanned PDFs sometimes store pages in non-sequential order (e.g. pairs swapped: 7,6,9,8,11,10,...). If the source is a PDF extracted with `pdftotext`, **check page order before doing anything else**:

```bash
python3 -X utf8 -c "
import re
with open('input.txt', 'r', encoding='utf-8') as f:
    pages = f.read().split('\x0c')
FOOTER_RE = re.compile(r'^[\[\]ן)(]{1,2}(\d+)[\[\]ן)(]{1,2}$')
for i, p in enumerate(pages[:15]):
    for line in reversed(p.strip().split('\n')[-4:]):
        m = FOOTER_RE.match(line.strip())
        if m: print(f'PDF page {i} -> book page {m.group(1)}'); break
"
```

If the sequence is non-monotonic, sort pages by their footer numbers before processing:

```python
FOOTER_RE = re.compile(r'^[\[\]ן)(]{1,2}(\d+)[\[\]ן)(]{1,2}$')

def get_footer_page_num(page_text):
    for line in reversed(page_text.strip().split('\n')[-4:]):
        m = FOOTER_RE.match(line.strip())
        if m:
            return int(m.group(1))
    return None

with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    pdf_pages = f.read().split('\x0c')

sorted_pages = sorted(
    [(get_footer_page_num(p), p) for p in pdf_pages if get_footer_page_num(p)],
    key=lambda x: x[0]
)
# Then use sorted_pages instead of raw pdf_pages for all chapter detection
```

**Footer bracket variants** — Hebrew OCR produces several bracket forms for the `]XX[` page number footer. The regex above covers all known variants:
- `]7[` — normal
- `]5ן` — `ן` (final nun, U+05DF) used in place of `[`
- `[9ן` — reversed
- `)265[` — parenthesis instead of bracket (some scanners)

### Step 1 — Understand the source file

**Do these three things in parallel as your very first tool calls — before reading any file content:**

1. `grep ^##` (or `^[0-9]$`, or whatever heading marker suits the format) to get all chapter headings with line numbers in one shot.
2. `grep !\[` (or the equivalent image-reference pattern) to discover whether images exist and what form they take.
3. Read only the first ~150 lines to get title, author, TOC, and structural pattern.

Run all three in the same message. The grep results give you the complete chapter map and image inventory immediately; the short read confirms the structural pattern. **Do not read 400+ lines before running greps** — that wastes tokens on content you don't need yet.

After these three parallel calls you should know:
   - Book title, author, translator, publisher
   - All chapter start line numbers (from grep)
   - Whether images exist and how they're referenced (from grep)
   - What the markdown/text structure looks like (from the short read)

Only read additional file sections if something is genuinely unclear after the parallel triage — e.g. to inspect a specific chapter opening or verify back matter. Do not read chapter bodies as part of exploration.

4. If a PDF of the same book exists nearby, consult it for layout reference (chapter structure, section headers).

**Bidi mark check** — PDFs with embedded Unicode directionality (common in Hebrew books typeset with InDesign or similar) often have invisible bidi control characters (`\u202A`, `\u202B`, `\u202C`, `\u202D`, `\u202E`, `\u200F`, etc.) inline in every line. These cause string comparisons to fail silently — `line.strip() == chapter_name` returns `False` even though they look identical on screen. Always strip them before any comparison:

```python
BIDI_RE   = re.compile(r'[\u200f\u200e\u202a\u202b\u202c\u202d\u202e\u200b\u200c\u200d]')
# Strip niqqud vowel points but NOT maqaf (U+05BE ־) or paseq (U+05C0 ׀) or sof-pasuk (U+05C3)
NIQQUD_RE = re.compile(r' ?[\u05b0-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]')

def clean(s):
    s = BIDI_RE.sub('', s).replace('\x0c', '')
    s = NIQQUD_RE.sub('', s)
    # Fix reversed parentheses: only swap )Hebrew content( → (Hebrew content).
    # Do NOT do a blanket swap — some PDFs preserve logical order already.
    s = re.sub(r'\)([^()]*[\u0590-\u05FF][^()]*)\(', r'(\1)', s)
    return s.strip()
```

Use `clean(line)` everywhere instead of `line.strip()` when working with such files.

**Parentheses reversal artifact** — `pdftotext` sometimes extracts parentheses in visual (screen) order for RTL text, producing `)רחמנא ליצלן(` instead of `(רחמנא ליצלן)`. However, other PDFs (especially those with explicit bidi marks like `\u202b`) already preserve logical order, so a blanket swap would break them. The correct fix is a targeted regex that only corrects already-reversed parens — `)content(` where content contains Hebrew → `(content)`. Correctly-ordered `(content)` is left untouched. This works universally regardless of the source PDF's bidi handling.

**Niqqud (Hebrew vowel points) artifact** — `pdftotext` often separates Hebrew vowel marks (niqqud, U+05B0–U+05BD) from their base letters with a space, producing garbage like `שבי ֵלי` instead of `שבילי`, `ע ּובדות` instead of `עובדות`. The `NIQQUD_RE` above strips both the leading space and the niqqud character in one pass. It preserves:
- U+05BE `־` (maqaf, the Hebrew hyphen) — used in compound words
- U+05C0 `׀` (paseq) — used as running-header separator
- U+05C3 `׃` (sof pasuk)

To check if a file is affected:

```python
python3 -X utf8 -c "
import re
BIDI_RE = re.compile(r'[\u200f\u200e\u202a\u202b\u202c\u202d\u202e]')
with open('input.txt', encoding='utf-8') as f:
    lines = f.readlines()
hits = sum(1 for l in lines if BIDI_RE.search(l))
print(f'{hits}/{len(lines)} lines have bidi marks')
"
```

If the count is high (thousands of lines), add `clean()` to all line processing in the script.

### Step 2 — Map chapter boundaries

**Always include front matter and back matter — do not start at the first chapter.**

**Front matter to capture** (appears before chapter 1, often on pages 3–9):
- Series editor's introduction or book description (a few paragraphs about the series/book)
- Dedication ("לדוד...", "למשה ודליה...")
- Author's preface / הקדמה
- Any other introductory text with substantive content

Each distinct front-matter section should become its own EPUB chapter. Inspect the first ~150 lines carefully and include everything that has readable content — don't start the TOC scan at the first numbered chapter.

**Back matter to capture** (appears after the last chapter):
- הערות / Notes / Footnotes section (if collected at the end rather than inline)
- ביבליוגרפיה / Bibliography / References
- מפתח / Index
- Acknowledgments

These should also become EPUB chapters. Check the last ~200 lines of the file and the TOC for these sections.

Use grep to find:
- Standalone single-digit lines (`^[0-9]$`) — likely chapter numbers
- **Dot-prefixed numbers** (`.1`, `.2`, … `.19`) — some Israeli books use this reversed convention instead of standalone digits. Grep with `^\.\d{1,2}$`.
- Chapter names from the TOC as standalone lines
- Front-matter headings: הקדמה, מבוא, דברי פתיחה, הקדשה
- Back-matter headings: הערות, ביבליוגרפיה, מקורות, מפתח

Verify each candidate line in context (read ±5 lines) to confirm it's a real chapter start, not a page number or index entry.

Build a `CHAPTER_STARTS` list:
```python
CHAPTER_STARTS = [
    # (0-indexed line number, chapter_number_str, chapter_name, subtitle)
    (108,  '',  'הקדמה',           'סיזיפוס ודוקטור סוס'),
    (436,  '1', 'חשיבה מדעית',     'התנסות חוץ-גופית'),
    # ...
]
```

**Anthology books with per-essay authors** — when different essays/chapters are written by different authors, add a 5th field (author string) to each tuple. Pass it to `build_chapter_html` and render as `<p class="author">` between the subtitle and the first paragraph:

```python
CHAPTER_STARTS = [
    # (line, num, name, subtitle, author)
    (504,  '', 'מצוינות והאופי הישראלי', 'הילכו שניים יחדיו בלתי אם נועדו?', 'אלי הורביץ'),
    (1557, '', 'השיטה הפילנתרופית',       '',                                   'גיא ראביד'),
    (7925, '', 'הערות',                   '',                                   ''),
]

# In build_chapter_html, after the h2 subtitle block:
if ch_author:
    parts.append(f'<p class="author">{escape_html(ch_author)}</p>')
```

**CSS for author line:**
```css
p.author { direction: rtl; text-align: right; font-size: 1.05em; font-style: italic;
           text-indent: 0; margin: 0.3em 0 1.5em 0; color: #333; }
```

**Critical:** do NOT add the author string to `skip_exact` — it would strip the name from the body text too. The author is passed as a separate parameter and rendered directly; it never appears as a standalone line in the extracted text.

**Chapter letter labels** — Some books (especially academic series) use a standalone Hebrew letter (א, ב, ג, ד, ...) on its own line immediately before the chapter title, instead of or in addition to a numeric label. These single-letter lines appear in `process_chapter`'s skip window and must be stripped. Add them to `skip_exact` or define a set:

```python
CHAPTER_LETTERS = {'א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט', 'י'}

# In process_chapter, extend skip_exact:
skip_exact = {normalize_ws(x) for x in
              {ch_num, ch_name, ch_sub} | CHAPTER_LETTERS if x}
```

Use the letter itself (e.g. `'א'`) as the `ch_num` label in `CHAPTER_STARTS` so it renders as the chapter number in the EPUB heading.

**Dot-prefixed chapter numbers** — When chapter labels are `.1`, `.2`, … `.19`, add the dot form to `skip_exact` so it doesn't leak into the first paragraph:

```python
skip_exact = {normalize_ws(x) for x in
              {ch_num, ch_name, ch_sub, f'.{ch_num}', f'פרק {ch_num}'} - {'', 'פרק '}}
```

### Step 3 — Identify running headers to strip

Running headers are lines that repeat throughout the body (the book title, author name, chapter name as a page header).

**First, check for the `X | text` / `text | X` pattern.** OCR'd Hebrew books commonly format running headers as `44 | הפצצה` (even pages) and `מועדון האורניום | 45` (odd pages). If you see this pattern, a single regex handles all of them — no need to enumerate manually (see script template). Grep to confirm:
```bash
grep -nP '^\d+ \| .+$|^.+ \| \d+$' input.txt | head -20
```

If the pattern is consistent, set `RUNNING_HEADER_RE` in the script (already included in template). Otherwise fall back to a static `RUNNING_HEADERS` set.

**Option C — "follows page number" detection.** When running headers use neither the pipe pattern nor a single repeated string (e.g. each chapter has its own Hebrew title as an even-page header), detect them positionally: any Hebrew line immediately following a standalone page number is a running header. Implement with a `prev_was_page_num` flag in the body loop:

```python
prev_was_page_num = False
for i in range(idx, end):
    s = clean(all_lines[i])

    if is_page_number(s):
        prev_was_page_num = True
        continue

    # Running header: Hebrew line right after a page number
    if prev_was_page_num and s and has_hebrew(s) and len(s) < 60:
        if current: blocks.append(' '.join(current)); current = []
        prev_was_page_num = False
        continue

    prev_was_page_num = False
    # ... rest of loop
```

This handles all 51 chapter-name headers automatically without enumerating them. The `len(s) < 60` guard prevents accidentally eating long body lines that happen to follow a page number (body paragraphs are usually much longer). Confirm the pattern first: check that lines following page numbers are consistently short Hebrew titles and never body text.

**Check for private-use character headers.** Some Hebrew PDFs typeset with symbol fonts embed a private-use Unicode character (commonly `\uf03c`, rendered as a `<` arrow) as a decorative element in running headers. These won't match the pipe pattern or a static set. Detect them by checking for the character directly:

```python
PRIVATE_CHAR = '\uf03c'   # adjust codepoint if needed

def is_running_header(line):
    if PRIVATE_CHAR in line:
        return True
    if RUNNING_HEADER_RE.match(line):
        return True
    return False
```

To find which private-use codepoint(s) a file uses:

```python
python3 -X utf8 -c "
import re, collections
with open('input.txt', encoding='utf-8') as f:
    text = f.read()
pua = re.findall(r'[\ue000-\uf8ff]', text)
print(collections.Counter(pua).most_common(10))
"
```

If any codepoint appears frequently, inspect the lines containing it — they are almost certainly running headers.

**Option D — no-pipe headers with character-reversed Hebrew (bidi artifact).** Some PDFs produce running headers with no `|` separator at all. Instead:
- Even pages: `BOOK_TITLE NN` (book title + space + page number, no pipe)
- Odd pages: `NN REVERSED_NAME` — the chapter name appears with **all characters reversed** due to a pdftotext bidi rendering artifact (e.g. `הקדמה` → `המדקה`, `מבוא` → `אומב`, `מכירות משחקים בספורט :רקע כללי` → `יללכ עקר :טרופסב םיקחשמ תוריכמ`)

Detect with a book-specific function rather than `RUNNING_HEADER_RE`:

```python
def is_running_header(s):
    # Even pages: book title + page number (no pipe)
    if re.match(r'^BOOK_TITLE \d+$', s):
        return True
    # Odd pages: 1-3 digit page number + space + short Hebrew text (reversed chapter name)
    # Length guard prevents eating long body lines that happen to start with a number
    if re.match(r'^\d{1,3} [\u0590-\u05FF]', s) and len(s) < 50:
        return True
    return False
```

Replace `BOOK_TITLE` with the actual book title string (exact, after bidi cleaning). You don't need to enumerate the reversed chapter names — the length-guarded number+Hebrew pattern catches all of them. Call `is_running_header(s)` in the body loop instead of `RUNNING_HEADER_RE.match(s)`.

To confirm this is the pattern, look for short lines starting with a 1–3 digit number followed by Hebrew text, and verify the Hebrew is indeed a reversed chapter name from the TOC.

**Option E — dual-layer "Optimized" scanned PDF (rawdict extraction).** Some OCR'd PDFs — often named `*_Optimized.pdf` or produced by Adobe Acrobat OCR — contain two overlapping text layers: the original visual-order scan glyphs AND a separately added OCR layer. `pdftotext` and `get_text('words')` both read the glyph layer, returning reversed Hebrew characters. The fix is `get_text('rawdict')` on each page, filtering out **invisible blocks** (whose bounding box coordinates are near ±2³¹):

```python
HUGE = 1e9   # bounding box value indicating an invisible/dummy block

def extract_page_rawdict(page):
    """Extract lines from the OCR text layer only (visible blocks)."""
    d = page.get_text('rawdict')
    line_chars   = {}   # y_key → [char, ...]
    line_right_x = {}   # y_key → max x (rightmost = first char in RTL)

    for b in d['blocks']:
        if b.get('type') != 0: continue
        bbox = b.get('bbox', (0, 0, 0, 0))
        if abs(bbox[0]) > HUGE or abs(bbox[2]) > HUGE:
            continue   # invisible block — skip
        for line in b.get('lines', []):
            for span in line.get('spans', []):
                if span.get('size', 0) >= 18:
                    continue   # skip heading-size text (chapter titles, etc.)
                for c in span.get('chars', []):
                    ch = c.get('c', '')
                    ox, oy = c.get('origin', (0, 0))
                    y_key = round(oy / 4) * 4
                    line_chars.setdefault(y_key, []).append(ch)
                    if ch.strip() and ox > line_right_x.get(y_key, 0):
                        line_right_x[y_key] = ox

    return [(y, ''.join(v).strip(), line_right_x.get(y, 0))
            for y, v in sorted(line_chars.items()) if ''.join(v).strip()]
```

**How to detect this situation:** run `get_text('words')` on a content page and check whether the extracted words are reversed Hebrew (e.g. `'אובמ'` instead of `'מבוא'`). If so, switch to `rawdict` extraction. The invisible blocks have `|bbox[0]| > 1e9`; visible blocks have normal float coordinates and carry the correct OCR text in logical order with spaces preserved as separate space-only spans (so do not skip spans where `t.strip() == ''`).

**Paragraph detection for rawdict extraction** — since the text is not line-separated by blank lines, use per-page adaptive RTL indentation: the first (rightmost) character of an indented paragraph line sits measurably left of the page's right margin. Compute the threshold per page rather than using a fixed value, because chapter-opening pages often have slightly different typography:

```python
def compute_indent_threshold(lines, header_max_y=104):
    """75th-percentile rightmost-x across body lines, minus 18pt."""
    xs = [rx for y, t, rx in lines
          if y > header_max_y and rx > 50 and not is_ocr_garbage(t)]
    if not xs:
        return 460.0   # fallback
    xs.sort()
    return xs[int(len(xs) * 0.75)] - 18

# In the extraction loop:
indent_thresh = compute_indent_threshold(lines)
for y, text, first_x in lines:
    if y <= header_max_y: continue          # running header
    if is_ocr_garbage(text): continue
    if first_x < indent_thresh and first_x > 50 and current:
        flush()   # new paragraph
    current.append(text)
```

**Skip heading spans by size** — filtering `span.get('size', 0) >= 18` inside the rawdict loop removes chapter titles, chapter number labels, and TOC entries automatically, without needing to list them in `skip_exact`.

### Step 3.25 — Fix inline footnote references

Endnote/footnote superscripts in the original PDF appear as plain inline digits after `pdftotext` extraction. Two common forms:

| Extracted text | Original | Fix |
|---|---|---|
| `ריזלינג5.` | `ריזלינג`<sup>5</sup>`.` | `ריזלינג<sup>5</sup>.` |
| `"חיים נכון"2.` | `"חיים נכון"`<sup>2</sup>`.` | `"חיים נכון"<sup>2</sup>.` |
| `הרהור רדיקלי" 3.` | `הרהור רדיקלי"`<sup>3</sup>`.` | same with `<sup>` |
| `Stevenson(.3)` | `Stevenson`<sup>3</sup>`.` | `(.N)` → `<sup>N</sup>` |

Apply `fix_footnotes()` to each paragraph **after** HTML-escaping `&` (so the inserted `<sup>` tags are not escaped). Hebrew text rarely contains literal `<` or `>` so those don't need escaping.

```python
FOOTNOTE_RE = re.compile(r'(?<=[^\d\s,.;:\u05be])( ?)(\d{1,2})\.(?!\d)')

def fix_footnotes(s):
    # (.N) pdftotext artifact variant (RTL/LTR bidi reordering of superscript + period)
    s = re.sub(r'\(\.(\d{1,2})\)', r'<sup>\1</sup>', s)
    # Standard variant: letter/punct then optional space then 1-2 digits then period
    s = FOOTNOTE_RE.sub(lambda m: f'{m.group(1)}<sup>{m.group(2)}</sup>.', s)
    return s
```

Call it in `build_chapter_html` when rendering each paragraph:

```python
for b in blocks:
    escaped = b.replace('&', '&amp;')
    escaped = fix_footnotes(escaped)
    parts.append(f'<p>{escaped}</p>')
```

The lookbehind `(?<=[^\d\s,.;:\u05be])` prevents matching numbers inside years (`1926`), measurements (`1,200`), or after colons (`:3חוזרים לווגאס` film titles). The `(?!\d)` lookahead prevents matching partial multi-digit numbers.

### Step 3.5 — Extract figures from the PDF (vector graphics: charts, scatter plots, diagrams)

Charts, scatter plots, and diagrams in PDFs are almost always **vector graphics** — `pdfimages` will not capture them, but `page.get_drawings()` returns their paths. Use **PyMuPDF** (`fitz`) to render the relevant PDF pages and crop out just the figure area. For **raster images** (photographs, historical illustrations, maps), see Step 3.6 instead — the approach is different.

**How to tell which type you have:** inspect a page with an image using `page.get_drawings()` and `page.get_images()`. If `get_drawings()` returns many paths → vector. If `get_images()` returns entries and `get_drawings()` is sparse (just border lines) → raster.

**Prerequisites:** `pip install pymupdf pillow` (Pillow is needed for any post-crop manipulation).

**How it works end-to-end:**

1. **Build a page map** — scan each PDF page's first text block (the running header, at y ≤ 80pt) to extract the book page number. Both header formats are handled:
   - Even pages: `25 | book title` → extracts 25
   - Odd pages: `author | 26` → extracts 26
   After building the map, fill in **gap pages** — figure-only pages that have no running header and therefore don't appear in the map. If book pages N and N+2 are both mapped to consecutive PDF indices, page N+1 → PDF index N+1.

2. **Find figure captions** in the text file. Hebrew books typically use `איור :N` (number after colon), `תרשים :N`, etc. Scan with:
   ```python
   CAPTION_RE = re.compile(r'^(איור|תרשים|גרף|טבלה)\s+:\d+')
   ```
   For each caption line, locate the book page number by searching **both backward and forward** up to ~50 lines. Use a **gap heuristic**: if forward_page = backward_page + 2 AND the forward page is within 1.5× the backward distance, the figure is on the gap page between them (a figure-only page with no page number in the extracted text).

3. **Render and crop** the PDF page with PyMuPDF:
   ```python
   def crop_figure(pdf_page, scale=2.0):
       blocks  = pdf_page.get_text('blocks')
       page_h  = pdf_page.rect.height
       y_top   = 70   # skip running header
       y_bottom = page_h
       # Find where body text resumes after the figure
       # (tall block with Hebrew content, below all vector drawings)
       for b in [b for b in blocks if b[1] > 70]:
           if b[3]-b[1] > 30 and len(clean(b[4])) > 60 and has_hebrew(clean(b[4])):
               drawings = pdf_page.get_drawings()
               if drawings:
                   max_dy = max(d['rect'][3] for d in drawings if d['rect'])
                   if b[1] > max_dy:
                       y_bottom = b[1]; break
               else:
                   y_bottom = b[1]; break
       clip = fitz.Rect(0, max(0, y_top-8), pdf_page.rect.width, min(page_h, y_bottom))
       pix  = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
       return pix.tobytes('png')
   ```
   The crop skips the running header (top ~70pt) and stops at the first body-text paragraph after the figure. Vector drawings are used to validate the y_bottom cut-off.

4. **Embed in EPUB** — add `EpubItem` entries with `media_type='image/png'` and inject `<div class="figure"><img .../></div>` blocks at the caption's position in the chapter HTML. The `process_chapter` function is extended to return a mixed list of string paragraphs and `{'type':'figure', ...}` dicts; `build_chapter_html` renders each accordingly.

**Image embedding checklist:**

```python
# 1. Add to manifest (before building chapters)
book.add_item(epub.EpubItem(
    uid=f'img_{fig_id}',
    file_name=f'Images/{fig_id}.png',   # lives at EPUB/Images/fig_NNN.png
    media_type='image/png',
    content=img_bytes,                  # bytes from pix.tobytes('png')
))

# 2. Reference in HTML — CRITICAL: use a path relative to the chapter file's
#    location within the EPUB package (EPUB/chapter_NN.xhtml → EPUB/Images/).
#    Both the chapter and the Images/ folder are inside EPUB/, so the correct
#    relative path is just 'Images/fig_NNN.png' — NOT '../Images/fig_NNN.png'.
#
#    '../Images/' goes UP from EPUB/ to the zip root, then looks for Images/
#    at the zip root — that folder does not exist, so readers show a broken icon.
#    The same applies to any EPUB reader, but Chrome EPUBReader is particularly
#    strict and will show a spinning placeholder for every broken image src.
f'<div class="figure"><img src="Images/{fig_id}.png" alt="{caption}"/></div>'
```

**Why `Images/` not `../Images/`:**  
All content files (`chapter_NN.xhtml`, `Styles/style.css`, `Images/`, `Fonts/`) live under the same `EPUB/` directory. From `EPUB/chapter_02.xhtml`, the relative path to `EPUB/Images/fig_001.png` is simply `Images/fig_001.png`. Using `../Images/` navigates up to the zip container root first, where there is no `Images/` folder.

Note: `../Styles/style.css` in `<link>` tags uses the same wrong pattern — some readers tolerate it for CSS but not for images. Always use same-directory-relative paths: `Styles/style.css`, `Images/fig.png`, `Fonts/font.ttf`.

**CSS to add for figures:**
```css
div.figure { text-align: center; margin: 1.5em 0; page-break-inside: avoid; }
div.figure img { max-width: 100%; height: auto; }
p.caption { direction: rtl; text-align: right; font-size: 0.9em; color: #333;
             text-indent: 0; margin: 0.3em 0 1em 0; }
```

**Verify images after generation:**
```python
import zipfile
z = zipfile.ZipFile('output.epub')
for name in z.namelist():
    if name.startswith('EPUB/Images/'):
        print(name, z.getinfo(name).file_size, 'bytes')
# All images must be non-zero bytes.
# Also confirm img src in at least one chapter:
import re
for ch in z.namelist():
    if ch.endswith('.xhtml'):
        c = z.read(ch).decode('utf-8')
        for src in re.findall(r'src="([^"]+\.png)"', c):
            print(ch, '->', src)
```

**Known pitfalls (vector-graphic figures):**

- **Images not visible in Chrome EPUBReader** — almost always a wrong `src` path. Use `Images/fig_NNN.png` (not `../Images/`). Patch an existing EPUB by rewriting the zip: read each `.xhtml`, call `.replace('src="../Images/', 'src="Images/')`, rewrite.
- **Figure-only pages** (no running header in text) → the gap-fill and gap-heuristic in `find_book_page` handle this.
- **Gap heuristic fires incorrectly** when a figure is in the *middle* of a text page: backward=17 lines, forward=49 lines. Guard: only use the gap if `fwd_dist ≤ back_dist × 1.5`.
- **Hebrew caption format** varies: `איור 1:` vs `איור  :1` (number after colon) vs `איור :1` — inspect the file before writing `CAPTION_RE`.
- **Full-page figure with no body text resuming** — `y_bottom` stays at `page_h`, giving a full-page crop. This is correct behaviour.
- **Pipe variant `| 12יעקב בורק`** (no space between number and name) — add `^\| \d+` branch to `RUNNING_HEADER_RE` when building the page map.

---

### Step 3.6 — Raster images (photographs, historical illustrations)

Some books embed **raster (bitmap) images** — photographs, historical illustrations, maps — rather than vector graphics. `page.get_drawings()` returns nothing for these; you must use `page.get_images()` to detect them.

**First, scan all PDF pages for raster content:**

```python
import fitz, re, collections

doc = fitz.open(PDF_FILE)
BIDI_RE = re.compile(r'[\u200f\u200e\u202a\u202b\u202c\u202d\u202e\u200b\u200c\u200d]')
def clean(s):
    return BIDI_RE.sub('', s).replace('\x0c','').replace('\x04','').strip()

for pdf_idx in range(len(doc)):
    page = doc[pdf_idx]
    imgs = page.get_images(full=True)
    if not imgs:
        continue
    blocks = page.get_text('blocks')
    # Get book page number
    pg_num = next((clean(b[4]).strip() for b in blocks
                   if re.match(r'^\d+$', clean(b[4]).strip())), '?')
    # Show all text blocks with y-positions (to understand layout)
    print(f'PDF {pdf_idx} (book p{pg_num}): {len(imgs)} images')
    for b in sorted(blocks, key=lambda x: x[1]):
        t = clean(b[4])
        if t and t != pg_num:
            print(f'  y={b[1]:.0f}-{b[3]:.0f}: {repr(t[:80])}')
```

This reveals:
- Which pages have raster images
- The y-positions of captions relative to body text and running headers
- Whether images are at the **top** of the page (caption below, body text below caption) or **bottom** (body text above, caption near bottom)

**Identify caption style.** Raster-image books often use free-form captions — not the `איור :N` numbered format used for charts. Instead, captions are short descriptive lines like `'ספינת קרב אנגלית ,המאה ה–16'` or `'מפת המזרח הקדום ,הכוללת את שומר ומצרים התחתונה'`. These appear in the extracted text file and can be found by substring search.

**Map each image to a text-file line.** Search for a unique fragment of the caption near its expected line number:

```python
def find_caption_line(lines, fragment, start_hint, window=15):
    """Return the line index whose cleaned text contains `fragment`,
    searching within `window` lines of `start_hint`."""
    best = None
    for i in range(max(0, start_hint - window), min(len(lines), start_hint + window)):
        if fragment in clean(lines[i]):
            if best is None or abs(i - start_hint) < abs(best - start_hint):
                best = i
    return best
```

**Manually specify crop coordinates.** Unlike vector figures (where `crop_figure()` auto-detects the image bounds), raster images require you to specify `y_start` and `y_end` per image after inspecting the block output above. Typical patterns (page height ≈ 560pt, running header ends ≈ 57pt):

| Layout | y_start | y_end |
|---|---|---|
| Image fills whole page | 57 | 560 (page bottom) |
| Image at top, body text below | 57 | caption_y + 12 |
| Two images stacked, no body text | 57 / prev_caption_y+12 | next_caption_y+12 / 560 |
| Image at bottom, body text above | last_footnote_y + 10 | 560 |
| Image at top, body text below | 57 | caption_y + 12 |

Build an `IMAGE_PAGE_SPECS` list — one entry per image (not per page):

```python
IMAGE_PAGE_SPECS = [
    # (pdf_idx, book_pg, [(caption_fragment, hint_line_idx, y_start, y_end), ...])
    (20, 21, [
        ('מפת המזרח הקדום',         450, 57,  272),   # image at top half
        ('מצרי קדום עם טרנסליטרציה', 452, 272, 560),   # image at bottom half
    ]),
    (21, 22, [
        ('כתב הירוגליפים מצרי',     456, 57,  250),
        ('כתב יתדות שּומרי',        458, 250, 560),
    ]),
    (58, 59, [
        ('קמע מודפס בערבית',        1585, 320, 560),   # image at bottom
    ]),
    # ... one tuple per image
]
```

**Render each crop:**

```python
def render_crop(pdf_page, y_start, y_end, scale=2.0):
    w = pdf_page.rect.width
    h = pdf_page.rect.height
    clip = fitz.Rect(0, max(0, y_start), w, min(h, y_end))
    pix = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    return pix.tobytes('png')

def extract_raster_figures(lines, pdf_doc):
    figures = {}
    counter = 0
    for pdf_idx, book_pg, cap_specs in IMAGE_PAGE_SPECS:
        pdf_page = pdf_doc[pdf_idx]
        for frag, hint_idx, y_start, y_end in cap_specs:
            line_idx = find_caption_line(lines, frag, hint_idx)
            if line_idx is None:
                print(f'  [warn] caption not found: {repr(frag)} near idx {hint_idx}')
                continue
            counter += 1
            fig_id    = f'fig_{counter:03d}'
            img_bytes = render_crop(pdf_page, y_start, y_end)
            figures[line_idx] = {
                'id': fig_id,
                'img_bytes': img_bytes,
                'caption': clean(lines[line_idx]),
            }
            print(f'  [figure] {fig_id} @ line {line_idx+1}: {clean(lines[line_idx])[:55]}')
    return figures
```

**Known pitfalls (raster images):**

- **Caption fragment contains special characters** (quotes, dashes) — use a safe interior substring that avoids them. E.g. for `'"אלפבית" מצרי קדום עם ...'` use fragment `'מצרי קדום עם טרנסליטרציה'` instead of the full string with embedded quotes.
- **Section headings look like captions** — on pages with images at the top followed by a section heading and body text, the heading (e.g. `'סחר בינלאומי'`) may appear at a similar y-position to a caption. It is NOT a caption; don't include it in `cap_specs`. Check: captions describe the image (time period, place, subject); headings introduce the next section.
- **Caption continuation lines** — some captions span two lines in the PDF (e.g. `'סידור מוכן להדפסה של ספר משנת 1733\nבטכנולוגיית הדפוס הנייד שהמציא גוטנברג'`). The second line appears as a separate entry in the text file. The `hint_idx` should point to the FIRST line; the second line will appear in the chapter as normal text, which is fine since it reads naturally as a caption continuation.
- **`get_images()` returns cover/title-page images** — pages without a book page number in their text blocks are front-matter (cover art, title page). Skip them by checking `pg_num is None`.
- **y_start for bottom-of-page images** — the image starts right after the last body/footnote block. Inspect the block output to find `last_footnote_y` and add ~10pt padding. Don't guess; use the actual value from the scan output.
- **Raster scan silently omitted from generated script** — the most common cause of missing raster images is that the Step 3.6 PDF scan was never run and no `IMAGE_PAGE_SPECS` / figure extraction code was added to the script at all. **Always run the raster scan (`page.get_images()` loop) before finalising the script**, even when the book appears to be text-only. If `get_images()` returns results on any page, add the `extract_raster_figures` function and `IMAGE_PAGE_SPECS`; if it returns nothing on all pages, explicitly note that no raster figures exist. Skipping this check is the primary reason images silently disappear from the output EPUB.

### Step 3.7 — Tables (space-aligned format from pdftotext -layout)

`pdftotext -layout` preserves column alignment using spaces. Tables are identified by a caption line (`^טבלה :N ...`) and parsed by reading the column positions from the header row. The `clean()` function must **not** be used when extracting column positions — it strips leading spaces, destroying alignment. Use a separate `_clean_nws()` (no whitespace strip) instead.

**Table structure in extracted text:**
- Caption: `טבלה :1 title text` (may wrap to next line)
- Optional blank line
- Header row: columns separated by **2+ spaces** (use `\S(?:[^ \n]| (?! ))*` regex)
- Data rows: values at the same character x-positions as header segments
- End: blank line followed by body text (long paragraph at low indent)

**Two table formats exist in the same book:**
1. **Dense format** — no blank lines between rows; ends at first blank line before body text
2. **Sparse format** — blank lines between each row; end detected by peeking ahead after each blank line

**End-of-table heuristic:** a line is body text if `leading_spaces <= 2 AND len(content) > 35`. This threshold (35 chars) separates long paragraphs from short table cells and footnotes. `leading_spaces` is computed from the **raw** line (not cleaned) with `len(line) - len(line.lstrip(' '))`.

**RTL column reversal:** `pdftotext` outputs columns left-to-right by physical x-position. For RTL HTML tables with `direction: rtl`, reverse the column order so the rightmost physical column (Hebrew text column) becomes the first HTML column (displayed on the right).

**Continuation rows:** a table line with content in only one column (and a current row already started) is a continuation — merge its cell value into the existing row instead of starting a new row.

**Key code:**

```python
def _clean_nws(raw_line):
    """Strip bidi marks but preserve leading spaces for column alignment."""
    return BIDI_RE.sub('', raw_line).replace('\x0c', '').replace('\x04', '')

def _line_segs(raw_line):
    """Return [(text, start, end)] for segments separated by 2+ spaces."""
    c = _clean_nws(raw_line)          # ← _clean_nws, NOT clean()
    segs = []
    for m in re.finditer(r'\S(?:[^ \n]| (?! ))*', c):
        t = m.group().strip()
        if t:
            segs.append((t, m.start(), m.end()))
    return segs

def _is_body_text(raw_line):
    s = normalize_ws(clean(raw_line))
    if not s or re.match(r'^טבלה\s*:\d', s):
        return False
    return (len(raw_line) - len(raw_line.lstrip(' '))) <= 2 and len(s) > 35
```

**CSS for tables:**
```css
div.table-wrap { margin: 1.5em 0; overflow-x: auto; }
p.table-caption { direction: rtl; text-align: right; font-weight: bold;
                  font-size: 0.9em; text-indent: 0; margin-bottom: 0.3em; }
table { border-collapse: collapse; width: 100%; direction: rtl; font-size: 0.9em; }
th, td { border: 1px solid #bbb; padding: 0.3em 0.6em; text-align: right; }
thead tr { background-color: #eee; }
```

**Integration in `process_chapter`:** pre-scan for table regions with `_find_table_regions(all_lines, start, end)` which returns `{caption_line: (TableBlock, last_consumed_line)}`. In the main line loop, inject `TableBlock` at the caption line and skip all consumed lines. Handle `TableBlock` in `apply_citations()` (skip it) and `build_chapter_html()` (render with `render_table_html()`).

**Known limitations:**
- Cells that span multiple rows in the original PDF may appear merged (the bidi-extracted lines for continuation cells get combined into the previous row's cell).
- Missing offense types (empty cells) in the extraction are a PDF bidi artifact — nothing can be done.
- `PyMuPDF find_tables()` does not reliably detect Hebrew academic tables in this type of book; stick to text-based parsing.

---

### Step 3.8 — In-chapter section headers (bold/large centered text)

Books often use short bold or large-font titles to divide chapters into named sections. In `pdftotext` output these appear as **short lines surrounded by empty lines** — the centering and formatting are lost, but the isolation between empty lines is preserved.

**Two forms exist:**

| In PDF | In extracted text |
|---|---|
| Single-line: `ההבדל בין הצלחה לכישלון` | One short line, empty line before, empty line after |
| Two-line: `אמנו מחדש את מוחכם:` / `מילה אחת בכל פעם` | Two short lines, empty line before, empty line after |

**Detection predicate** — a line is a section header if it is short, has no sentence-ending punctuation, no inline commas, doesn't start with an em-dash (attribution line), and doesn't end with a dangling grammatical particle:

```python
_DANGLING = {'את', 'של', 'עם', 'אל', 'כי', 'לא', 'עד', 'כך', 'הם', 'הן', 'כן'}

def is_section_header(s):
    last_word = s.rsplit(None, 1)[-1] if s else ''
    return (len(s) > 2 and len(s) < 40
            and not s.endswith('.')
            and not s.endswith(',')
            and not s.endswith('?')
            and not s.endswith('!')
            and ',' not in s
            and not s.startswith('—')   # attribution lines: "— אפיקטטוס"
            and last_word not in _DANGLING
            and not is_page_number(s)
            and not is_running_header(s)
            and not is_chapter_marker(s))
```

**Key guards explained:**
- `len < 40` — real section titles are short; body text lines that happen to be isolated are usually longer
- `not endswith('?')` / `not endswith('!')` — sentence fragments that happen to be alone on a line (e.g. `'לשום מקום?'`, `'מקרים קשים של שיח פנימי שלילי!'`)
- `',' not in s` — body text fragments contain commas; titles don't (e.g. `'ותסכול כלפיהן ,אני מפגין סקרנות'` is a false positive)
- `not s.startswith('—')` — author/quote attribution lines (`'— אפיקטטוס'`) look like headers but aren't
- `last_word not in _DANGLING` — lines ending with `'את'`, `'של'` etc. are sentence fragments, not titles

**Detection in the body loop** — use a `skip_next` flag to handle two-line headers without converting to a while-loop:

```python
skip_next = False

for i in range(idx, end):
    if skip_next:
        skip_next = False
        prev_empty = False
        continue

    s = all_lines[i]
    # ... (handle empty lines, running headers, page numbers as usual) ...

    # Section header detection: short line(s) surrounded by empty lines
    if prev_empty and not current:
        next_s  = all_lines[i+1] if i+1 < end else ''
        next2_s = all_lines[i+2] if i+2 < end else ''

        if not next_s and is_section_header(s):
            # Single-line header
            blocks.append(('h3', s))
            prev_empty = False
            continue

        if next_s and not next2_s and is_section_header(s) and is_section_header(next_s):
            # Two-line header — combine and skip the second line
            blocks.append(('h3', s + '<br/>' + next_s))
            skip_next = True
            prev_empty = False
            continue

    current.append(s)
    prev_empty = False
```

**Rendering in `build_chapter_html`:**

```python
for kind, text in blocks:
    if kind == 'h3':
        parts.append(f'<h3>{text}</h3>')
    else:
        parts.append(f'<p>{escape_html(text)}</p>')
```

**CSS:**
```css
h3 { direction: rtl; text-align: right; font-size: 1.1em; font-weight: bold;
     margin-top: 1.2em; margin-bottom: 0.4em; }
```

**Debugging** — after generation, print all detected headers to confirm no false positives and no missed headers:

```python
for ci, (start, num, name, sub) in enumerate(CHAPTER_STARTS):
    end = CHAPTER_STARTS[ci+1][0] if ci+1 < len(CHAPTER_STARTS) else len(all_lines)
    blocks = process_chapter(start, end, num, name, sub)
    headers = [t for k, t in blocks if k == 'h3']
    if headers:
        print(f'Ch {ci+1} ({name}): {headers}')
```

Compare against the PDF's section titles to catch missed headers (need wider `len < 40` threshold?) or false positives (need additional guards?).

**Note:** not all books have in-chapter section headers. If a book has none, this detection is harmless — no headers will be found and paragraphs are unaffected.

---

### Step 3.9 — RTL numbered bullet lists (pdftotext reversal artifact)

`pdftotext` extracts RTL numbered lists with the number and dot **after** the text — but because the text is read right-to-left, the extracted line appears as `.1text` (dot, number, then text with no space). This is the opposite of what you'd expect from a standard `1. text` list.

**Detection and formatting:**

```python
BULLET_RE = re.compile(r'^\.(\d{1,3})(.*)')

def is_bullet_item(s):
    m = BULLET_RE.match(s)
    if not m:
        return False
    rest = m.group(2).strip()
    if not rest:
        return False
    # rest must start with a letter (Hebrew or Latin) — rejects years (.2016),
    # page ranges (.51-48), standalone numbers (.25), date strings (.2014 , text)
    return bool(re.match(r'^[\u0590-\u05FF\u0041-\u007A\u00C0-\u00FF"״׳]', rest))

def format_bullet(s):
    m = BULLET_RE.match(s)
    if m:
        return f'{m.group(1)}. {m.group(2).strip()}'
    return s
```

**Why `\d{1,3}`:** endnote books may have footnote numbers up to 3 digits (e.g. `.109`). Using `\d{1,2}` would miss them.

**Why the letter guard:** many lines that look like `.NNN` are NOT list items — years (`.2016`), page ranges (`.51-48`), standalone numbers (`.25`). Requiring the rest to start with a Hebrew or Latin letter rejects all of these without any false negatives on real list items.

**Integration in `process_chapter`** — use an `in_list_item` flag and a `flush()` helper so continuation lines join the same `li` block:

```python
in_list_item = False

def flush():
    nonlocal current, in_list_item
    if current:
        kind = 'li' if in_list_item else 'p'
        blocks.append((kind, ' '.join(current)))
        current = []
        in_list_item = False

# In body loop:
if is_bullet_item(s):
    flush()
    current = [format_bullet(s)]
    in_list_item = True
    prev_empty = False
    continue
```

**Rendering in `build_chapter_html`** — list items use `<p class="list-item">` (not `<li>` inside `<ol>`, because EPUB RTL list rendering is inconsistent across readers):

```python
for kind, text in blocks:
    if kind == 'h3':
        parts.append(f'<h3>{text}</h3>')
    elif kind == 'li':
        parts.append(f'<p class="list-item">{fix_footnotes(escape_html(text))}</p>')
        # list items are never 'first' for no-indent purposes
    else:
        attr = ' class="no-indent"' if first else ''
        parts.append(f'<p{attr}>{fix_footnotes(escape_html(text))}</p>')
        first = False
```

**CSS:**
```css
p.list-item { direction: rtl; text-align: right; text-indent: 0;
              margin: 0.5em 0 0.5em 0; padding-right: 0.5em; }
```

---

### Step 3.7 — Inline academic citations (bidi-mangled format)

Academic Hebrew books extracted from PDF often contain inline citations where bidi processing has **reversed the parentheses**, producing artifacts like:

| Raw (after bidi clean) | Original intent |
|---|---|
| `( .)Cashmore, 2003` | `(Cashmore, 2003)` |
| `(,)Conn, 1997; Moore, 2016` | `(Conn, 1997; Moore, 2016)` |
| `(.)Kunkel & Biscaia, 2020` | `(Kunkel & Biscaia, 2020)` |
| `()Blanden, Gregg & Machin, 2005` | `(Blanden, Gregg & Machin, 2005)` |
| `(האילן ומוכתר, 2022)` | normal Hebrew-author citation (stays intact) |

The fix: replace all citation artifacts with `[N]` superscripts inline and render the full citations as a numbered list at the bottom of each chapter.

**Detection heuristic** — a match is a real citation only if it contains a 4-digit year. This filters out English terms like `( ,)fair play` and `( )city-state` that share the same artifact format.

```python
# ── Citation processing ───────────────────────────────────────────────────────
CITE_MANGLED_RE = re.compile(r'\([.,\s]*\)([^()\u0590-\u05FF\n]+)')
CITE_NORMAL_RE  = re.compile(r'\(([A-Za-z\u0590-\u05FF\xC0-\xFF][^()]*?\d{4}[a-z]?[^()]{0,30}?)\)')
YEAR_RE         = re.compile(r'\d{4}')

def apply_citations(blocks):
    """Replace inline citation artifacts with [N] superscripts.
    Returns (processed_blocks, {n: citation_text}) for footnote rendering."""
    cite_map  = {}   # canonical_text -> n
    cite_list = {}   # n -> canonical_text
    counter   = [0]

    def register(raw):
        key = raw.strip().rstrip('.,; ')
        if not key or not YEAR_RE.search(key) or len(key) < 5:
            return None
        if key not in cite_map:
            counter[0] += 1
            cite_map[key] = counter[0]
            cite_list[counter[0]] = key
        return cite_map[key]

    new_blocks = []
    for block in blocks:
        text = str(block)

        def sub_mangled(m, _reg=register):
            n = _reg(m.group(1))
            return f'<sup>[{n}]</sup>' if n else m.group(0)

        def sub_normal(m, _reg=register):
            n = _reg(m.group(1))
            return f'<sup>[{n}]</sup>' if n else m.group(0)

        text = CITE_MANGLED_RE.sub(sub_mangled, text)
        text = CITE_NORMAL_RE.sub(sub_normal, text)
        new_blocks.append(text)

    return new_blocks, cite_list
```

**Rendering in HTML** — blocks now contain `<sup>[N]</sup>` tags, so escape only the non-tag parts:

```python
safe = re.sub(r'(<sup>\[\d+\]</sup>)|(.)',
              lambda m: m.group(1) if m.group(1) else escape_html(m.group(2)),
              para)
parts.append(f'<p{attr}>{safe}</p>')
```

**Footnote section** — append to each chapter's `<body>` before `</body>`:

```python
if chapter_cites:
    parts.append('<div class="footnotes"><hr/><ol>')
    for n in sorted(chapter_cites):
        parts.append(f'<li id="fn{n}">{escape_html(chapter_cites[n])}</li>')
    parts.append('</ol></div>')
```

**CSS additions:**
```css
div.footnotes { border-top: 1px solid #999; margin-top: 2em; padding-top: 0.5em; }
div.footnotes ol { direction: ltr; text-align: left; font-size: 0.85em; color: #444; padding-left: 2em; margin: 0; }
div.footnotes li { margin: 0.3em 0; }
sup { font-size: 0.75em; }
```

**In the main loop:**
```python
blocks = process_chapter(start, end, ch_name, ch_sub, ch_num, lines)
blocks, chapter_cites = apply_citations(blocks)
html_str = build_chapter_html(ch_num, ch_name, ch_sub, blocks, chapter_cites)
```

**Note:** The `רשימת מקורות` (bibliography) chapter at the end of academic books typically gets a few false-positive citation matches (e.g. year numbers in the bibliography entries). This is harmless — the footnotes at the bottom of the bibliography chapter will be duplicates of entries already in the bibliography itself, and can be ignored or suppressed by skipping `apply_citations` for the bibliography chapter.

---

### Step 4 — Generate the EPUB

Use the Python script template below. Run it with:
```bash
python3 -X utf8 make_epub.py
```

**Always use `-X utf8`** on Windows to avoid cp1255/cp1252 codec errors with Hebrew/Unicode filenames and content.

**Font:** For Hebrew books, embed Frank Ruhl Libre (see [Font Resources](#font-resources) below). Set `FONT_DIR` in the script to `h:\My Drive\misc\fonts` — the Regular and Bold TTF files are already extracted there.

**Cover image — extracting from the PDF when no separate file exists:** PDF page 0 is almost always the cover. Render it at 2× and save as JPEG:

```python
import fitz
doc = fitz.open(PDF_FILE)
pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
pix.save('cover.jpg')
```

Then set `COVER_IMAGE = r'cover.jpg'` in the script. This produces a clean ~280KB cover that EPUB readers display in the library thumbnail.

**Cover spine placement:** After calling `book.set_cover(...)`, retrieve the generated cover page and prepend it to the spine so readers open directly to the cover:

```python
book.set_cover('cover.jpg', cover_data)
cover_page = book.get_item_with_id('cover')   # the auto-generated cover XHTML
# Then in spine:
book.spine = ([cover_page] if cover_page else []) + ['nav'] + epub_chapters
```

**Paragraph spacing — always use a visible bottom margin:** Blank lines in the source text (empty lines between paragraphs, section breaks, page breaks) all become paragraph boundaries in the EPUB. These must be **visually distinguishable** — use `margin-bottom: 0.8em` on `p` elements so readers can clearly see where one paragraph ends and the next begins. Do **not** use `margin: 0` or a tiny value like `0.1em`; the result looks like a wall of indented text with no breathing room.

```css
p { margin: 0 0 0.8em 0; text-indent: 1.5em; }
```

This value (`0.8em`) is already set in the `RTL_CSS` and `LTR_CSS` templates above.

### Step 5 — Verify

```python
import zipfile, re
z = zipfile.ZipFile('output.epub')
for name in z.namelist():
    print(name, z.getinfo(name).file_size, 'bytes')

content = z.read('EPUB/chapter_01.xhtml').decode('utf-8')
hebrew = re.findall(r'[\u0590-\u05FF]+', content)
print(f'{len(hebrew)} Hebrew words in chapter 1')
print(content[:800])
```

All chapter `.xhtml` files must be **non-zero bytes**. If any are 0 bytes, see the debugging section below.

---

## Python Script Template

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert text file (+ optional PDF) to EPUB. Run with: python3 -X utf8 make_epub.py"""

import re
import fitz          # PyMuPDF — pip install pymupdf   (only needed when PDF_FILE is set)
from ebooklib import epub
from ebooklib import utils as epub_utils

INPUT_FILE   = r'path\to\input.txt'
# Naming convention: <book title>-<author last names separated by spaces>.epub
# Examples: 'לחשוב כמו פריק-לוויט דובנר.epub', 'התנור והחמאה-פוגל.epub'
OUTPUT_FILE  = r'path\to\<title>-<last names>.epub'
PDF_FILE     = r'path\to\source.pdf'   # set to None to skip figure extraction
COVER_IMAGE  = r'path\to\cover.jpg'    # set to None to skip cover; JPEG or PNG
BOOK_LANG    = 'he'   # 'he' or 'en'
IS_RTL       = True   # True for Hebrew/Arabic
FONT_DIR     = r'C:\Users\User\.claude\fonts'

# Caption pattern — inspect the file first; Hebrew books vary:
#   'איור 1:'  →  CAPTION_RE = re.compile(r'^(איור|תרשים|גרף|טבלה)\s*\d+')
#   'איור  :1' →  CAPTION_RE = re.compile(r'^(איור|תרשים|גרף|טבלה)\s+:\d+')
CAPTION_RE  = re.compile(r'^(איור|תרשים|גרף|טבלה)\s+:\d+')

RTL_CSS = """
@font-face {
    font-family: 'FrankRuhlLibre';
    src: url('Fonts/FrankRuhlLibre-Regular.ttf'); font-weight: normal;
}
@font-face {
    font-family: 'FrankRuhlLibre';
    src: url('Fonts/FrankRuhlLibre-Bold.ttf'); font-weight: bold;
}
body {
    direction: rtl; text-align: right;
    font-family: 'FrankRuhlLibre', 'David', 'Times New Roman', serif;
    font-size: 1em; line-height: 1.7; margin: 1em 1.5em;
}
h1 {
    direction: rtl; text-align: right; font-weight: bold;
    font-size: 1.8em; margin-top: 1.5em; margin-bottom: 0.3em;
    page-break-before: always;
    border-bottom: 2px solid #333; padding-bottom: 0.2em;
}
h2 { direction: rtl; text-align: right; font-size: 1.4em; color: #444; }
h3 { direction: rtl; text-align: right; font-size: 1.1em; }
p  { direction: rtl; text-align: right; margin: 0 0 0.8em 0; text-indent: 1.5em; }
p.no-indent { text-indent: 0; }
.chapter-number { font-size: 2em; font-weight: bold; display: block; }
div.figure { text-align: center; margin: 1.5em 0; page-break-inside: avoid; }
div.figure img { max-width: 100%; height: auto; }
p.caption { direction: rtl; text-align: right; font-size: 0.9em; color: #333;
             text-indent: 0; margin: 0.3em 0 1em 0; }
"""

LTR_CSS = """
body { font-family: Georgia, serif; font-size: 1em; line-height: 1.6; margin: 1em 1.5em; }
h1   { font-size: 1.8em; margin-top: 1.5em; page-break-before: always;
       border-bottom: 2px solid #333; padding-bottom: 0.2em; }
h2   { font-size: 1.4em; color: #444; }
p    { margin: 0 0 0.8em 0; text-indent: 1.5em; }
p.no-indent { text-indent: 0; }
.chapter-number { font-size: 2em; font-weight: bold; display: block; }
div.figure { text-align: center; margin: 1.5em 0; page-break-inside: avoid; }
div.figure img { max-width: 100%; height: auto; }
p.caption { font-size: 0.9em; color: #333; text-indent: 0; margin: 0.3em 0 1em 0; }
"""

ACTIVE_CSS = RTL_CSS if IS_RTL else LTR_CSS
DIR_ATTR   = 'rtl' if IS_RTL else 'ltr'

# ── Running headers to strip ───────────────────────────────────────────────────
# Uses \s+ to handle variable spacing (e.g. 'חנוך דאום  |                8').
# Extend with ^\|\s+\d+ for books where odd-page format is '| 12AuthorName' (no space after pipe).
RUNNING_HEADER_RE = re.compile(r'^.+\s+\|\s+\d+$|^\d+\s+\|\s+.+$|^\|\s+\d+')

RUNNING_HEADERS = {
    # Static fallback — add strings that appear alone on a line as page headers
}

# ── Chapter map ────────────────────────────────────────────────────────────────
CHAPTER_STARTS = [
    # (0-indexed start line, number label or '', chapter name, subtitle or '')
]

# ── Helpers ────────────────────────────────────────────────────────────────────

BIDI_RE   = re.compile(r'[\u200f\u200e\u202a\u202b\u202c\u202d\u202e\u200b\u200c\u200d]')
# Strips Hebrew vowel niqqud (U+05B0–U+05BD, etc.) but NOT maqaf ־ (U+05BE) or paseq ׀ (U+05C0)
NIQQUD_RE = re.compile(r' ?[\u05b0-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]')
# Footnote superscript ref: 1-2 digits after a word/quote char, followed by period
FOOTNOTE_RE = re.compile(r'(?<=[^\d\s,.;:\u05be])( ?)(\d{1,2})\.(?!\d)')

def clean(s):
    s = BIDI_RE.sub('', s).replace('\x0c', '').replace('\x04', '')
    s = NIQQUD_RE.sub('', s)
    if re.search(r'[\u0590-\u05FF]', s):
        s = s.translate(str.maketrans('()', ')('))
    return s.strip()

def normalize_ws(s):
    """Collapse runs of whitespace to a single space. Needed because OCR often
    produces 'title  -subtitle' (double space, no space before dash) while the
    ch_name you type is 'title - subtitle'. Without this, skip_exact misses the
    line and it leaks into the first paragraph."""
    return re.sub(r'\s+', ' ', s).strip()

def is_page_number(s):
    # Also matches []N — the bidi-artifact form of [N] page markers
    # (pdftotext extracts '[7]' as '[]7' when bidi marks are stripped)
    return bool(re.match(r'^\d{1,4}$', s) or re.match(r'^\[\]\d{1,4}$', s))

def is_separator(s):
    return s in {'-', '–', '—', '--', '- -', '=', '==', '.', '*', '* * *', '***'}

def has_hebrew(text):
    return bool(re.search(r'[\u0590-\u05FF]', text))

def fix_footnotes(s):
    """Convert inline footnote numbers (pdftotext artifact) to <sup> tags."""
    s = re.sub(r'\(\.(\d{1,2})\)', r'<sup>\1</sup>', s)   # (.N) variant
    s = FOOTNOTE_RE.sub(lambda m: f'{m.group(1)}<sup>{m.group(2)}</sup>.', s)
    return s

def escape_html(text):
    # Escape & only; Hebrew text has no literal < >.
    # Call fix_footnotes() AFTER this so <sup> tags are not escaped.
    return text.replace('&', '&amp;')

# ── Figure extraction (requires PDF_FILE) ─────────────────────────────────────

def build_page_map(pdf_doc):
    """
    Build {book_page_number: pdf_page_index} by reading running headers.
    Handles both 'NN | title' and 'author | NN' formats.
    Also fills gap pages (figure-only pages with no running header).
    """
    HEADER_RE = re.compile(r'^(\d+)\s*\||\|\s*(\d+)\s*$')
    page_map = {}
    for pdf_idx in range(len(pdf_doc)):
        page   = pdf_doc[pdf_idx]
        blocks = page.get_text('blocks')
        if not blocks or blocks[0][1] > 80:
            continue
        m = HEADER_RE.search(clean(blocks[0][4]))
        if m:
            book_pg = int(m.group(1) or m.group(2))
            if book_pg not in page_map:
                page_map[book_pg] = pdf_idx

    # Fill gap pages: book pages N and N+2 mapped to consecutive PDF indices
    # → gap page N+1 maps to pdf_idx N+1
    for p1, p2 in zip(sorted(page_map), sorted(page_map)[1:]):
        if p2 == p1 + 2 and page_map[p2] == page_map[p1] + 2:
            page_map[p1 + 1] = page_map[p1] + 1

    return page_map

def find_figure_page(lines, caption_line, page_map):
    """
    Return the PDF page index for the figure whose caption is at caption_line.
    Looks backward and forward for book page numbers, with gap-page detection.
    Returns None if no mapping can be found.
    """
    PAGE_RE = re.compile(r'^\d{1,4}$')
    PIPE_RE = re.compile(r'\|(\d+)$|^\|\s*(\d+)')

    def scan(start, stop, step):
        for j in range(start, stop, step):
            cl = clean(lines[j])
            if PAGE_RE.match(cl):
                return j, int(cl)
            m = PIPE_RE.search(cl)
            if m:
                return j, int(m.group(1) or m.group(2))
        return None, None

    back_line, back_pg = scan(caption_line, max(0, caption_line - 50), -1)
    fwd_line,  fwd_pg  = scan(caption_line, min(len(lines), caption_line + 60),  1)

    # Gap-page heuristic: caption is on a figure-only page between back_pg and fwd_pg.
    # Only trigger when the forward marker is ≤ 1.5× as far as the backward marker
    # (otherwise the caption is mid-page on back_pg, not on the gap page).
    if (back_pg and fwd_pg and fwd_pg == back_pg + 2
            and back_line is not None and fwd_line is not None):
        if (fwd_line - caption_line) <= (caption_line - back_line) * 1.5:
            book_pg = back_pg + 1
        else:
            book_pg = back_pg
    else:
        book_pg = back_pg

    if book_pg is None:
        return None
    pdf_idx = page_map.get(book_pg)
    if pdf_idx is None:
        print(f'  [figure] caption line {caption_line}: book page {book_pg} not in page_map')
    return pdf_idx

def crop_figure(pdf_page, scale=2.0):
    """
    Render a PDF page at `scale`× and crop to just the figure area.
    Skips the running header (top 70pt) and stops where body text resumes.
    Returns PNG bytes.
    """
    blocks  = pdf_page.get_text('blocks')
    page_h  = pdf_page.rect.height
    y_top   = 70      # skip running header
    y_bottom = page_h  # default: full remaining page

    for b in [b for b in blocks if b[1] > 70]:
        block_h = b[3] - b[1]
        text    = clean(b[4])
        # Body text: tall block with substantial Hebrew content
        if block_h > 30 and len(text) > 60 and has_hebrew(text):
            drawings = pdf_page.get_drawings()
            if drawings:
                rects = [d['rect'] for d in drawings if d['rect']]
                if rects and b[1] > max(r[3] for r in rects):
                    y_bottom = b[1]
                    break
            else:
                y_bottom = b[1]
                break

    clip = fitz.Rect(0, max(0, y_top - 8), pdf_page.rect.width, min(page_h, y_bottom))
    pix  = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    return pix.tobytes('png')

def extract_figures(lines, pdf_doc, page_map):
    """
    Scan the text file for figure captions, render the corresponding PDF pages,
    and return {text_line_index: {'id': 'fig_NNN', 'img_bytes': bytes, 'caption': str}}.
    """
    figures = {}
    counter = 0
    for i, line in enumerate(lines):
        if not CAPTION_RE.match(clean(line)):
            continue
        # Collect multi-line caption
        cap_lines = [clean(line)]
        for k in range(i + 1, min(i + 5, len(lines))):
            cl = clean(lines[k])
            if not cl or is_page_number(cl) or RUNNING_HEADER_RE.match(cl):
                break
            cap_lines.append(cl)
        caption = ' '.join(cap_lines)

        pdf_idx = find_figure_page(lines, i, page_map)
        if pdf_idx is None:
            continue

        counter += 1
        fig_id = f'fig_{counter:03d}'
        img_bytes = crop_figure(pdf_doc[pdf_idx])
        figures[i] = {'id': fig_id, 'img_bytes': img_bytes, 'caption': caption}
        print(f'  [figure] {fig_id}: PDF idx {pdf_idx+1}, caption: {caption[:60]}')

    return figures

# ── Chapter processing ─────────────────────────────────────────────────────────

def build_chapter_html(ch_num, ch_name, ch_sub, blocks):
    """
    blocks: list of str (paragraphs) or dict {'type':'figure','id':..,'caption':..}
    """
    title_esc = escape_html(ch_name)
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE html>',
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{BOOK_LANG}" lang="{BOOK_LANG}" dir="{DIR_ATTR}">',
        f'<head><meta charset="utf-8"/><title>{title_esc}</title>',
        '<link rel="stylesheet" type="text/css" href="Styles/style.css"/>',
        '</head>',
        f'<body dir="{DIR_ATTR}">',
    ]
    if ch_num:
        parts.append(f'<h1><span class="chapter-number">{escape_html(ch_num)}</span>{title_esc}</h1>')
    else:
        parts.append(f'<h1>{title_esc}</h1>')
    if ch_sub:
        parts.append(f'<h2>{escape_html(ch_sub)}</h2>')

    first = True
    for block in blocks:
        if isinstance(block, dict) and block.get('type') == 'figure':
            first = False
            cap = escape_html(block['caption'])
            parts.append(
                f'<div class="figure"><img src="Images/{block["id"]}.png" alt="{cap}"/></div>'
                f'<p class="caption">{cap}</p>'
            )
        else:
            para = str(block).strip()
            if not para:
                continue
            attr = ' class="no-indent"' if first else ''
            # escape & first, then insert <sup> for footnote refs (so tags aren't escaped)
            parts.append(f'<p{attr}>{fix_footnotes(escape_html(para))}</p>')
            first = False

    parts += ['</body>', '</html>']
    return '\n'.join(parts)

def process_chapter(start, end, ch_name, ch_sub, ch_num, all_lines, figures=None):
    """
    Returns a mixed list of str (paragraphs) and dict (figures).
    Pass figures={} or omit when not extracting figures.
    """
    if figures is None:
        figures = {}
    skip_exact = {normalize_ws(x) for x in {ch_num, ch_name, ch_sub, f'פרק {ch_num}'} - {'', 'פרק '}}

    idx = start
    while idx < min(start + 20, end):
        l = normalize_ws(clean(all_lines[idx]))
        if (not l or is_page_number(l) or is_separator(l)
                or l in skip_exact
                or (ch_name and l.startswith(normalize_ws(ch_name)))
                or RUNNING_HEADER_RE.match(l) or l in RUNNING_HEADERS):
            idx += 1
        else:
            break

    current, result = [], []

    def flush():
        if current:
            result.append(' '.join(current))
            current.clear()

    for i in range(idx, end):
        if i in figures:
            flush()
            result.append({'type': 'figure', **figures[i]})
            continue

        s = clean(all_lines[i])

        if is_page_number(s) or RUNNING_HEADER_RE.match(s) or s in RUNNING_HEADERS:
            continue
        if is_separator(s):
            flush(); continue
        if s and not has_hebrew(s) and len(s) < 25 and re.match(r"^[a-zA-Z'\-\.,\s]+$", s):
            if s not in {ch_name, ch_sub}:
                continue
        if not s:
            flush()
        else:
            current.append(s)

    flush()
    result = [b for b in result if not (isinstance(b, str) and re.match(r'^\d{1,4}$', b.strip()))]
    return result or ['(תוכן פרק זה אינו זמין)']

# ── Build EPUB ─────────────────────────────────────────────────────────────────

with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    lines = [l.rstrip('\n') for l in f]

# Figure extraction (skip if no PDF_FILE)
figures = {}
if PDF_FILE:
    print('Building page map...')
    pdf_doc  = fitz.open(PDF_FILE)
    page_map = build_page_map(pdf_doc)
    print(f'  {len(page_map)} pages mapped')
    print('Extracting figures...')
    figures = extract_figures(lines, pdf_doc, page_map)
    print(f'  {len(figures)} figures extracted')

book = epub.EpubBook()
book.set_identifier('book_id_here')
book.set_title('Book Title')
book.set_language(BOOK_LANG)
book.add_author('Author Name')          # call twice for co-authored books
# book.add_author('Second Author')
if IS_RTL:
    book.set_direction('rtl')

# Cover image
cover_page = None
if COVER_IMAGE:
    ext = COVER_IMAGE.rsplit('.', 1)[-1].lower()
    mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else 'image/png'
    cover_fname = f'cover.{ext}'
    with open(COVER_IMAGE, 'rb') as fh:
        cover_data = fh.read()
    # set_cover adds the image item AND creates a cover XHTML page
    book.set_cover(cover_fname, cover_data)
    cover_page = book.get_item_with_id('cover')   # the generated XHTML cover page

# Fonts
if IS_RTL:
    for fname in ('FrankRuhlLibre-Regular.ttf', 'FrankRuhlLibre-Bold.ttf'):
        with open(f'{FONT_DIR}\\{fname}', 'rb') as fh:
            font_data = fh.read()
        book.add_item(epub.EpubItem(uid=f'font_{fname}', file_name=f'Fonts/{fname}',
                                    media_type='application/font-sfnt', content=font_data))

style = epub.EpubItem(uid='style_main', file_name='Styles/style.css',
                      media_type='text/css', content=ACTIVE_CSS)
book.add_item(style)

# Figure images
for fig_info in figures.values():
    book.add_item(epub.EpubItem(
        uid=f'img_{fig_info["id"]}',
        file_name=f'Images/{fig_info["id"]}.png',
        media_type='image/png',
        content=fig_info['img_bytes'],
    ))

epub_chapters, toc_items = [], []

for i, (start, ch_num, ch_name, ch_sub) in enumerate(CHAPTER_STARTS):
    end      = CHAPTER_STARTS[i+1][0] if i+1 < len(CHAPTER_STARTS) else len(lines)
    blocks   = process_chapter(start, end, ch_name, ch_sub, ch_num, lines, figures)
    html_str = build_chapter_html(ch_num, ch_name, ch_sub, blocks)
    n_paras  = sum(1 for b in blocks if isinstance(b, str))
    n_figs   = sum(1 for b in blocks if isinstance(b, dict) and b.get('type') == 'figure')
    n_tables = sum(1 for b in blocks if isinstance(b, dict) and b.get('type') == 'table')
    print(f'  {ch_name}: {n_paras} paras'
          + (f', {n_figs} img' + ('s' if n_figs != 1 else '') if n_figs else '')
          + (f', {n_tables} table' + ('s' if n_tables != 1 else '') if n_tables else ''))

    ch = epub.EpubHtml(title=ch_name, file_name=f'chapter_{i:02d}.xhtml',
                       lang=BOOK_LANG, direction=DIR_ATTR)
    # CRITICAL: set content as bytes, not str — see Debugging Tips
    ch.content = html_str.encode('utf-8')
    ch.add_item(style)
    book.add_item(ch)
    epub_chapters.append(ch)
    toc_items.append(epub.Link(f'chapter_{i:02d}.xhtml',
                               f'{ch_num}. {ch_name}' if ch_num else ch_name,
                               f'chap_{i:02d}'))

book.toc   = toc_items
spine_cover = [cover_page] if cover_page else []
book.spine = spine_cover + ['nav'] + epub_chapters
book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())

# CRITICAL: patch get_pages to handle items whose body cannot be parsed
_orig_get_pages = epub_utils.get_pages
def _safe_get_pages(item):
    body = item.get_body_content()
    if not body or not body.strip():
        return []
    return _orig_get_pages(item)
epub_utils.get_pages = _safe_get_pages

epub.write_epub(OUTPUT_FILE, book)
# OUTPUT: leave the file at OUTPUT_FILE (c:\github\). Do NOT copy it elsewhere — the user copies it manually.

# ── Final report ──────────────────────────────────────────────────────────────
total_paras = total_figs = total_tables = 0
print(f'\n{"Chapter":<45} {"Paras":>6} {"Imgs":>5} {"Tables":>7}')
print('-' * 67)
for i, (start, ch_num, ch_name, ch_sub) in enumerate(CHAPTER_STARTS):
    end    = CHAPTER_STARTS[i+1][0] if i+1 < len(CHAPTER_STARTS) else len(lines)
    blocks = process_chapter(start, end, ch_name, ch_sub, ch_num, lines, figures)
    np_ = sum(1 for b in blocks if isinstance(b, str))
    nf  = sum(1 for b in blocks if isinstance(b, dict) and b.get('type') == 'figure')
    nt  = sum(1 for b in blocks if isinstance(b, dict) and b.get('type') == 'table')
    total_paras  += np_
    total_figs   += nf
    total_tables += nt
    extras = (f'  {nf} img' if nf else '') + (f'  {nt} table' + ('s' if nt != 1 else '') if nt else '')
    print(f'  {ch_name[:43]:<43} {np_:>6} {nf:>5} {nt:>7}')
print('-' * 67)
print(f'  {"TOTAL":<43} {total_paras:>6} {total_figs:>5} {total_tables:>7}')
print(f'\nDone: {OUTPUT_FILE}')
```

---

## Debugging Tips (hard-won)

### 0-byte chapter files — the #1 gotcha

**Symptom:** EPUB is generated without error but all `.xhtml` files are 0 bytes.

**Root cause:** `EpubHtml.get_content()` in ebooklib calls
`parse_html_string(self.content)` which uses lxml's HTML parser with
`encoding='utf-8'`. That parser **expects `bytes`**, not a Python `str`.
When given a `str`, lxml throws internally, `get_content()` silently catches
it and returns `b""`, so the zip entry is written as empty.

**Fix:** Always encode content before assigning:
```python
ch.content = html_str.encode('utf-8')   # bytes, not str
```

### ParserError: Document is empty

**Symptom:** `epub.write_epub()` raises `lxml.etree.ParserError: Document is empty`
inside `_get_nav → get_pages_for_items → get_pages → parse_html_string(b"")`.

**Root cause:** Same as above — one item's body is `b""`, and `parse_html_string`
chokes on empty bytes.

**Fix:** Patch `epub_utils.get_pages` to skip empty-body items (see script above),
**and** fix the root cause (encode content as bytes).

### Windows encoding errors (`cp1255`, `cp1252`)

**Symptom:** `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9f` when
reading the `.py` file or the input `.txt`.

**Fix:** Always run with `-X utf8`:
```bash
python3 -X utf8 make_epub.py
```
This sets `PYTHONUTF8=1` for the whole process, overriding the Windows ANSI
code-page default for all file I/O.

### Chapter title bleeding into first paragraph

**Symptom:** The chapter title appears as the first `<p>` in the chapter body instead of being stripped.

**Root cause:** The `skip_exact` check uses exact string equality, but OCR spacing often differs from the `ch_name` you set. For example, OCR produces `"הקדמה  -שיחה..."` (double space, no space before dash) while `ch_name` is `"הקדמה - שיחה..."` — the strings look the same on screen but `in` returns `False`.

**Fix:** The script template now includes `normalize_ws()` which collapses all whitespace runs to a single space before comparing. If you copied an older template, add it manually:

```python
def normalize_ws(s):
    return re.sub(r'\s+', ' ', s).strip()

# In process_chapter, build skip_exact with normalization:
skip_exact = {normalize_ws(x) for x in {ch_num, ch_name, ch_sub} if x}
# And compare with:
if normalize_ws(s) in skip_exact: ...
```

### Verifying content without a reader

```python
import zipfile, re
z = zipfile.ZipFile('output.epub')
for name in z.namelist():
    print(f"{name}: {z.getinfo(name).file_size} bytes")

ch = z.read('EPUB/chapter_01.xhtml').decode('utf-8')
words = re.findall(r'[\u0590-\u05FF]+', ch)   # Hebrew
# words = re.findall(r'[A-Za-z]+', ch)         # Latin
print(f'{len(words)} words, sample: {words[:5]}')
```

All chapter files should be several KB at minimum. A 0-byte file means the
content encoding bug above is present.

### Identifying running headers

Running headers are lines that appear **alone** every ~20–40 lines throughout
the body (author name, chapter name used as a page header, book title).

**Check for the pipe pattern first** — OCR'd Hebrew books often use `44 | הפצצה` (even pages) and `מועדון האורניום | 45` (odd pages). Confirm with:
```bash
grep -nP '^\d+ \| .+$|^.+ \| \d+$' input.txt | head -20
```
If consistent, `RUNNING_HEADER_RE` in the script template handles all of them automatically — no manual enumeration needed.

**For other patterns**, grep for a suspected string:
```bash
grep -n "^SomeSuspectedHeader$" input.txt | head -20
```
If the same string appears 20+ times across the file, it's a running header —
add it to `RUNNING_HEADERS`.

**Blank page markers.** Some publishers' OCR emits annotations for intentionally blank pages: `עמ' 14 ריק` (Hebrew) or `עמ' 8 ריק`. Strip with:
```python
BLANK_PAGE_RE = re.compile(r"^עמ'[ \u00a0]+\d+ ?ריק$")
```
Add a check `if BLANK_PAGE_RE.match(s): continue` in the body loop.

**`zzz` section separator.** Some books use `zzz` (or `* * *`) as a typographic section break between sub-sections within a chapter. These appear as standalone lines and should be stripped. Add `'zzz'` to the `is_separator` check.

### Finding chapter start lines

```bash
# Standalone single digits (chapter numbers 1-9)
grep -n "^[0-9]$" input.txt

# Verify context around a candidate line N (0-indexed → use N+1 in grep):
# Read lines N-3 to N+8 in the file to confirm chapter title follows
```

Beware: standalone `1` also appears as a page number or footnote marker.
Always verify in context.

### OCR-merged chapter headings

OCR sometimes fuses the chapter label and name into a single token, or corrupts punctuation within it. Common examples:

| Expected | OCR output |
|---|---|
| `פרק רביעי` | `פרקירהביצי` |
| `פרק תשיעי` | `פבקיתשיעי` |
| `פרק עשרים ושניים` | `פרק עשרים.ושניים` (dot instead of space) |

**If `find_chapter_page('פרק X')` returns nothing**, grep for a short unique fragment of the chapter name (e.g. `רביעי`, `תשיעי`) and inspect the page. Then add fallback patterns to the search:

```python
# Provide multiple patterns; try each until one matches
patterns = ['פרק רביעי', 'פרקירהביצי', 'פרקיר']
found = None
for pat in patterns:
    found = find_chapter_page(pat, start_after=last_found)
    if found:
        break
```

The display name in the EPUB should always be the canonical form (`פרק רביעי`), regardless of which OCR variant was matched.

---

## Font Resources

### Frank Ruhl Libre (Hebrew serif — recommended for all Hebrew books)

**What it is:** A high-quality open-source Hebrew serif font, the standard choice for Israeli book publishing. Much better than the Windows built-in `David` or `Times New Roman` fallbacks.

**Where the files live:** TTF files are stored in the user's `.claude` folder:
```
C:\Users\User\.claude\fonts\
    FrankRuhlLibre-Regular.ttf
    FrankRuhlLibre-Bold.ttf
    FrankRuhlLibre-Medium.ttf
    FrankRuhlLibre-SemiBold.ttf
    FrankRuhlLibre-Light.ttf
    FrankRuhlLibre-ExtraBold.ttf
    FrankRuhlLibre-Black.ttf
```
The original zip (also containing Heebo) is at `h:\My Drive\misc\Frank_Ruhl_Libre,Heebo.zip`.

**Usage:** The script template already includes the `FONT_DIR`, `@font-face` CSS, and embedding code — just set `FONT_DIR` and leave `IS_RTL = True`. Only Regular and Bold are embedded by default to keep file size down.

**Reader support:** Apple Books, Kobo, Calibre, and most desktop EPUB readers honour embedded fonts. Kindle ignores them and uses its own Hebrew rendering.
