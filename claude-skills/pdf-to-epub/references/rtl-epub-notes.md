# RTL EPUB scrolling: the investigation, in order

This is the story of how a Hebrew EPUB ended up scrolling/paging sideways, and what actually fixed it — kept here so the next attempt doesn't retrace the same dead ends.

## Symptom

A converted Hebrew (RTL) PDF-to-EPUB looked correct on screen (right-aligned text, correct paragraph indents, images in place) but in the user's reader app, a chapter with many paragraphs paged *sideways* instead of scrolling down.

## Dead end 1: EPUB3 rendition hints

First attempt: add `<meta property="rendition:flow">scrolled-doc</meta>` (plus `rendition:layout`/`rendition:spread`) to `content.opf`, and `properties="rendition:flow-scrolled-doc"` on each spine `<itemref>`. This is the "correct," spec-sanctioned way to hint at scroll-vs-paginated rendering.

Result: no change. The user's reader app doesn't honor the hint.

## Dead end 2 (made it worse): CSS overflow/column overrides

Second attempt: add `overflow-x: hidden` and force `column-count: 1; column-width: auto;` on `html, body` in the stylesheet, reasoning that the reader might be using CSS columns internally for pagination and this would neutralize it.

Result: the user reported pages now didn't scroll *at all*, in either direction — content was cut off. Likely explanation: the reader app's own pagination mechanism wraps rendered content in a container it controls (often with its own `overflow` and column CSS applied around/over the book's content for its page-flip UI). Forcing `column-count: 1` from inside the content stylesheet doesn't disable that outer mechanism — it just breaks whatever internal column-based page-splitting the reader was doing, while the reader's own `overflow: hidden` (not ours) still clips anything taller than one "page." Net effect: broken pagination *and* no scrolling.

Lesson: don't try to out-fight a reader app's own rendering mode from inside the content CSS. Removing the override (reverting to plain CSS with no `overflow`/`column` rules at all) fixed the "nothing scrolls" regression immediately.

## The actual fix: diff against a known-working reference book

The breakthrough came from the user supplying a Hebrew EPUB they already knew scrolled correctly in the same reader app, so it could be diffed structurally against the broken one. Concrete differences found:

1. **`page-progression-direction="rtl"` on `<spine>`.** The broken book had it (seemed "obviously correct" for an RTL book — it's literally in the name). The working reference book didn't have it at all. This attribute tells the reading system "this is a right-to-left *paginated* book" (think manga/comics reading order) — for RTL prose meant to scroll, it's the wrong signal and was the single biggest cause of the sideways behavior. **Removing it** (i.e. `<spine toc="ncx">` with no page-progression-direction) was the main fix.

2. **Missing `<!DOCTYPE html>`.** The working reference had `<!DOCTYPE html>` right after the `<?xml ...?>` prolog in every XHTML file. The broken book had no doctype at all. Added it everywhere.

3. **`dir="rtl"` only on `<html>`, not `<body>`.** The working reference set `dir="rtl"` on both. Added it to `<body>` too.

4. **CSS `direction: rtl` was missing.** It had been deliberately removed earlier in the process because EPUBCheck's `CSS-001` rule flags the `direction` property in a stylesheet as an error ("must not be included in an EPUB Style Sheet"). The working reference book has `direction: rtl` all over its CSS (`body`, `h1`, `h2`, `p`) and is *not* EPUBCheck-clean either — but it's a real, working, widely-read book in the target reader app. Re-added `direction: rtl` to the equivalent selectors. `text-align: right` plus a `dir` attribute is evidently not fully equivalent to CSS `direction` for how some reader engines decide layout/pagination axis.

After applying items 1–4 together (not fully isolated one at a time, so it's possible not all four were strictly necessary — but this combination is now the confirmed-working baseline), the user confirmed: "now it works!"

## Follow-up: the more common case is the opposite direction

After the above, several more requests came in of the form "make this EPUB scroll horizontally" — i.e. the opposite of the original symptom. These were all existing, often professionally-produced books (Calibre-exported, or Adobe InDesign-exported with `idGeneratedStyles.css`), not something built from scratch, and it turned out horizontal right-to-left *page-turning* is what a normal ebook is supposed to do — the vertical-scroll case above is the unusual one. This significantly changes the takeaway: **`page-progression-direction="rtl"` isn't universally wrong to have** — it's the literal on/off switch between the two behaviors, and which one is correct depends on what the book/user wants, not on "it's an RTL book so remove it."

Across four such real books, the pattern each time was the same shared checklist (DOCTYPE, `dir="rtl"` on `<html>`+`<body>`, CSS `direction: rtl`) plus adding (not removing) `page-progression-direction="rtl"` when it was missing. Each book was missing a different subset — one had everything but the spine attribute, another had the spine attribute and `<html>` dir but nothing else — so diagnosing each file's actual starting state mattered more than assuming they'd all be broken the same way. This is now automated in `../scripts/fix_rtl_epub.py`.

Two more real, unrelated defects showed up in these older exported files while rewriting their zips, worth fixing for free since the archive is already being rebuilt: `mimetype` not being the first entry in the zip (a real epubcheck error, `PKG-006`), and the whole archive stored fully uncompressed (harmless but bloats file size — expect a fixed file to shrink noticeably, sometimes by 30%+, with zero content lost).

## Takeaways for next time

- Figure out which direction is wanted FIRST — don't assume. In practice, "make it page/scroll the right way" for a real existing Hebrew book has meant "make it page horizontally" (add `page-progression-direction="rtl"`) far more often than "make it scroll" (remove it). Default assumption if genuinely unstated: the user wants normal page-turning, since that's the standard ebook reading experience and continuous scroll is the exception.
- Regardless of direction, always get right:
  - `<!DOCTYPE>` in every XHTML file — `<!DOCTYPE html>` for EPUB3 (`<package version="3.0">`), the full XHTML 1.1 public DOCTYPE for EPUB2 (`<package version="2.0">`). Using the wrong one for the book's declared version introduces a new epubcheck error.
  - `dir="rtl"` on `<html>` *and* `<body>` — real files are often inconsistent about which one has it.
  - CSS `direction: rtl` on `body` (it inherits down, no need to chase every selector), accepting the resulting EPUBCheck `CSS-001` warning as known-safe noise.
  - No `rendition:*` metadata hints — they didn't help and aren't worth the added surface area.
  - No CSS `overflow`/`column` overrides trying to force a rendering mode — they actively broke things.
- The one switch: `page-progression-direction="rtl"` on `<spine>` present = pages horizontally; absent = scrolls. Add or remove *only* this to change which one a book does.
- When a "should be simple" formatting bug resists two straightforward, spec-based fixes in a row, the fastest path is often to ask the user for a known-good reference file in the same target environment and diff against it structurally, rather than continuing to guess from spec knowledge alone.
- Reader-app behavior for scroll-vs-paginate is often an app-level user setting the EPUB can only weakly hint at. If a user reports the problem persisting after this whole checklist, ask which specific app/device — some apps (e.g. Kindle) don't expose this to the EPUB at all.
- When fixing an existing (not newly-built) EPUB, diff the file's own error count against a fresh epubcheck run of the *original* backup, not against zero — real-world production files often carry a handful of pre-existing, unrelated validation errors that aren't yours to fix unless asked.
