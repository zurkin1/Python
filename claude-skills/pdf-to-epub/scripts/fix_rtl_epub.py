# -*- coding: utf-8 -*-
"""
Fix an EXISTING EPUB (not one you're building from scratch) so it pages
horizontally right-to-left in real reader apps, instead of scrolling down or
paging the wrong way. This is the "someone handed me a finished .epub and it
reads sideways/wrong" tool — for building a new EPUB from a PDF, see
build_epub.py instead (and pdf_lines.py / extract_images.py for extraction).

Background: many commercially-produced Hebrew EPUBs (especially ones
exported from Adobe InDesign, or converted years ago with Calibre) are
missing one or more of the signals real reader apps use to decide "this book
pages right-to-left" vs. "this book scrolls." Seen in the wild, roughly in
order of how often each was the missing piece:
  - <spine> has no page-progression-direction="rtl" at all.
  - <html>/<body> have no dir="rtl" (sometimes one has it and not the other).
  - The stylesheet has no CSS `direction: rtl` on `body` (text-align: right
    alone isn't equivalent for how some reader engines pick a layout axis).
  - No <!DOCTYPE> in the XHTML files.
  - (Unrelated to RTL, but seen alongside it and free to fix while rewriting
    the zip anyway) `mimetype` not being the first, uncompressed entry in
    the archive, or literally everything in the zip stored uncompressed.

See ../references/rtl-epub-notes.md for the full investigation this was
distilled from, including why some fixes that sound "more correct" (EPUB3
rendition:flow hints, CSS overflow/column overrides) turned out to be
useless or actively harmful — this script deliberately does NOT do those.

Every fix here is written to be a no-op if that piece is already correct,
so it's safe to run against a book that only needs one or two of these
without manually diagnosing first — though DIAGNOSING FIRST is still worth
doing (see below) so you know what you're about to change and can tell the
user why, and so you pick the right --doctype for the book's actual EPUB
version.

Diagnose first:
    - <package version="2.0"> (EPUB2) wants the full XHTML 1.1 public
      DOCTYPE; <package version="3.0"> (EPUB3) wants the plain HTML5
      "<!DOCTYPE html>". Passing the wrong one for the book's declared
      version can itself introduce a NEW epubcheck error ("Irregular
      DOCTYPE") where there was none before - check <package version="...">
      in content.opf and pass --doctype accordingly (default: html5).
    - If the book already has page-progression-direction="rtl" and you're
      asked to make it scroll instead, this is the WRONG script - you want
      to remove that attribute and the other paginated-book signals, not add
      them. This script only adds the paginated/horizontal signals.

Always back up the original file before running this against a real file -
it does not create a backup itself.

CLI usage (only safe for ASCII-only paths - see note below):
    python fix_rtl_epub.py src.epub dst.epub [--doctype html5|xhtml11]

For non-ASCII (e.g. Hebrew-named) file paths, don't rely on shell argv -
Windows shells can mangle non-ASCII CLI arguments. Instead write a tiny
driver script and run that:
    import sys
    sys.path.insert(0, r"<path to this scripts/ dir>")
    from fix_rtl_epub import fix_epub
    fix_epub(r"C:\path\to\<hebrew name>.epub", r"C:\path\to\<hebrew name>.epub")
(fix_epub writes to a temp file first and only replaces dst at the end, so
passing the same path for src and dst to edit in place is safe.)
"""
import argparse
import os
import re
import shutil
import tempfile
import zipfile

XML_PROLOG = "<?xml version='1.0' encoding='utf-8'?>\n"
DOCTYPES = {
    'html5': '<!DOCTYPE html>\n',
    'xhtml11': ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
                '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'),
}

HTML_TAG_RE = re.compile(r'<html\b([^>]*)>')
BODY_TAG_RE = re.compile(r'<body\b([^>]*)>')
SPINE_TAG_RE = re.compile(r'<spine\b([^>]*)>')


def _fix_html_attrs(attrs):
    if 'dir=' not in attrs:
        attrs += ' dir="rtl"'
    if 'xml:lang=' not in attrs:
        attrs += ' xml:lang="he"'
    if ' lang=' not in attrs:
        attrs += ' lang="he"'
    return attrs


