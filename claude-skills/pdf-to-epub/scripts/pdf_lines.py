"""
Reconstruct true visual print-lines from a PyMuPDF (fitz) page.

Why this exists: page.get_text() and page.get_text("dict") often split ONE
printed line into several internal "line" objects — one per word or short
phrase — especially in RTL-authored PDFs where each word can carry its own
explicit text-positioning command. Grouping purely by fitz's own "line"
boundaries under-merges; grouping by exact (y0, y1) rounding is fragile to
sub-pixel jitter between fragments that are visually on the same row.

get_visual_lines() clusters text spans by y-proximity (tolerant of a few
points of jitter) into one record per real printed line, with the spans
ordered right-to-left within the line (correct reading order for RTL text;
harmless for LTR text since a mostly-LTR line usually has one span anyway).
Each record carries x0/x1/size so callers can derive paragraph indentation
and heading font-size jumps.

Usage:
    import fitz
    from pdf_lines import get_visual_lines
    doc = fitz.open("book.pdf")
    for line in get_visual_lines(doc[10]):
        print(line['y0'], line['x0'], line['x1'], line['size'], line['text'])

Quick CLI inspection of a page range:
    python pdf_lines.py book.pdf 8 12
"""
import fitz


def get_visual_lines(page, tol=4.0):
    """Return a list of dicts {y0, y1, x0, x1, text, size}, one per visual
    print-line on the page, sorted top-to-bottom. `tol` is the y-distance (in
    PDF points) within which two fragments are considered the same line —
    raise it if a page's lines are being split, lower it if unrelated lines
    are merging."""
    d = page.get_text('dict')
    raw = []
    for b in d['blocks']:
        if b.get('type') != 0:  # 0 = text block; skip images etc.
            continue
        for ln in b['lines']:
            y0, y1 = ln['bbox'][1], ln['bbox'][3]
            raw.append((y0, y1, ln['spans']))
    raw.sort(key=lambda r: r[0])

    clusters = []
    for y0, y1, spans in raw:
        placed = False
        for c in clusters:
            if abs(c['y0'] - y0) < tol:
                c['spans'].extend(spans)
                c['y0'] = min(c['y0'], y0)
                c['y1'] = max(c['y1'], y1)
                placed = True
                break
        if not placed:
            clusters.append({'y0': y0, 'y1': y1, 'spans': list(spans)})

    out = []
    for c in clusters:
        # right-to-left order: sort by descending x0. For LTR text this is
        # usually a no-op since each line tends to be one span anyway; if you
        # know the page is LTR, sort by ascending x0 instead.
        spans_sorted = sorted(c['spans'], key=lambda s: -s['bbox'][0])
        text = ''.join(s['text'] for s in spans_sorted)
        x0 = min(s['bbox'][0] for s in c['spans'])
        x1 = max(s['bbox'][2] for s in c['spans'])
        maxsize = max(s['size'] for s in c['spans'])
        out.append({'y0': c['y0'], 'y1': c['y1'], 'x0': x0, 'x1': x1,
                     'text': text.strip(), 'size': round(maxsize, 1)})
    out.sort(key=lambda r: r['y0'])
    return out


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('usage: python pdf_lines.py <pdf_path> [first_page] [last_page]')
        raise SystemExit(1)
    path = sys.argv[1]
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    last = int(sys.argv[3]) if len(sys.argv) > 3 else first
    doc = fitz.open(path)
    for pno in range(first, last + 1):
        print(f'=== page {pno}')
        for r in get_visual_lines(doc[pno - 1]):
            print(f"  y=({r['y0']:.0f},{r['y1']:.0f}) x=({r['x0']:.0f},{r['x1']:.0f}) "
                  f"size={r['size']}  {r['text']!r}")
