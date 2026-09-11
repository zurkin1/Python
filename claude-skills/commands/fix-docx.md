# fix-docx

Diagnose and fix slow-opening/saving `.docx` files caused by PDF-to-Word conversion bloat.

## Background

When a PDF is converted to Word (via Word's built-in converter, Adobe, or online tools), the resulting `.docx` is typically enormous and slow because:

1. **Per-character run fragmentation** — Every character or word becomes its own `<w:r>` run, each carrying explicit inline formatting (font, size, color, letter-spacing, character-width). A normal 50-page document may have 400k–500k runs instead of ~10k.
2. **Redundant default properties** — Runs explicitly state `color=000000` (black = Word default), near-white shading (`FDFDFD`, `FCFCFC`), and other properties that are already implied by Normal style.
3. **PDF-artifact spacing** — Per-character `<w:spacing>` (letter tracking) and `<w:w>` (character width %) are recorded for every run to faithfully reproduce PDF glyph positions. These are meaningless in an editable Word document.
4. **Duplicate fallback copies** — Each floating drawing/textbox is stored twice inside `<mc:AlternateContent>`: once in `<mc:Choice>` (modern Word) and once in `<mc:Fallback>` (legacy compatibility). The fallback doubles the textbox XML with no benefit for any current Word version.
5. **Floating text boxes** — PDF converters place every text block as an absolutely-positioned floating text box (`<wp:anchor>`). Word recalculates layout for every floating object on every open/save. 3,000+ text boxes = minutes of recalculation.

## Diagnosis steps

Run this to get a quick profile of any `.docx`:

```python
import zipfile
from lxml import etree
from collections import Counter

W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

with zipfile.ZipFile("yourfile.docx", "r") as z:
    info = z.getinfo("word/document.xml")
    print(f"document.xml uncompressed: {info.file_size/1024/1024:.1f} MB")
    xml = z.read("word/document.xml")

tree = etree.fromstring(xml)
tags = Counter(el.tag.split("}")[1] if "}" in el.tag else el.tag for el in tree.iter())
for tag, n in tags.most_common(15):
    print(f"  {n:8,}  {tag}")

drawings = list(tree.iter(f"{{{W}}}drawing"))
anchored = [d for d in drawings if d.find(f"{{{WP}}}anchor") is not None]
print(f"\nFloating drawings: {len(anchored)}")
print(f"mc:Fallback blocks: {len(list(tree.iter(f'{{{MC}}}Fallback')))}")
```

**Warning signs:**
- `document.xml` uncompressed > 10 MB
- `<w:r>` count > 50k (especially if >> paragraph count)
- `<w:spacing>` count close to run count
- Floating drawings in the hundreds or thousands

## The fix script

Save as `fix_docx.py` and run from the same directory as the `.docx`:

```python
"""
Fix slow-opening .docx files caused by PDF-to-Word conversion bloat.
Preserves layout (floating text boxes stay floating).
"""
import zipfile, shutil, os
from lxml import etree

# ── Configure these ───────────────────────────────────────────────────────────
INPUT  = "your-file.docx"
OUTPUT = "your-file-fixed.docx"
# ─────────────────────────────────────────────────────────────────────────────

W   = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC  = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NEAR_WHITE_FILLS = {"FDFDFD", "FCFCFC", "FDFCFD", "FEFEFE", "FFFFFF"}


def strip_redundant_rpr(rpr_el):
    """Remove PDF-conversion artifacts and Word-default properties from a run's rPr."""
    removed = 0
    for child in list(rpr_el):
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        # Black = Word default, never needs stating
        if tag == "color" and child.get(f"{{{W}}}val", "").upper() == "000000":
            rpr_el.remove(child); removed += 1; continue
        # Near-white shading = visually invisible noise
        if tag == "shd":
            fill = child.get(f"{{{W}}}fill", "").upper()
            val  = child.get(f"{{{W}}}val", "").lower()
            if fill in NEAR_WHITE_FILLS or val == "clear":
                rpr_el.remove(child); removed += 1; continue
        # Per-character letter-spacing from PDF glyph positioning
        if tag == "spacing":
            rpr_el.remove(child); removed += 1; continue
        # Per-character width scaling from PDF glyph positioning
        if tag == "w":
            rpr_el.remove(child); removed += 1; continue
    return removed


def rpr_key(rpr_el):
    return etree.tostring(rpr_el, encoding="unicode") if rpr_el is not None else ""


def merge_runs_in_paragraph(para_el):
    """Merge consecutive runs with identical formatting."""
    merged = 0
    allowed = {f"{{{W}}}rPr", f"{{{W}}}t"}
    while True:
        runs = para_el.findall(f"{{{W}}}r")
        changed = False
        i = 0
        while i < len(runs) - 1:
            cur, nxt = runs[i], runs[i + 1]
            cur_t = cur.findall(f"{{{W}}}t")
            nxt_t = nxt.findall(f"{{{W}}}t")
            if len(cur_t) != 1 or len(nxt_t) != 1:
                i += 1; continue
            if not {c.tag for c in cur}.issubset(allowed) or \
               not {c.tag for c in nxt}.issubset(allowed):
                i += 1; continue
            if rpr_key(cur.find(f"{{{W}}}rPr")) != rpr_key(nxt.find(f"{{{W}}}rPr")):
                i += 1; continue
            combined = (cur_t[0].text or "") + (nxt_t[0].text or "")
            cur_t[0].text = combined
            if combined != combined.strip():
                cur_t[0].set(XML_SPACE, "preserve")
            para_el.remove(nxt)
            runs = para_el.findall(f"{{{W}}}r")
            merged += 1; changed = True
        if not changed:
            break
    return merged


def strip_fallbacks(tree):
    """Remove mc:Fallback from every mc:AlternateContent (halves textbox XML)."""
    removed = 0
    for ac in tree.iter(f"{{{MC}}}AlternateContent"):
        for fb in ac.findall(f"{{{MC}}}Fallback"):
            ac.remove(fb)
            removed += 1
    return removed


def process():
    with zipfile.ZipFile(INPUT, "r") as zin:
        xml = zin.read("word/document.xml")

    tree = etree.fromstring(xml)

    # 1. Strip redundant run properties
    stripped = 0
    for r in tree.iter(f"{{{W}}}r"):
        rpr = r.find(f"{{{W}}}rPr")
        if rpr is not None:
            stripped += strip_redundant_rpr(rpr)
            if len(rpr) == 0:
                r.remove(rpr)

    # 2. Merge adjacent identical runs
    merged = 0
    for para in tree.iter(f"{{{W}}}p"):
        merged += merge_runs_in_paragraph(para)

    # 3. Strip mc:Fallback duplicates
    fallbacks = strip_fallbacks(tree)

    new_xml = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)

    shutil.copy(INPUT, OUTPUT)
    tmp = OUTPUT + ".tmp"
    with zipfile.ZipFile(OUTPUT, "r") as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "word/document.xml":
                zout.writestr(item, new_xml)
            else:
                zout.writestr(item, zin.read(item.filename))
    os.replace(tmp, OUTPUT)

    orig_kb  = os.path.getsize(INPUT)  / 1024
    fixed_kb = os.path.getsize(OUTPUT) / 1024
    print(f"Properties stripped : {stripped:,}")
    print(f"Runs merged         : {merged:,}")
    print(f"Fallbacks removed   : {fallbacks:,}")
    print(f"Original size       : {orig_kb:.0f} KB")
    print(f"Fixed size          : {fixed_kb:.0f} KB  ({100*(1 - fixed_kb/orig_kb):.0f}% smaller)")
    print(f"Output              : {OUTPUT}")


if __name__ == "__main__":
    process()
```

## What gets changed vs. preserved

| Changed (safe to remove) | Preserved |
|---|---|
| `w:color="000000"` (black = default) | All bold, italic, underline |
| Near-white `w:shd` fills | Font face and size |
| `w:spacing` per-character tracking | Headings and styles |
| `w:w` per-character width % | Tables |
| `mc:Fallback` duplicate copies | Floating text boxes (layout intact) |
| Redundant runs merged | Images and drawings |

## Typical results on a PDF-converted document

- File size: **80–90% smaller**
- `document.xml` uncompressed: **60–80% smaller**
- Run count: **85–90% fewer**
- Open/save time: from minutes → seconds

## The fix is not persistent across edits

If you edit the fixed file in Word and save, it will bloat again. Word re-serializes text inside floating text boxes with explicit per-character formatting on every save, because that text doesn't inherit from document paragraph styles. The fix can simply be re-run after any editing session.

## When to go further

If the document is still slow after this fix, the remaining bottleneck is almost certainly **floating text boxes** (`<wp:anchor>` elements). Word recalculates layout for every floating object. If the count is in the thousands, the only real fix is converting them to inline paragraphs — but this changes the visual layout significantly (positions become flow-based). Only do this if you're willing to reformat the document from scratch.

## Dependencies

```
pip install lxml
```
(`python-docx` is not needed — we work directly on the XML inside the ZIP.)