def _fix_body_attrs(attrs):
    if 'dir=' not in attrs:
        attrs += ' dir="rtl"'
    return attrs


def fix_xhtml(data: str, doctype: str = 'html5') -> str:
    doctype_str = DOCTYPES[doctype]
    if not data.lstrip().startswith('<?xml'):
        data = XML_PROLOG + doctype_str + data
    elif '<!DOCTYPE' not in data:
        nl = data.find('\n') + 1
        data = data[:nl] + doctype_str + data[nl:]

    data = HTML_TAG_RE.sub(lambda m: '<html' + _fix_html_attrs(m.group(1)) + '>', data, count=1)
    data = BODY_TAG_RE.sub(lambda m: '<body' + _fix_body_attrs(m.group(1)) + '>', data, count=1)
    return data


def fix_css(data: str) -> str:
    """Add `direction: rtl;` to the standalone `body { ... }` rule. Relies on
    CSS inheritance to cascade to every descendant (p, span, div, ...)
    rather than trying to guess the book's paragraph class names."""
    def body_block(m):
        block = m.group(0)
        if re.search(r'direction\s*:', block):
            return block
        return block[:-1].rstrip() + '\n\tdirection:rtl;\n}'
    # \bbody\s*\{ only matches a standalone "body {" rule; a grouped selector
    # like "body, div, p {" has a comma right after "body", not "{", so it's
    # left alone.
    new_data, n = re.subn(r'\bbody\s*\{[^}]*\}', body_block, data, count=1)
    if n == 0:
        new_data = 'body {\n\tdirection:rtl;\n}\n' + data
    return new_data


def fix_opf(data: str) -> str:
    def spine_sub(m):
        attrs = m.group(1)
        if 'page-progression-direction=' not in attrs:
            attrs += ' page-progression-direction="rtl"'
        return '<spine' + attrs + '>'
    return SPINE_TAG_RE.sub(spine_sub, data, count=1)


def fix_epub(src: str, dst: str, doctype: str = 'html5', css_suffix: str = '.css'):
    """Read the EPUB at `src`, apply the horizontal-RTL-paging fixes, and
    write the result to `dst` (which may be the same path as `src` - the
    rewrite happens in a temp file first, so this is safe for in-place
    edits). `doctype` is 'html5' (EPUB3 books) or 'xhtml11' (EPUB2 books) -
    check <package version="..."> in the book's content.opf first."""
    fd, tmp = tempfile.mkstemp(suffix='.epub', dir=os.path.dirname(os.path.abspath(dst)) or '.')
    os.close(fd)
    try:
        zin = zipfile.ZipFile(src, 'r')
        items = zin.infolist()
        items.sort(key=lambda it: it.filename != 'mimetype')  # mimetype must be first
        with zipfile.ZipFile(tmp, 'w') as zout:
            for item in items:
                data = zin.read(item.filename)
                if item.filename.endswith('.xhtml') or item.filename.endswith('.html'):
                    data = fix_xhtml(data.decode('utf-8'), doctype).encode('utf-8')
                elif item.filename.endswith(css_suffix):
                    data = fix_css(data.decode('utf-8')).encode('utf-8')
                elif item.filename.endswith('content.opf'):
                    data = fix_opf(data.decode('utf-8')).encode('utf-8')
                # mimetype must be STORED (uncompressed); DEFLATE everything else -
                # some real-world EPUBs store every entry uncompressed, which just
                # bloats the file for no benefit.
                compress = zipfile.ZIP_STORED if item.filename == 'mimetype' else zipfile.ZIP_DEFLATED
                zout.writestr(item, data, compress_type=compress)
        zin.close()
        shutil.move(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print(f'fixed -> {dst}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--doctype', choices=['html5', 'xhtml11'], default='html5',
                     help='html5 for EPUB3 books, xhtml11 for EPUB2 books (check <package version="..."> in content.opf)')
    args = ap.parse_args()
    fix_epub(args.src, args.dst, args.doctype)
