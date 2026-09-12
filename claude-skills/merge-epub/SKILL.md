---
name: merge-epub
description: Merge two or more existing .epub files into a single combined EPUB, each source book kept intact as its own navigable section (cover, chapters, images, fonts all preserved) rather than reflowed into one undifferentiated book. Use when the user wants several EPUBs combined into one file, wants to add a book to an existing combined EPUB, or wants to update/rebuild a combined EPUB after fixing one of its source books.
---

# merge-epub

Combine N existing `.epub` files into one, using `ebooklib`. Each source book stays intact and independently readable as its own section — this is a container merge (repackage everything under shared covers with one navigable TOC), not a content merge (don't touch the individual books' chapter text, formatting, or images).

Parse the invocation as: `<source1.epub> <source2.epub> ... [output.epub]` — a list of source paths (or a folder containing them) and an optional output path. If no output path is given, ask the user for a title/filename before writing anything, since the combined file's title is a real content decision, not a detail to default silently.

If the user wants to **add a book to an already-merged file** (one of the sources is itself a previous output of this skill), see "Updating an existing merged file" below — do not just treat it as one more flat source without reading that section first.

## Before writing any code — inspect every source

For each source file, check with `ebooklib`:
1. `book.get_metadata('DC', 'title')`, `'creator'`, `'language')` — note anything missing, placeholder-looking, or oddly formatted (e.g. an English internal title left over from a template, an unescaped `&apos;`, a locale like `ar-SA` that doesn't match the actual content). Decide per-book title/creator overrides now rather than discovering them after the merge.
2. `book.spine` — the `(idref, linear)` tuples, in order. Note any `linear == 'no'` entries (commonly the cover) — these must survive the merge with their flag intact, not get flattened to `'yes'`.
3. Every item's `file_name` and `get_type()` — different books almost always reuse the same generic names (`cover.xhtml`, `style.css`, `content.opf`) across different folder conventions (`Text/`/`Styles/`/`Images/` vs flat-root vs lowercase `css/`/`image/`/`font/`). Never assume a shared layout; the per-book subfolder plan below sidesteps this regardless of what convention each one uses.
4. The `.opf` filename itself — don't hardcode `content.opf`; some exports use something else (e.g. `mendele.opf`). Always resolve it as `[n for n in zipfile.namelist() if n.endswith('.opf')][0]` if you ever need to touch the OPF directly, and let `ebooklib.read_epub()` handle this for you in the normal path.
5. Whether the book's own NCX/nav item is *itself* placed in its own spine (rare, but real — see pitfalls). If so it's a genuine content page (often the book's own in-book TOC) and must not be dropped just because it's named `nav.xhtml`/`*.ncx`.

None of this needs a full read of every chapter — metadata, spine, and the manifest item list are enough to plan the merge.

## Building the merged book

**The core rule that avoids every bug below: never let `ebooklib` auto-generate an id, and never assume one book's internal file layout won't collide with another's.** Every item you copy gets an explicit `uid` you construct yourself (`f'{prefix}_{original_id}'`) and an explicit `file_name` placed under a per-book subfolder (`f'{prefix}/{original_file_name}'`) that preserves that book's own internal relative structure beneath the prefix.

```python
from ebooklib import epub

def copy_book_items(merged_book, source_book, prefix):
    """Copy every item into its own id/folder namespace. Returns old_id -> new_item."""
    spine_idrefs = {idref for idref, linear in source_book.spine}
    item_by_old_id = {}
    for it in source_book.get_items():
        base = it.file_name.rsplit('/', 1)[-1].lower()
        is_nav_like = base == 'nav.xhtml' or it.file_name.lower().endswith('.ncx')
        # Skip the book's OWN structural nav/ncx -- UNLESS it's genuinely placed in
        # that book's own spine, in which case it's a real page (e.g. an in-book TOC),
        # not throwaway navigation metadata. See pitfalls below.
        if is_nav_like and it.id not in spine_idrefs:
            continue
        new_item = epub.EpubItem(
            uid=f'{prefix}_{it.id}',
            file_name=f'{prefix}/{it.file_name}',
            media_type=it.media_type,
            content=it.get_content(),
        )
        merged_book.add_item(new_item)
        item_by_old_id[it.id] = new_item
    return item_by_old_id

def spine_items(source_book, item_by_old_id):
    """(item, linear) tuples, preserving each source's own linear flag."""
    return [(item_by_old_id[idref], linear)
            for idref, linear in source_book.spine if idref in item_by_old_id]
```

**Wrap each book's own TOC under a top-level `Section` with an explicit `href`.** `epub.Section(title)` defaults to `href=""`. A blank-href Section renders as a plain non-clickable `<span>` in the EPUB3 nav — and worse, in the legacy NCX (what most readers actually use for their "bookmarks"/table-of-contents list), `ebooklib` **backfills the empty navPoint's content src from that section's first child** rather than leaving it blank (NCX can't have an empty `content src`). Since a book's own internal TOC usually starts at its foreword or first chapter — not its cover — the section's bookmark silently opens on the wrong page. Always give the Section an explicit `href` pointing at that book's actual opening page (its own first spine item, which is normally its cover):

```python
book_toc = rewrite_toc(list(source_book.toc), f'{prefix}/', f'{prefix}_')
cover_href = book_spine[0][0].file_name if book_spine else None  # first item in THIS book's own spine
merged.toc.append((epub.Section(book_title, href=cover_href or ''), book_toc))
```

Do the same `href=` fix for any *divider/title page you build yourself* for a book that doesn't already have a physical cover file (see below) — point its Section at that divider page.

**If a source book has no cover page of its own** (e.g. it's markdown-built output from `txt-to-epub`/`txt-to-md` rather than a professionally produced EPUB), build a minimal divider/title page and insert it as that book's first spine item before its own chapters, then use it as the Section's `href`:

```python
divider_html = (
    '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="he" dir="rtl">\n'
    f'<head><title>{book_title}</title>'
    f'<link rel="stylesheet" type="text/css" href="{prefix}/style.css"/></head>\n'
    f'<body style="text-align:center; margin-top:35%;">'
    f'<h1>{book_title}</h1><p>{author}</p></body></html>'
)
divider = epub.EpubHtml(title=book_title, file_name=f'{prefix}/divider.xhtml', lang='he')
divider.content = divider_html.encode('utf-8')
merged.add_item(divider)
# spine: [divider] + this book's own chapter items, in order
```

**Assembling the final book:**

```python
merged = epub.EpubBook()
merged.set_identifier('...')
merged.set_title('...')          # the combined collection's own title, not any one source's
merged.set_language('he')
for author in authors_seen:      # de-duplicated, in first-seen order across all sources
    merged.add_author(author)

merged.spine = []                 # flat list of (item, linear) tuples, one source after another
merged.toc = []                   # list of (Section(title, href=...), [Link, ...]) tuples, one per source

# ... for each source, extend merged.spine and append to merged.toc as shown above ...

merged.add_item(epub.EpubNcx())
merged.add_item(epub.EpubNav())
# Point the combined cover meta at whichever source's cover image you're using as the
# overall cover (commonly the first book's) -- don't call book.set_cover() if you already
# copied that image as a regular item, it will add a second colliding manifest entry:
merged.add_metadata(None, 'meta', '', {'name': 'cover', 'content': f'{prefix}_{cover_item_id}'})

epub.write_epub(output_path, merged)
```

## Updating an existing merged file

When one of the "sources" is itself a previous output of this skill (it already has multiple `Section` entries in its own `book.toc`), **splice its existing sections in directly as their own top-level entries** rather than wrapping the whole thing in one more layer of `Section`. This keeps the combined TOC flat (one entry per actual book) instead of growing an extra nesting level every time something gets added to an already-merged file:

```python
for node in already_merged_source.toc:
    if isinstance(node, tuple):          # (Section, children) -- one of its earlier sources
        sec_title = node[0].title
        rewritten = rewrite_toc(node[1], f'{prefix}/', f'{prefix}_')
        sec_href = first_leaf_href(rewritten)   # see helper below
        merged.toc.append((epub.Section(sec_title, href=sec_href or ''), rewritten))
```

**Prefer rebuilding from all the original individual sources in one pass over repeatedly appending to an already-merged output.** Appending to an already-merged file works and is fine for a quick one-off addition, but every additional book you fold in through this skill was itself produced by a fresh `epub.EpubBook()` instance elsewhere, and if you ever create a fresh divider/title page in each merge pass without giving it an explicit `uid`, two dividers from two separate merge runs can land on the exact same `ebooklib`-auto-generated default id (`chapter_0` — `ebooklib` numbers untagged `EpubHtml` items sequentially per book instance, so the *first* untagged item in *any* fresh `EpubBook()` always gets the same default id). Two manifest items sharing an id is invisible until a reader tries to follow the spine through that exact id and gets resolved to the *first* matching manifest entry instead of the intended one — symptom: "next page" from the end of one book jumps backward to the start of an earlier book instead of forward into the new one. Always give every `EpubHtml`/`EpubItem` you construct yourself an explicit `uid`, and when in doubt, rebuild from the original sources rather than layering merges.

## Validate before considering it done

`ebooklib.read_epub()` round-tripping without an exception is **not sufficient** — it won't surface duplicate ids or dangling references reliably. Check the raw OPF/NCX XML directly:

```python
import zipfile, re
from collections import Counter

z = zipfile.ZipFile(output_path)
opf_name = [n for n in z.namelist() if n.endswith('.opf')][0]
opf = z.read(opf_name).decode('utf-8')

manifest_ids = re.findall(r'<item\b[^>]*\bid="([^"]+)"', opf)
spine_ids = re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)
print('duplicate manifest ids:', {k: v for k, v in Counter(manifest_ids).items() if v > 1})
print('duplicate spine idrefs:', {k: v for k, v in Counter(spine_ids).items() if v > 1})
print('dangling spine idrefs:', [i for i in spine_ids if i not in set(manifest_ids)])

hrefs = re.findall(r'<item\b[^>]*\bhref="([^"]+)"', opf)
opf_dir = opf_name.rsplit('/', 1)[0] + '/' if '/' in opf_name else ''
names = set(z.namelist())
print('missing files:', [h for h in hrefs if (opf_dir + h) not in names])

import xml.dom.minidom as minidom
minidom.parseString(opf)  # raises if malformed
```

All four checks must come back empty/clean. Then separately confirm every top-level bookmark actually resolves where you intended (this is the check that catches the `Section`-with-no-`href` bug even when the XML is otherwise perfectly valid):

```python
# Parse the real toc.ncx (not any source book's copied-in *.ncx, which will also
# match a loose "*.ncx" glob once copied into the merged file) and print each
# top-level navPoint's label -> content src, then eyeball that every one lands on
# a cover/opening page rather than a mid-book chapter.
```

## Known pitfalls

- **Generic filenames collide across books.** `cover.xhtml`, `style.css`, `content.opf` show up in most independently-produced EPUBs. The per-book subfolder prefix sidesteps this entirely — never try to merge multiple books' files into shared folders even if their internal layouts happen to look identical.
- **A source book's own nav.xhtml/`*.ncx` can be genuine content**, not just structural metadata, if that exact item is also listed in the book's own spine (some books place their own in-book TOC page there deliberately). Check spine membership before excluding by filename — see `copy_book_items` above. Dropping it unconditionally silently removes a real page a reader would otherwise see.
- **A blank-`href` `Section` silently sends readers to the wrong page**, not to an error — this fails quietly and only shows up when someone actually clicks the bookmark. Always pass an explicit `href` (see above), and verify it post-build with the NCX top-level check, not just by trusting the code.
- **Id collisions across separately-instantiated `EpubBook()` objects are invisible in normal validation** — `ebooklib.read_epub()` succeeds, the file opens fine in many readers, and it *looks* correct until someone actually reads through a book-boundary transition and the "next page" button jumps to the wrong place. This is why explicit ids on every item you create (not just items you copy) are non-negotiable, and why the raw-OPF duplicate-id check above is part of the validation step, not optional.
- **HTML entities in metadata may not get decoded by `ebooklib`** (e.g. an author name stored as `Name&apos;s` renders literally instead of as `Name's`). Run `html.unescape()` on any `DC.title`/`DC.creator` value you pull out before reusing it.
- **Don't call `book.set_cover()` if you already copied that image as a regular `EpubItem`** — it adds a second manifest item at the same `file_name`/a colliding id. Just add the `meta name="cover"` entry pointing at the item id you already have.
- **`linear='no'` spine items (typically covers) must be preserved as tuples**, not flattened into a bare list of items (which defaults everything to `'yes'`). If you've already lost this flag in a previous merge pass and no longer have the original source to recover it from, it's a cosmetic loss, not a functional one — don't chase it further than one attempt.
