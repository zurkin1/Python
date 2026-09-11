---
name: txt-to-md
description: Convert a markdown book specifically (not PDF/OCR/DOCX — use txt-to-epub for those) into a clean EPUB with correct chapter structure, metadata, images, and optional RTL support. Use when the input is already a well-formed .md file.
---

# txt-to-md

Convert a Markdown book into a clean EPUB with correct chapter structure, metadata, images, and optional RTL support.

## Scope

Use this skill **only** when the input is a `.md` file. Ignore PDF, OCR, `pdftotext`, `rawdict`, page-order checks, and DOCX workflows.

Parse arguments as:

`<input.md> [output.epub] [--lang he|en] [--rtl]`

- First positional arg: input markdown path, required.
- Second positional arg: output epub path, optional.
- `--lang`: default `he`.
- `--rtl`: default `true` when language is Hebrew, otherwise `false` unless explicitly requested.
- Always leave the final EPUB exactly at the requested output path.

If no input path was provided, ask for it before proceeding.

## Workflow

### 1. Fast triage

Do these checks first and keep them minimal:

1. Read only the first ~120 lines.
2. Search once for heading markers (`^#`, `^##`, `^###`, `^####`).
3. Search once for markdown image syntax or base64 reference-image definitions.

Do **not** read large body sections unless structure is still unclear.

Goal of triage:
- infer title/author/front matter pattern,
- infer heading hierarchy,
- detect whether images exist,
- detect whether separators like `---` or `* * *` are structurally meaningful.

### 2. Prefer one generic parser

Use one generic markdown parser with small book-specific constants only when needed.

Default assumptions:
- `###` starts a main EPUB chapter.
- `####` can mean subtitle, standalone front/back-matter chapter, or in-chapter subsection.
- blank lines end paragraphs.
- `---` may mark a boundary before a new standalone `####` chapter.
- `* * *` is a separator, not a chapter boundary.

Do not create a whole new script unless the markdown structure genuinely breaks the generic parser.

### 3. Extract embedded images and Recovery (Enhanced)

Before parsing chapter text, extract base64 reference-style images and remove their definition lines from the text.
**Image Recovery Logic:** 
Ensure the parser specifically looks for both standard markdown images and reference tags (e.g., `![caption][ref_id]`). Even if a path is missing in the local definitions, dynamically inject the image into the flow if the reference ID exists in the extracted image map.

Pattern to support:

```text
[ch1_img_1]: data:image/jpeg;base64,/9j/4AAQ...
```

Use this pattern:

```python
import re, base64

IMAGE_DEF_RE = re.compile(
    r'^\[([^\]]+)\]:\s*data:image/([^;]+);base64,([^\s]+)',
    re.MULTILINE,
)

def extract_images(text):
    images = {}
    for m in IMAGE_DEF_RE.finditer(text):
        ref = m.group(1)
        mime_subtype = m.group(2).lower()
        b64 = m.group(3)
        ext = 'jpg' if mime_subtype in ('jpeg', 'jpg') else mime_subtype
        images[ref] = {
            'bytes': base64.b64decode(b64),
            'ext': ext,
            'mime': f'image/{mime_subtype}',
        }
    text = IMAGE_DEF_RE.sub('', text)
    return text, images
```

Do not inspect raw base64 lines manually.

### 4. Chapter parsing rules

Use a single pass over lines with these states:
- `current_chapter`
- `current_paragraph_lines`
- `after_separator`

Recommended behavior:

```python
after_separator = False

for i, line in enumerate(lines):
    s = line.strip()

    if s.startswith('### '):
        save_chapter()
        title = s[4:].strip()
        subtitle = maybe_peek_subtitle(lines, i)
        current_chapter = {'title': title, 'subtitle': subtitle, 'blocks': []}
        after_separator = False

    elif s.startswith('#### '):
        text = s[5:].strip()
        if current_chapter is None or after_separator:
            save_chapter()
            current_chapter = {'title': text, 'subtitle': '', 'blocks': []}
        else:
            flush_paragraph()
            current_chapter['blocks'].append({'type': 'section', 'text': text})
        after_separator = False

    elif s == '---':
        flush_paragraph()
        after_separator = True

    elif s == '* * *':
        flush_paragraph()
        ensure_chapter()
        current_chapter['blocks'].append({'type': 'separator'})

    elif not s:
        flush_paragraph()

    else:
        after_separator = False
        ensure_chapter()
        current_paragraph_lines.append(s)
```

### 5. Subtitle detection

A `####` immediately following a `###` is often a subtitle, not a subsection.

Use a short look-ahead only, for example 1-2 non-empty lines. Consume that subtitle during `###` handling so the main loop does not emit it again.

```python
def maybe_peek_subtitle(lines, i):
    j = i + 1
    seen_nonempty = 0
    while j < len(lines) and seen_nonempty < 2:
        s = lines[j].strip()
        if not s:
            j += 1
            continue
        seen_nonempty += 1
        if s.startswith('#### '):
            return s[5:].strip()
        break
    return ''
```

If you consume the subtitle, skip that line in the main loop.

### 6. Section headings and footnotes

Support these common cases:

#### Section-number headings

