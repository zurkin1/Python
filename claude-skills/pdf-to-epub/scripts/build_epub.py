"""
Package a directory of already-written XHTML/CSS/images into a valid EPUB3,
with the RTL scrolling-correctness rules (see references/rtl-epub-notes.md)
baked into the generated container.xml / content.opf / nav.xhtml / toc.ncx.

This does NOT write your chapter XHTML files for you — write those yourself
(or adapt gen_epub-style code) applying the same rules: <!DOCTYPE html>,
dir="rtl" on both <html> and <body> if the book is RTL, and (for RTL books)
CSS `direction: rtl` on your text-bearing selectors despite EPUBCheck
flagging it. This script handles everything AROUND those files: the
manifest, spine (deliberately with NO page-progression-direction attribute),
nav/toc, and zipping.

Expected input layout (relative to --oebps-dir):
    text/*.xhtml       - one file per spine item, already written
    images/*           - .png/.jpg/.jpeg/.gif/.svg
    styles/*.css        - your stylesheet(s)

Spec file (--spec, JSON) describes reading order and nav structure:
{
  "title": "Book Title",
  "creator": "Author Name",
  "language": "he",
  "rtl": true,
  "cover_image": "cover.png",          // filename inside images/, optional
  "spine": [
    {"id": "cover", "href": "cover.xhtml", "title": "Cover", "in_nav": false},
    {"id": "ch01", "href": "ch01.xhtml", "title": "Chapter 1",
     "subsections": [{"anchor": "sec1", "title": "First heading"}]}
  ]
}
`href` is relative to text/. `in_nav` defaults to true; set false for
cover/copyright-page-style spine items you don't want listed in the TOC.

Usage:
    python build_epub.py --oebps-dir path/to/OEBPS --spec book_spec.json --out book.epub
"""
import argparse
import datetime
import json
import os
import uuid
import zipfile

MEDIA_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.svg': 'image/svg+xml',
}


