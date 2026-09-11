---
name: pdf-to-epub
description: Convert a PDF book into a proper reflowable EPUB, OR fix an existing EPUB that scrolls/pages the wrong way. Use this whenever the user asks to convert a PDF to EPUB, turn a PDF into an ebook/e-reader format, make a PDF "readable" on Kindle/Apple Books/Kobo, extract a book's text+images into a clean digital-book format, or reports that an EPUB "scrolls sideways", "scrolls down instead of paging", "won't turn pages", or asks to "change the scroll direction" / "make it scroll horizontally or vertically" for an .epub file — including Hebrew, Arabic, or other right-to-left (RTL) language books. Trigger even if the user just says "make this PDF into an epub" or "convert this book" with a PDF attached, or hands you a .epub file with a one-line complaint about how it scrolls, without using the word "EPUB" or "RTL" themselves.
---

# PDF → EPUB conversion, and fixing existing EPUBs

This skill covers two different jobs that share the same underlying RTL know-how:

1. **Building a new EPUB from a PDF** — see "Workflow overview" below. Converting a PDF book into a good EPUB is NOT just "wrap the PDF text in HTML." A PDF has no real paragraph/chapter structure — it only has positioned text fragments and images per page. You have to reconstruct structure (paragraphs, headings, chapter breaks, image placement) from layout clues, then hand-build a spec-correct EPUB package.
2. **Fixing an already-existing EPUB that scrolls or pages the wrong way** — see "Fixing an existing EPUB's scroll/paging direction" below. This has turned out to be the more common real request: someone hands you a finished, often professionally-produced (Calibre- or InDesign-exported) .epub and it scrolls when it should page, or won't page at all. Jump straight there — you don't need to touch the PDF-conversion workflow at all for this.

Treat every PDF/EPUB as different — font sizes, margins, and heading conventions vary per book, and so does which of the fixes below a given file is already missing. The numeric thresholds and code below are starting points to calibrate against the actual file you're given, not universal constants.

## Workflow overview

1. **Inspect the PDF first.** Open it with `pypdf`/`PyMuPDF` (`fitz`) and check: page count, whether text extracts cleanly (real text layer) or is garbled/empty (scanned — needs OCR, see the `pdf` skill's OCR guidance), and whether each page has an embedded raster image (could be real photos, or could be a decorative/DRM background — see step 3).

2. **Reconstruct real paragraphs and headings from position + font size**, not raw `page.get_text()` output — naive text extraction often breaks one printed line into several fragments (especially in RTL PDFs where each word can be its own internal "line" object). Use `scripts/pdf_lines.py`'s `get_visual_lines()`: it clusters text fragments into true visual print-lines by y-position, and for RTL text sorts fragments right-to-left before joining. Each returned line carries `x0`, `x1`, `size`, and `text` — from these you can derive:
   - **Chapter/major headings**: usually the biggest font-size jump on the page, sitting near the top (small `y0`). Font size alone can false-positive on pull-quotes/sidebars elsewhere on a page — require *both* large size *and* near-top position, or cross-check against extracted heading candidates from the table-of-contents page(s) if the book has one.
   - **Paragraph breaks**: in a right-aligned RTL layout, look for a line whose `x1` (right edge) sits noticeably left of the page's normal right margin — that's a first-line right-indent, meaning a new paragraph starts there. (Mirror this logic — watch `x0` instead — for LTR books.) A short last line followed by a normal-margin line is just paragraph-end + next-paragraph-start; don't confuse it with a heading.
   - **Subsection headings that use body-sized font**: some books style sub-headings the same size as body text, distinguishable only by being a short, standalone, margin-hugging line not ending in sentence punctuation, followed by a non-indented line. If the book has a table of contents, fuzzy-match short candidate lines against the ToC's title list (allow for OCR/font-glyph noise — see below) rather than trusting text equality.
   - **Font-glyph extraction glitches**: some PDFs (especially ones with subsetted/custom fonts) mis-map specific glyphs in headings — e.g. one Hebrew ו consistently extracting as ר only when used as a standalone list-ordinal glyph, elsewhere fine. If a heading looks wrong compared to its ToC entry, prefer the ToC's version, and don't assume the whole book's text layer is corrupted just because of an isolated glyph bug.

3. **Extract embedded photos/diagrams, not whole-page background rasters.** Many PDFs embed one full-page-sized raster per page that's mostly blank/decorative (or, for "protected"/watermarked PDFs, a deliberately blurred duplicate of the page's own text, layered under sharp vector text as a copy-protection trick). Don't ship that whole raster as a "photo" — crop out just the real image content:
   - Compute a `nonwhite`/edge-density fraction per page raster first; skip pages near zero (nothing but faint noise).
   - For candidate pages, use `scripts/extract_images.py`'s connected-component approach (edge-magnitude + darkness mask, dilated, filtered by component size AND by *fill density within its bounding box* — the density filter is what separates real photos/diagrams from sparse decorative text or index-page listings that would otherwise false-positive).
   - Watch for pages with a flat, non-white/non-black *design-color* background (e.g. a tinted "about the author" page) — a plain darkness threshold will scoop up the entire colored background as one giant "photo." Prefer the edge/texture-based mask over raw darkness for these.
   - Place each cropped image at the point in the text flow whose y-position brackets the image's y-position on the source page — i.e., between the paragraph before it and the paragraph after it, so photos land next to the text that referenced them.