Lines like `1.1  Some title` or `2.3.1  Some title` with at least two spaces after the number are section headings.

```python
SECTION_NUM_RE = re.compile(r'^\d+\.\d+(?:\.\d+)?\s{2,}(.+)')
```

Emit them as section blocks, not body paragraphs.

#### Footnote blocks

Support standalone markdown footnotes like these:
- `[* text]`
- `[1. text]`

```python
FOOTNOTE_RE = re.compile(r'^\[\*\.?\s*(.+)\]$|^\[\d+\.\s*(.+)\]$')
```

Emit them as `footnote` blocks and style them separately.

### 7. Image references in body

Support both inline markdown images and reference-style body placeholders when they map to extracted images.

Typical cases:
- `![caption](path)`
- `![caption][ch1_img_1]`
- a parser-specific placeholder already normalized to an image ref

When an image ref matches an extracted base64 image:
- add image bytes to EPUB manifest,
- emit a figure block in the chapter,
- use the alt text as caption when useful.

If the first extracted image clearly appears before chapter content and is named like `cover`, `cover_img`, or similar, prefer it as the EPUB cover.

## Generic data model

Use a small internal block model:

```python
{'type': 'paragraph', 'text': '...'}
{'type': 'section', 'text': '...'}
{'type': 'footnote', 'text': '...'}
{'type': 'separator'}
{'type': 'figure', 'ref': 'ch1_img_1', 'caption': '...'}
```

This keeps parsing separate from HTML rendering.

## HTML rendering

Each EPUB chapter should render as valid XHTML.

Recommended mapping:
- chapter title -> `<h1>`
- chapter subtitle -> `<h2>`
- section block -> `<h3>`
- paragraph block -> `<p>`
- first paragraph after heading -> `<p class="no-indent">`
- footnote block -> `<p class="footnote">`
- separator block -> `<p class="separator">* * *</p>`
- figure block -> `<div class="figure"><img src="images/ref.ext" .../></div>` and optional caption — use a path **relative to the chapter file** (e.g. `images/ref.ext`, never `../images/ref.ext`, since chapters and images share the same EPUB directory)

Always HTML-escape text.

## EPUB assembly

Use one shared EPUB builder pattern:
- create `epub.EpubBook()`
- set identifier, title, language, author, and direction if RTL,
- add CSS once,
- add fonts only if actually needed,
- add image items once,
- add chapter XHTML items,
- build TOC and spine,
- add `EpubNcx` and `EpubNav`,
- write the `.epub`.

Do not duplicate assembly logic per book.

**Critical:** When creating `EpubHtml` items, **never** pass `content=` to the constructor — ebooklib silently ignores it, producing 0-byte pages. Always set content after construction as bytes:

```python
item = epub.EpubHtml(title=chap['title'], file_name=fname, lang=LANG)
item.content = xhtml.encode('utf-8')  # must be bytes, set after construction
```

Patch `ebooklib.utils.get_pages` only if the run actually hits the known empty-body parser issue.

## Minimal CSS baseline

Use one compact stylesheet. Include only what matters:

```css
body { direction: rtl; text-align: right; font-family: serif; line-height: 1.7; margin: 1em 1.5em; }
h1 { font-size: 1.8em; margin: 1.5em 0 0.3em; page-break-before: always; }
h2 { font-size: 1.25em; margin: 0.2em 0 1.2em; }
h3 { font-size: 1.1em; margin: 1.4em 0 0.4em; }
p { margin: 0 0 0.8em 0; text-indent: 1.5em; }
p.no-indent, p.separator, p.footnote { text-indent: 0; }
p.separator { text-align: center; margin: 1em 0; }
p.footnote { font-size: 0.85em; color: #555; border-right: 3px solid #ccc; padding-right: 0.8em; }
div.figure { text-align: center; margin: 1.5em 0; page-break-inside: avoid; }
div.figure img { max-width: 100%; height: auto; }
p.caption { text-indent: 0; font-size: 0.9em; color: #333; margin: 0.3em 0 1em; }
```

Switch to LTR only when requested or when the language is non-Hebrew.

## Token-saving rules for the agent

- Do not read whole chapters during exploration.
- Do not inspect base64 payloads manually.
- Do not generate a new script when config or a tiny regex tweak is enough.
- Do not duplicate CSS, EPUB assembly, or escaping helpers across books.
- Do not add Markdown-only edge cases unless the current file actually needs them.
- Prefer one generic script plus a tiny per-book config section.
- Keep debug output short: counts, chosen parser mode, detected chapters, detected images.

## When a tiny override is allowed

Only add a small book-specific override when one of these is true:
- the main chapter marker is not `###`,
- `####` has a different semantic role throughout the file,
- section-number lines use a different pattern,
- image placeholders use a different reference syntax,
- front/back matter uses a unique separator pattern.

In those cases, change constants or regexes first. Do not fork the whole workflow.

## Deliverable standard

The final solution should normally be:
1. one generic markdown-to-epub script,
2. zero or one tiny config block for the current book,
3. the generated `.epub` at the requested output path.

Do not create separate full scripts for each new markdown book unless the structure is truly incompatible with the generic parser.
