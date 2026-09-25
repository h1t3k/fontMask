# fontMask text-transposition example

This fixture demonstrates fontMask's core Unicode-to-glyph remapping behavior.

The intended visible text is:

    the kiln keeps every ledger

The alternate underlying text is:

    PROPRIETARY WORK DO NOT COPY

fontMask resolves the visible characters to glyph outlines in the supplied
font, then remaps those glyphs onto a Unicode stream derived from the
underlying text.

Where the same underlying code point would need to display different glyphs
at different positions, fontMask distributes the conflicting mappings
across multiple WOFF2 font subsets.

## Files

- `visible.txt` — text intended for the reader
- `underlying.txt` — alternate Unicode/notice text
- `DejaVuSans.ttf` — font fixture used by this example
- `DEJAVU-LICENSE.txt` — upstream license for the font fixture
- `generated/` — output produced by fontMask

## Reproduce the example

Run this from the repository root:

    python3 fontmask.py \
      ait=examples/text-transposition/visible.txt \
      bit=examples/text-transposition/DejaVuSans.ttf \
      gif=examples/text-transposition/underlying.txt \
      oof=examples/text-transposition/generated

Then open:

    examples/text-transposition/generated/index.html

## Generated bundle

The generated directory contains:

- WOFF2 remapped font subsets
- `remap.css`
- `snippet.html`
- `index.html`
- `remap-guard.js`
- `mapping.json`

`mapping.json` exposes the resulting codepoint-to-glyph assignments so the
transformation can be inspected rather than treated as a black box.

This mechanism is a text-transposition and font-remapping technique. It is
not intended to make displayed information impossible to recover.
