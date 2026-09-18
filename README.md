# glyphWeave

**Deterministic Unicode-to-glyph remapping for OpenType and web fonts.**

glyphWeave is a Python CLI for remapping existing font glyphs to alternate
Unicode code points without redrawing the glyph outlines.

It can decouple the text stored in a document or webpage from the glyphs
rendered on screen. When conflicting mappings cannot coexist in a single
OpenType `cmap`, glyphWeave distributes those mappings across multiple
deterministic WOFF2 font subsets and generates the supporting browser assets
needed to render them correctly.

## What it does

glyphWeave takes three primary inputs:

- **Visible text** — the text the reader should see.
- **Source font** — the font whose existing glyphs will be remapped.
- **Underlying text** — the Unicode character stream stored in the generated
  markup.

The program resolves the visible characters to glyphs in the source font,
reassigns those glyphs to the underlying Unicode stream, and generates as many
font subsets as necessary to resolve mapping collisions.

This makes it possible for visible text and underlying machine-readable text
to differ while the visible content remains actual rendered font glyphs rather
than a rasterized image.

## Example applications

Potential applications include:

- copyright or trademark notice transposition
- controlled clipboard text
- alternate machine-readable text beneath displayed copy
- experimental typography and character substitution
- deterministic Unicode/glyph mapping research
- web-font transformation and subsetting

For example, a protected passage can be rendered normally while the
underlying DOM or clipboard contains a copyright notice or other alternate
text.

## Font support

Input:

- `.woff2`
- `.woff`
- `.ttf`
- `.otf`

Generated font output is normalized to WOFF2.

## Text input support

Visible and underlying text can be supplied from:

- TXT
- Markdown
- RTF
- DOCX
- ODT
- HTML

## Generated output

A normal build produces:

- remapped WOFF2 font subsets
- `remap.css`
- `snippet.html`
- `index.html`
- `remap-guard.js`
- `mapping.json`

`mapping.json` provides an auditable record of the generated codepoint-to-glyph
mappings.

## How the mapping works

An OpenType `cmap` maps a Unicode code point to a glyph.

A single `cmap` cannot map the same Unicode code point to different glyphs at
different positions. When glyphWeave encounters that situation, it assigns
the conflicting mappings to separate font subsets and applies those subsets
to the corresponding spans in the generated markup.

The assignment is deterministic: identical inputs produce the same mapping
decisions and generated font structure.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Usage

```bash
python3 glyphweave.py \
  ait=visible.txt \
  bit=source-font.ttf \
  gif=underlying.txt \
  oof=output
```

Current CLI terminology:

- `ait=` — visible/alpha text
- `bit=` — source font
- `gif=` — underlying/gamma text
- `oof=` — output directory
- `fam=` — generated CSS font-family prefix
- `map=` — explicit codepoint/glyph mapping
- `nul=1` — omit the standalone `index.html`
- `lax=1` — permit characters absent from the source font to pass through

Run:

```bash
python3 glyphweave.py --help
```

for the complete grammar.

## Design characteristics

- deterministic mapping
- deterministic first-fit collision resolution
- OpenType `cmap` rewriting
- WOFF2 normalization
- font subsetting
- explicit codepoint-to-glyph mappings
- strict and passthrough input modes
- generated CSS/HTML/JavaScript integration
- auditable JSON mapping output

## Limitations

glyphWeave is not DRM and does not make displayed information impossible to
recover.

Rendered content can still be captured or reconstructed through methods such
as screenshots, OCR, font inspection, DOM analysis, or reverse engineering.

The project is better understood as a font-remapping and text-transposition
mechanism than as an absolute content-protection system.

## Development

glyphWeave was developed using an agent-assisted programming workflow with
iterative testing and refinement of the mapping behavior, font transformation,
browser integration, and generated output.

## License

No open-source license is currently granted. The source is published for
portfolio and technical-reference purposes.