4. **Build the EPUB package** — mimetype (stored, not deflated), `META-INF/container.xml`, `content.opf`, `nav.xhtml` + `toc.ncx`, one XHTML file per chapter (so each chapter starts on its own page in every reader), a shared CSS file, and the images. See `scripts/build_epub.py` for a working packager; the header/CSS boilerplate it emits already encodes the RTL correctness rules below — reuse it rather than re-deriving them.

5. **Validate with `epubcheck`** (`pip install epubcheck`, needs Java) before calling it done:
   ```python
   from epubcheck import EpubCheck
   result = EpubCheck('book.epub')
   print(result.valid, result.messages)
   ```
   On Windows, if the filename has non-ASCII characters, copy to an ASCII-named temp file before running epubcheck — otherwise the Java subprocess call mangles the path and you'll get a confusing false failure. One exception to "fix every error": see the CSS `direction` note below — that specific error is fine to leave.

## RTL (Hebrew/Arabic) books: critical scrolling-direction rules

**This is the part that's easy to get wrong and hard to debug** — a book can look perfect on screen and still behave wrong in real reader apps: paging *sideways* when it should scroll down, or scrolling down when it should page. First figure out which one the user actually wants — **most real requests turn out to be "make this book page properly" (horizontal, right-to-left, like flipping a physical Hebrew book), not "make it scroll."** Continuous vertical scroll is the unusual case (mainly requested for one specific from-scratch-built EPUB in the history behind this skill); page-turning is the normal way people read ebooks and is what most professionally-produced Hebrew EPUBs are supposed to do already, just sometimes missing a piece.

These rules were confirmed by diffing broken and working EPUBs against each other, both directions, across several real books:

**Shared foundation — always correct regardless of which direction you want:**
- **Do** set `dir="rtl"` on both `<html>` *and* `<body>` in every XHTML file — not just one of them. Real books in the wild are frequently missing it on `<body>` specifically even when `<html>` has it.
- **Do** include a `<!DOCTYPE>` right after the XML prolog in every XHTML file. **Match it to the book's actual EPUB version** — check `<package version="...">` in `content.opf`: `version="3.0"` (EPUB3) wants the plain `<!DOCTYPE html>`; `version="2.0"` (EPUB2, common in older Calibre-produced files) wants the full XHTML 1.1 public DOCTYPE. Using the wrong one for the book's declared version can itself introduce a new epubcheck error where there was none before.
- **Do** put the CSS `direction: rtl;` property explicitly on `body` (it's an inherited property, so this cascades to every descendant without having to guess the book's paragraph class names) — **even though EPUBCheck's `CSS-001` rule flags `direction` in a stylesheet as an error.** In practice, real readers use it for layout/pagination decisions in ways that `text-align: right` alone doesn't cover. Multiple known-good, widely-read RTL EPUBs used as references for this rule have the same "error" and read fine — validator-cleanliness loses to real-world reader compatibility here.
- **Don't** reach for EPUB3 `rendition:flow`/`rendition:layout`/`rendition:spread` metadata hoping to force either mode. Many real reader apps ignore these hints entirely; they're not a fix for anything and add risk for no benefit.
- **Don't** fight a reader's own rendering mode with CSS (`overflow-x: hidden`, forcing `column-count: 1`, etc.) no matter which direction you're after. Reader apps implement their own pagination/scroll mechanism around your content; CSS overrides like this can clip content with *no* scroll in either direction, which is worse than the original complaint.