def build(oebps_dir, spec, out_path):
    title = spec['title']
    creator = spec.get('creator', '')
    language = spec.get('language', 'en')
    rtl = spec.get('rtl', False)
    cover_image = spec.get('cover_image')
    spine_spec = spec['spine']

    book_uuid = spec.get('identifier') or ('urn:uuid:' + str(uuid.uuid4()))
    dir_attr = ' dir="rtl"' if rtl else ''

    # ---- mimetype ----
    with open(os.path.join(oebps_dir, '..', 'mimetype'), 'w', encoding='ascii', newline='') as f:
        f.write('application/epub+zip')

    # ---- META-INF/container.xml ----
    meta_inf = os.path.join(oebps_dir, '..', 'META-INF')
    os.makedirs(meta_inf, exist_ok=True)
    with open(os.path.join(meta_inf, 'container.xml'), 'w', encoding='utf-8') as f:
        f.write('''<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
''')

    # ---- nav.xhtml ----
    def nav_li(item):
        href = f"text/{item['href']}"
        subs = item.get('subsections', [])
        if subs:
            inner = ''.join(f'<li><a href="{href}#{s["anchor"]}">{s["title"]}</a></li>\n' for s in subs)
            return f'<li><a href="{href}">{item["title"]}</a><ol>{inner}</ol></li>\n'
        return f'<li><a href="{href}">{item["title"]}</a></li>\n'

    nav_items = ''.join(nav_li(it) for it in spine_spec if it.get('in_nav', True))
    cover_item = next((it for it in spine_spec if it['id'] == 'cover'), None)
    body_item = next((it for it in spine_spec if it.get('in_nav', True)), None)
    landmarks = '<nav epub:type="landmarks" hidden="">\n<ol>\n'
    if cover_item:
        landmarks += f'<li><a epub:type="cover" href="text/{cover_item["href"]}">Cover</a></li>\n'
    if body_item:
        landmarks += f'<li><a epub:type="bodymatter" href="text/{body_item["href"]}">Start</a></li>\n'
    landmarks += '</ol>\n</nav>\n'

    with open(os.path.join(oebps_dir, 'nav.xhtml'), 'w', encoding='utf-8') as f:
        f.write(f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"{dir_attr} xml:lang="{language}" lang="{language}">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
</head>
<body{dir_attr}>
<nav epub:type="toc" id="toc">
<ol>
{nav_items}</ol>
</nav>
{landmarks}
</body>
</html>
''')

    # ---- toc.ncx ----
    idx = 0
    ncx_body = ''
    for it in spine_spec:
        if not it.get('in_nav', True):
            continue
        idx += 1
        ncx_body += (f'<navPoint id="np{idx}" playOrder="{idx}"><navLabel><text>{it["title"]}</text>'
                      f'</navLabel><content src="text/{it["href"]}"/>\n')
        for s in it.get('subsections', []):
            idx += 1
            ncx_body += (f'<navPoint id="np{idx}" playOrder="{idx}"><navLabel><text>{s["title"]}</text>'
                          f'</navLabel><content src="text/{it["href"]}#{s["anchor"]}"/></navPoint>\n')
        ncx_body += '</navPoint>\n'

    with open(os.path.join(oebps_dir, 'toc.ncx'), 'w', encoding='utf-8') as f:
        f.write(f'''<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{language}">
<head><meta name="dtb:uid" content="{book_uuid}"/></head>
<docTitle><text>{title}</text></docTitle>
<navMap>
{ncx_body}</navMap>
</ncx>
''')

    # ---- content.opf ----
    manifest_items = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                       '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>']
    spine_items = []
    for it in spine_spec:
        manifest_items.append(f'<item id="{it["id"]}" href="text/{it["href"]}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="{it["id"]}"/>')  # no page-progression-direction on <spine> either

    styles_dir = os.path.join(oebps_dir, 'styles')
    if os.path.isdir(styles_dir):
        for fname in sorted(os.listdir(styles_dir)):
            manifest_items.append(f'<item id="css-{fname.rsplit(".",1)[0]}" href="styles/{fname}" media-type="text/css"/>')

    images_dir = os.path.join(oebps_dir, 'images')
    cover_id = None
    if os.path.isdir(images_dir):
        for fname in sorted(os.listdir(images_dir)):
            ext = os.path.splitext(fname)[1].lower()
            mt = MEDIA_TYPES.get(ext)
            if not mt:
                continue
            iid = 'img-' + fname.rsplit('.', 1)[0]
            props = ''
            if cover_image and fname == cover_image:
                props = ' properties="cover-image"'
                cover_id = iid
            manifest_items.append(f'<item id="{iid}" href="images/{fname}" media-type="{mt}"{props}/>')

    cover_meta = f'<meta name="cover" content="{cover_id}"/>\n' if cover_id else ''

    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"{dir_attr} xml:lang="{language}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bookid">{book_uuid}</dc:identifier>
<dc:title>{title}</dc:title>
<dc:creator>{creator}</dc:creator>
<dc:language>{language}</dc:language>
<meta property="dcterms:modified">{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</meta>
{cover_meta}</metadata>
<manifest>
{chr(10).join(manifest_items)}
</manifest>
<spine toc="ncx">
{chr(10).join(spine_items)}
</spine>
</package>
'''
    with open(os.path.join(oebps_dir, 'content.opf'), 'w', encoding='utf-8') as f:
        f.write(opf)

    # ---- zip ----
    build_root = os.path.dirname(oebps_dir)
    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, 'w') as zf:
        zf.write(os.path.join(build_root, 'mimetype'), 'mimetype', compress_type=zipfile.ZIP_STORED)
        for root, _dirs, files in os.walk(build_root):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, build_root).replace('\\', '/')
                if rel == 'mimetype':
                    continue
                zf.write(full, rel, compress_type=zipfile.ZIP_DEFLATED)

    print(f'wrote {out_path} ({len(spine_items)} spine items, {len(manifest_items)} manifest items)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--oebps-dir', required=True, help='path to the OEBPS directory (contains text/, images/, styles/)')
    ap.add_argument('--spec', required=True, help='path to the JSON spec file (see module docstring)')
    ap.add_argument('--out', required=True, help='output .epub path')
    args = ap.parse_args()
    with open(args.spec, encoding='utf-8') as f:
        spec = json.load(f)
    build(args.oebps_dir, spec, args.out)


if __name__ == '__main__':
    main()
