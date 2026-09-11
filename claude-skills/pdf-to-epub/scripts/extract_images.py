"""
Crop the real photo/diagram content out of per-page raster images in a PDF,
skipping pages whose embedded raster is just blank/decorative/DRM noise.

Background: many PDFs embed one full-page-sized raster image per page, not
just on pages with real photos. Sometimes it's a paper-texture/decoration.
Sometimes (seen in a "protected"/watermarked digital edition) it's a
deliberately BLURRED duplicate of the page's own text, sitting under sharp
vector text as a copy-protection trick — so almost every page has *some*
faint non-white content in its raster even though there's no real image
there. Naively re-embedding every page's raster as a "photo" in the EPUB
would be wrong (duplicates the real text, ships pointless page-sized images).

This script:
  1. Computes a per-page mask combining edge-magnitude (catches
     photos/diagrams even against a busy or textured background) and
     absolute darkness (catches soft/low-contrast photos edge-detection
     alone would miss).
  2. Dilates the mask and finds connected components.
  3. Keeps only components that are both big enough (area) AND dense enough
     within their own bounding box (fill ratio) — this is what rejects a
     blurred-text background or a page of index/table entries, which are
     large-area but sparse, versus a real photo/diagram, which is dense.
  4. Crops each surviving component (with a small pad) to its own PNG.

Tune EDGE_THRESH / DARK_THRESH / MIN_AREA_FRAC / DENSITY_MIN against the
specific book — the defaults were calibrated on one real book and are a
starting point, not universal constants. If a known cover/full-bleed page
is wrongly getting cropped into pieces, add its page number to
FULLBLEED_PAGES to keep it whole instead.

Usage:
    python extract_images.py book.pdf out_dir/ [--fullbleed 1,2,215]

Produces out_dir/pageNNN_0.png, pageNNN_1.png, ... and out_dir/manifest.json
mapping page number -> list of {file, bbox_px, page_px}.
"""
import argparse
import json
import os

import fitz
import numpy as np
from PIL import Image
from scipy import ndimage

EDGE_THRESH = 10
DARK_THRESH = 225
MIN_AREA_FRAC = 0.006
DENSITY_MIN = 0.12
MIN_DIM = 60
PAD = 8


def get_page_raster(doc, page):
    imgs = page.get_images(full=True)
    if not imgs:
        return None
    xref = imgs[0][0]
    pix = fitz.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    mode = 'RGB' if pix.n >= 3 else 'L'
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def find_photo_boxes(img):
    """Return a list of (x0, y0, x1, y1) pixel boxes for real photo/diagram
    content on this page's raster, top-to-bottom."""
    gray = np.array(img.convert('L')).astype(np.float32)
    h, w = gray.shape

    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    grad = gx + gy
    mask = (grad > EDGE_THRESH) | (gray < DARK_THRESH)

    if mask.mean() < 0.006:
        return []

    dil = ndimage.binary_dilation(mask, iterations=12)
    labeled, n = ndimage.label(dil)
    page_area = h * w
    boxes = []
    for lbl in range(1, n + 1):
        ys, xs = np.where(labeled == lbl)
        comp_area = len(ys)
        if comp_area < MIN_AREA_FRAC * page_area:
            continue
        y0, y1 = ys.min(), ys.max()
        x0, x1 = xs.min(), xs.max()
        bw, bh = x1 - x0, y1 - y0
        if bw < MIN_DIM or bh < MIN_DIM:
            continue
        density = mask[y0:y1, x0:x1].sum() / (bw * bh)
        if density < DENSITY_MIN:
            continue
        boxes.append((y0, x0, y1, x1))
    boxes.sort(key=lambda b: b[0])
    return [(x0, y0, x1, y1) for y0, x0, y1, x1 in boxes]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf_path')
    ap.add_argument('out_dir')
    ap.add_argument('--fullbleed', default='',
                     help='comma-separated 1-indexed page numbers to keep whole '
                          '(covers, full-page art) instead of component-cropping')
    args = ap.parse_args()

    fullbleed_pages = {int(x) for x in args.fullbleed.split(',') if x.strip()}
    os.makedirs(args.out_dir, exist_ok=True)
    doc = fitz.open(args.pdf_path)
    manifest = {}

    for i in range(len(doc)):
        pno = i + 1
        img = get_page_raster(doc, doc[i])
        if img is None:
            continue
        w, h = img.size

        if pno in fullbleed_pages:
            fname = f'page{pno:03d}_0.png'
            img.convert('RGB').save(os.path.join(args.out_dir, fname))
            manifest[str(pno)] = [{'file': fname, 'bbox_px': [0, 0, w, h],
                                    'page_px': [w, h], 'fullbleed': True}]
            continue

        boxes = find_photo_boxes(img)
        if not boxes:
            continue
        entries = []
        for j, (x0, y0, x1, y1) in enumerate(boxes):
            cx0, cy0 = max(0, x0 - PAD), max(0, y0 - PAD)
            cx1, cy1 = min(w, x1 + PAD), min(h, y1 + PAD)
            crop = img.crop((cx0, cy0, cx1, cy1))
            fname = f'page{pno:03d}_{j}.png'
            crop.save(os.path.join(args.out_dir, fname))
            entries.append({'file': fname, 'bbox_px': [int(cx0), int(cy0), int(cx1), int(cy1)],
                             'page_px': [int(w), int(h)]})
        manifest[str(pno)] = entries

    with open(os.path.join(args.out_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    total = sum(len(v) for v in manifest.values())
    print(f'{total} image(s) extracted across {len(manifest)} page(s) -> {args.out_dir}')


if __name__ == '__main__':
    main()