**The one thing that actually switches page-turning vs. scrolling:**
- `page-progression-direction="rtl"` on `<spine>` in content.opf. **Present** → the book pages horizontally, right-to-left (the normal ebook reading mode — this is very likely what's wanted). **Absent** → the book scrolls continuously. Add or remove this one attribute to switch between them; don't touch anything else to try to force it, and don't assume "RTL book" automatically means this should be present — check what behavior is actually wanted first, because the attribute name is misleading (it sounds like it just means "the text is RTL," but it specifically means "paginate right-to-left").

If a user reports the wrong behavior persisting after all of the above and epubcheck is otherwise clean (or only has the expected `CSS-001` warning), ask which specific app/device they're reading in — a few apps (e.g. Kindle's own reader) ignore all EPUB-level hints and always follow their own app-level paged/scroll setting, which only the user can toggle on their end.

## Fixing an existing EPUB's scroll/paging direction

This is a separate, smaller job from building a new EPUB, and in practice the more common request. Someone hands you a finished `.epub` — often a real published book exported from Adobe InDesign (look for `idGeneratedStyles.css` and filenames like `_BookName_to_epub-12.xhtml`) or converted years ago with Calibre — and it scrolls or paginates the wrong way.

1. **Back up the original file first** (a plain copy next to it, or in your scratch directory) — you'll very likely be told to overwrite the file in place.
2. **Diagnose before fixing.** Unzip it (it's a zip) and check: `<package version="...">` in `content.opf` (decides which DOCTYPE to use), whether `<spine>` already has `page-progression-direction="rtl"` (compare to what the user actually wants — see above), whether a sample `.xhtml` file's `<html>`/`<body>` tags already have `dir="rtl"`, and whether the CSS already has a `direction` declaration. Real books are inconsistent about which of these they're already missing — one file had everything but the spine attribute, another had the spine attribute and `<html>` but nothing else. Don't assume; check.
3. **Apply `scripts/fix_rtl_epub.py`.** It implements the whole shared-foundation checklist above (idempotently — safe to run even if some pieces are already correct) plus the one spine-attribute switch, and as a free bonus fixes two common unrelated packaging defects in old exports while it's already rewriting the zip: `mimetype` not being the first/uncompressed entry, and files stored fully uncompressed (bloats file size for no reason — expect the fixed file to be noticeably *smaller*, which is normal and not a sign anything was lost). Read its module docstring for exact usage — in particular, don't pass Hebrew/non-ASCII paths as shell CLI arguments (they can get mangled); call `fix_epub()` directly from a small driver script instead.
4. **Validate with epubcheck** and compare the message count/content against a check of the *original* backup — a few pre-existing errors (e.g. EPUB3-only attributes used in a book that declares EPUB2, or stray `role` attributes) are normal for real-world files and not something you introduced; what matters is you haven't added *new* ones beyond the expected `CSS-001` direction warning.

## Chapter/heading → XHTML mapping

Give every chapter its own XHTML file (e.g. `ch01.xhtml`, `ch02.xhtml`) and list them in the spine in reading order — this, not any CSS page-break trick, is what reliably makes every reader start a new chapter on a fresh page/screen. Use `h1` for the chapter title and `h2` for sub-headings within it; add a CSS `page-break-before: always` on `h1` too as a (mostly redundant but harmless) belt-and-suspenders for print/paginated renderers.

## Reference

- `scripts/pdf_lines.py` — `get_visual_lines(page)`: reconstructs true print-lines (with x0/x1/size) from a PyMuPDF page, handling the "each word is its own internal line" quirk common in RTL PDFs.
- `scripts/extract_images.py` — crops real photo/diagram content out of per-page raster images, filtering out decorative/blank/DRM-blur backgrounds.
- `scripts/build_epub.py` — packages a directory of XHTML/CSS/images into a validated, correctly-RTL EPUB (mimetype, container.xml, content.opf, nav.xhtml, toc.ncx, zip). Read its `--help` / top-of-file docstring for the expected input layout, then adapt the manifest/spine-building loop to the specific book's chapter list.
- `scripts/fix_rtl_epub.py` — fixes an *existing* EPUB's scroll/paging direction and DOCTYPE/dir/CSS gaps in place (see "Fixing an existing EPUB's scroll/paging direction" above). Idempotent per-fix, so safe to run even when a book only needs one or two of the pieces.
- `references/rtl-epub-notes.md` — the fuller writeup of the RTL scrolling investigation, including the vertical-scroll case this was originally debugged from, if you want the "why" in more depth than the summary here.
