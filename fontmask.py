#!/usr/bin/env python3
"""
fontmask.py — standalone cmap-remapping CLI.

    Screen shows ALPHA text. DOM / clipboard / scrapers get GAMMA text.

GRAMMAR
    python3 fontmask.py ait=<file> bit=<file> gif=<file> [oof=<dir>] [...]

    ait=   alpha-input : text       what the READER SEES (the poem / body copy)
                                    formats: .txt .md .rtf .docx .odt .html/.htm
    bit=   beta-input  : typeface   source font supplying the display glyphs
                                    formats: .woff2 .woff .ttf .otf
                                    (non-woff2 is converted to woff2 on output)
    gif=   gamma-input : file       what the DOM CONTAINS (warning / notice text)
                                    same formats as ait= ; content is yours to
                                    author — nothing is baked into this program
    oof=   optional-output : dir    where the bundle is written
                                    default: <ait-dir>/<ait-stem>-remap/

    optional extras
    fam=   css font-family prefix   default: GS
    map=   single mapping           CP:GLYPHNAME or CHAR:CHAR, repeatable
                                    e.g. map=U+2122:ht.monogram  map=™:☃
    nul=1  suppress index.html      emit only shards/css/js/snippet/manifest
    lax=1  arbitrary-input mode     characters ait= needs but bit= lacks pass
                                    through un-remapped (rendered by the page
                                    fallback font, present VERBATIM in the DOM
                                    — each one is reported and recorded in
                                    mapping.json). Default is strict: error.
                                    Also tolerates non-UTF-8 bytes in text
                                    files via replacement characters.

OUTPUT BUNDLE
    <bit-stem>-s0.woff2 ... -sN.woff2   typeface shards
    remap.css                           @font-face + shard classes
    snippet.html                        drop-in markup (Hugo partial friendly)
    index.html                          self-contained display page
    remap-guard.js                      font-load gate + clipboard notice
    mapping.json                        auditable codepoint→glyph manifest

WHY SHARDS
    A cmap maps one codepoint to exactly one glyph. When the gamma text
    repeats a character but the alpha text needs different glyphs at those
    positions, no single font can express it. Positions are split across
    shards; the snippet spans each run with its shard's class.

DETERMINISM CONTRACT
    Strictly synchronous. No randomness. Identical inputs produce
    byte-identical outputs (font timestamps are not regenerated; every
    ordered choice is marked with a DETERMINISTIC comment).

Requires: fonttools, brotli        pip install fonttools brotli
"""

import html as html_mod
import io
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
    from fontTools import subset
except ImportError:
    sys.exit("fontMask: missing dependency — run: pip install fonttools brotli")


# ==========================================================================
# text extraction (ait= / gif=)  — stdlib only, one handler per format
# ==========================================================================

def _txt_to_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = []
    for p in root.iter():
        if p.tag.endswith("}p"):
            buf = []
            for node in p.iter():
                if node.tag.endswith("}t"):
                    buf.append(node.text or "")
                elif node.tag.endswith("}br") or node.tag.endswith("}cr"):
                    buf.append("\n")
            paras.append("".join(buf))
    return "\n".join(paras)


def _odt_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    paras = []
    for p in root.iter():
        tag = p.tag.rsplit("}", 1)[-1]
        if tag in ("p", "h"):
            buf = [p.text or ""]
            for node in p.iter():
                t = node.tag.rsplit("}", 1)[-1]
                if t == "line-break":
                    buf.append("\n")
                elif t == "tab":
                    buf.append("\t")
                elif t == "s":
                    buf.append(" " * int(node.get(
                        "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}c", "1")))
                if node is not p and node.text:
                    buf.append(node.text)
                if node.tail:
                    buf.append(node.tail)
            paras.append("".join(buf))
    return "\n".join(paras)


class _HTMLText(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
              "tr", "section", "article", "blockquote", "pre"}
    _SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def _html_to_text(path: Path) -> str:
    p = _HTMLText()
    p.feed(path.read_text(encoding="utf-8-sig"))
    text = "".join(p.out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


_RTF_MAP = {"par": "\n", "line": "\n", "tab": "\t", "emdash": "\u2014",
            "endash": "\u2013", "lquote": "\u2018", "rquote": "\u2019",
            "ldblquote": "\u201C", "rdblquote": "\u201D", "bullet": "\u2022",
            "~": "\u00A0", "-": "", "_": "\u2011", "\n": "\n", "\r": "\n"}
_RTF_DESTINATIONS = {"fonttbl", "colortbl", "stylesheet", "info", "pict",
                     "header", "footer", "generator", "themedata",
                     "colorschememapping", "latentstyles", "datastore",
                     "xmlnstbl", "listtable", "listoverridetable"}
_RTF_TOKEN = re.compile(
    r"\\([a-z]{1,32})(-?\d{1,10})?[ ]?"   # control word
    r"|\\'([0-9a-fA-F]{2})"               # hex escape
    r"|\\([^a-z])"                        # control symbol
    r"|([{}])"                            # group delimiters
    r"|([^\\{}]+)", re.DOTALL)            # plain text


def _rtf_to_text(path: Path) -> str:
    data = path.read_text(encoding="latin-1")
    out, stack = [], []
    skip_group, ucskip, pending_skip = 0, 1, 0
    for m in _RTF_TOKEN.finditer(data):
        word, num, hexb, sym, brace, text = m.groups()
        if brace == "{":
            stack.append((skip_group, ucskip))
            continue
        if brace == "}":
            if stack:
                skip_group, ucskip = stack.pop()
            continue
        if sym is not None:
            if sym == "*":                # \* — unknown destination: skip group
                skip_group = 1
            elif not skip_group and sym in _RTF_MAP:
                out.append(_RTF_MAP[sym])
            elif not skip_group and sym in ("\\", "{", "}"):
                out.append(sym)
            continue
        if word is not None:
            if word in _RTF_DESTINATIONS:
                skip_group = 1
            elif word == "uc":
                ucskip = int(num or 1)
            elif word == "u":
                if not skip_group:
                    cp = int(num)
                    out.append(chr(cp + 65536 if cp < 0 else cp))
                pending_skip = ucskip
            elif not skip_group and word in _RTF_MAP:
                out.append(_RTF_MAP[word])
            continue
        if hexb is not None:
            if pending_skip:
                pending_skip -= 1
            elif not skip_group:
                out.append(bytes([int(hexb, 16)]).decode("cp1252", "replace"))
            continue
        if text is not None and not skip_group:
            t = text.replace("\r", "").replace("\n", "")
            if pending_skip:
                take = min(pending_skip, len(t))
                t, pending_skip = t[take:], pending_skip - take
            out.append(t)
    return "".join(out)


_EXTRACTORS = {".txt": _txt_to_text, ".md": _txt_to_text, ".text": _txt_to_text,
               ".rtf": _rtf_to_text, ".docx": _docx_to_text,
               ".odt": _odt_to_text, ".html": _html_to_text, ".htm": _html_to_text}


def extract_text(path: Path, lax: bool = False) -> str:
    ext = path.suffix.lower()
    fn = _EXTRACTORS.get(ext)
    if fn is None:
        # DETERMINISTIC: unknown extensions are read as plain UTF-8 text,
        # never guessed at by content sniffing.
        sys.stderr.write(f"fontMask: note — unknown extension '{ext}', "
                         f"reading {path.name} as plain text\n")
        fn = _txt_to_text
    try:
        return fn(path)
    except UnicodeDecodeError:
        if lax and fn is _txt_to_text:
            # DETERMINISTIC: invalid byte sequences become U+FFFD, one per
            # undecodable byte, per Python's stable 'replace' handler.
            sys.stderr.write(f"fontMask: note — {path.name} is not valid "
                             f"UTF-8; undecodable bytes replaced (lax=1)\n")
            return path.read_text(encoding="utf-8", errors="replace")
        sys.exit(f"fontMask: {path.name} is not valid UTF-8 text "
                 f"(pass lax=1 to substitute undecodable bytes)")


# ==========================================================================
# core: tokens, shard assignment
# ==========================================================================

def parse_codepoint(token: str) -> int:
    t = token.strip()
    if len(t) == 1:
        return ord(t)
    tl = t.lower()
    if tl.startswith("u+") or tl.startswith("0x"):
        return int(t[2:], 16)
    return int(t, 16)


def build_tokens(gamma: str, alpha: str):
    """Position-walk the ALPHA text; whitespace passes through, every other
    position consumes the next non-whitespace GAMMA character (cycled)."""
    # DETERMINISTIC: gamma stream = gamma text minus whitespace, consumed
    # left-to-right, cycled with modulo. No shuffling, no hashing.
    stream = [c for c in gamma if not c.isspace()]
    if not stream:
        raise SystemExit("fontMask: error — gif= text is empty after "
                         "stripping whitespace; the warning content must be provided")
    tokens, k = [], 0
    for ch in alpha:
        if ch.isspace():
            tokens.append(("ws", ch))
        else:
            tokens.append(("map", ord(stream[k % len(stream)]), ch))
            k += 1
    return tokens


def assign_shards(token_lists, char_to_glyph, glyph_order, lax=False):
    shards, blocks_out, missing = [], [], set()
    passthrough = {}                      # display char -> occurrence count
    glyph_set = set(glyph_order)
    for block_id, tokens in token_lists:
        placed = []
        for tok in tokens:
            if tok[0] == "ws":
                placed.append(tok)
                continue
            _, gcp, disp = tok
            if len(disp) == 1:
                gname = char_to_glyph.get(ord(disp))
                if gname is None:
                    if lax:
                        # DETERMINISTIC: an uncovered character is emitted
                        # literally at its own position; it consumes no gamma
                        # stream character and joins no shard.
                        passthrough[disp] = passthrough.get(disp, 0) + 1
                        placed.append(("lit", disp))
                    else:
                        missing.add(disp)
                    continue
            else:
                gname = disp              # explicit map= glyph names are a
                if gname not in glyph_set:  # user contract: always fatal
                    missing.add(gname)
                    continue
            # DETERMINISTIC: first-fit shard scan in creation order; a new
            # shard is appended only when no existing shard can hold the pair.
            for si, shard in enumerate(shards):
                if shard.get(gcp) in (None, gname):
                    shard[gcp] = gname
                    placed.append(("map", si, gcp))
                    break
            else:
                shards.append({gcp: gname})
                placed.append(("map", len(shards) - 1, gcp))
        runs, cur, buf = [], None, []

        def flush():
            if cur is not None and buf:
                runs.append(("lit", "".join(buf)) if cur == "lit"
                            else ("run", cur, "".join(buf)))

        for p in placed:
            if p[0] == "ws":
                (buf.append(p[1]) if cur is not None else runs.append(("ws", p[1])))
                continue
            if p[0] == "lit":
                key, ch = "lit", p[1]
            else:
                _, si, cp = p
                key, ch = si, chr(cp)
            if key != cur:
                flush()
                cur, buf = key, []
            buf.append(ch)
        flush()
        blocks_out.append((block_id, runs))
    return shards, blocks_out, sorted(missing), passthrough


# ==========================================================================
# core: shard font generation (any input flavor -> woff2)
# ==========================================================================

def make_shard_font(font_bytes: bytes, mapping: dict, out_path: Path):
    font = TTFont(io.BytesIO(font_bytes), recalcTimestamp=False)
    font.recalcTimestamp = False          # DETERMINISTIC: keep source
    src_cmap = font.getBestCmap()         # 'modified' date; byte-reproducible

    full = dict(mapping)
    if 0x20 not in full and 0x20 in src_cmap:
        full[0x20] = src_cmap[0x20]       # pass-through whitespace renders

    bmp = {cp: g for cp, g in full.items() if cp <= 0xFFFF}
    supp = {cp: g for cp, g in full.items() if cp > 0xFFFF}
    tables = []
    st4 = CmapSubtable.getSubtableClass(4)(4)
    st4.platformID, st4.platEncID, st4.language = 3, 1, 0
    st4.cmap = bmp
    tables.append(st4)
    if supp:
        st12 = CmapSubtable.getSubtableClass(12)(12)
        st12.platformID, st12.platEncID, st12.language = 3, 10, 0
        st12.cmap = {**bmp, **supp}
        tables.append(st12)
    font["cmap"].tables = tables

    opts = subset.Options()
    opts.layout_features = ["*"]          # kerning is glyph-level: still correct
    opts.notdef_outline = True
    opts.glyph_names = True               # shipped shard auditable vs manifest
    ss = subset.Subsetter(opts)
    ss.populate(unicodes=sorted(full.keys()))   # DETERMINISTIC: sorted
    ss.subset(font)

    font.flavor = "woff2"                 # woff/ttf/otf input all normalize here
    font.save(out_path)


# ==========================================================================
# output bundle
# ==========================================================================

GUARD_JS = """\
// remap-guard.js — companion to fontMask woff2 shards.
// 1. Keeps protected blocks hidden until shards load, so the gamma (DOM)
//    layer is never flashed on a slow or blocked font fetch.
// 2. Replaces the clipboard payload with a clean notice on copy — the shard
//    remap already garbles copies at the DOM level; this is the readable
//    version for humans. Scrapers with JS off still only reach gamma text.
(function () {
  "use strict";
  var NOTICE = document.documentElement.getAttribute("data-gs-notice") ||
    "This text is protected. Reproduction without permission is prohibited.";
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () {
      document.documentElement.classList.add("gs-fonts-ready");
    });
    setTimeout(function () {           // failsafe: never hide content forever
      document.documentElement.classList.add("gs-fonts-ready");
    }, 4000);
  } else {
    document.documentElement.classList.add("gs-fonts-ready");
  }
  function onCopy(e) {
    var sel = document.getSelection();
    if (!sel || sel.isCollapsed) return;
    var node = sel.anchorNode;
    while (node && node.nodeType !== 1) node = node.parentNode;
    if (node && node.closest && node.closest(".gs-protect")) {
      e.clipboardData.setData("text/plain", NOTICE);
      e.preventDefault();
    }
  }
  document.addEventListener("copy", onCopy);
  document.addEventListener("cut", onCopy);
})();
"""

INDEX_TEMPLATE = """\
<!doctype html>
<html lang="en" data-gs-notice="{notice}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fontMask</title>
<link rel="stylesheet" href="remap.css">
{preloads}
<style>body{{max-width:42rem;margin:4rem auto;padding:0 1.5rem;font-size:1.4rem;line-height:1.7}}
.gs-note{{font:0.8rem/1.5 system-ui;color:#888;margin-bottom:2.5rem}}</style>
</head>
<body>
<p class="gs-note">Select and copy the text below, then paste it anywhere —
the clipboard receives the gamma layer, not what you see.</p>
{body}
<script src="remap-guard.js"></script>
</body>
</html>
"""


def render_runs(runs):
    parts = []
    for r in runs:
        if r[0] == "ws":
            parts.append(html_mod.escape(r[1]))
        elif r[0] == "lit":
            parts.append(f'<span class="gs-lit">{html_mod.escape(r[1])}</span>')
        else:
            parts.append(f'<span class="gs-s{r[1]}">{html_mod.escape(r[2])}</span>')
    return "".join(parts)


def write_bundle(out_dir, shards, blocks, family, shard_stem, notice,
                 with_index, passthrough):
    out_dir.mkdir(parents=True, exist_ok=True)

    css = []
    for si in range(len(shards)):
        css.append(
            f'@font-face {{\n'
            f'  font-family: "{family} S{si}";\n'
            f'  src: url("{shard_stem}-s{si}.woff2") format("woff2");\n'
            f'  font-display: block; /* never flash the gamma layer */\n'
            f'}}')
    css.append(".gs-protect { visibility: hidden; white-space: pre-wrap; }")
    css.append(".gs-fonts-ready .gs-protect { visibility: visible; }")
    for si in range(len(shards)):
        css.append(f'.gs-s{si} {{ font-family: "{family} S{si}"; }}')
    css.append(".gs-lit { font-family: inherit; }"
               " /* lax passthrough: char absent from bit=,"
               " rendered by page fallback, VERBATIM in DOM */")
    (out_dir / "remap.css").write_text("\n".join(css) + "\n")

    snippets = [
        f'<!-- fontMask block: {bid} -->\n'
        f'<div class="gs-protect" translate="no">{render_runs(runs)}</div>'
        for bid, runs in blocks
    ]
    (out_dir / "snippet.html").write_text("\n\n".join(snippets) + "\n")
    (out_dir / "remap-guard.js").write_text(GUARD_JS)

    manifest = {
        "shards": [{f"U+{cp:04X}": g for cp, g in sorted(s.items())} for s in shards],
        "files": [f"{shard_stem}-s{si}.woff2" for si in range(len(shards))],
        # DETERMINISTIC: sorted by codepoint; verbatim-in-DOM characters
        "passthrough": {f"U+{ord(c):04X}": n
                        for c, n in sorted(passthrough.items())},
    }
    (out_dir / "mapping.json").write_text(json.dumps(manifest, indent=2,
                                                     sort_keys=False) + "\n")
    if with_index:
        preloads = "\n".join(
            f'<link rel="preload" href="{shard_stem}-s{si}.woff2" '
            f'as="font" type="font/woff2" crossorigin>'
            for si in range(len(shards)))
        body = "\n\n".join(
            f'<div class="gs-protect" translate="no">{render_runs(runs)}</div>'
            for _, runs in blocks)
        (out_dir / "index.html").write_text(INDEX_TEMPLATE.format(
            notice=html_mod.escape(notice, quote=True),
            preloads=preloads, body=body))


# ==========================================================================
# cli
# ==========================================================================

def parse_args(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)
    args = {"map": []}
    valid = {"ait", "bit", "gif", "oof", "fam", "map", "nul", "lax"}
    for tok in argv:
        key, sep, val = tok.partition("=")
        if not sep or key not in valid:
            sys.exit(f"fontMask: unrecognized argument '{tok}'\n"
                     f"valid keys: ait= bit= gif= oof= fam= map= nul= lax=  "
                     f"(run with -h for the full grammar)")
        if key == "map":
            args["map"].append(val)
        else:
            args[key] = val
    for req in ("ait", "bit", "gif"):
        if req not in args:
            sys.exit(f"fontMask: missing required argument '{req}='  "
                     f"(run with -h for the full grammar)")
    return args


def main(argv):
    a = parse_args(argv)
    ait, bit, gif = Path(a["ait"]), Path(a["bit"]), Path(a["gif"])
    for p, k in ((ait, "ait"), (bit, "bit"), (gif, "gif")):
        if not p.is_file():
            sys.exit(f"fontMask: {k}= file not found: {p}")
    if bit.suffix.lower() not in (".woff2", ".woff", ".ttf", ".otf"):
        sys.exit(f"fontMask: bit= must be woff2/woff/ttf/otf, got '{bit.suffix}'")

    # DETERMINISTIC: default output directory is derived from ait= only —
    # <ait-dir>/<ait-stem>-remap/ — never from cwd or environment.
    out_dir = Path(a["oof"]) if "oof" in a else ait.parent / f"{ait.stem}-remap"
    family = a.get("fam", "GS")
    lax = a.get("lax") == "1"

    alpha = extract_text(ait, lax).rstrip("\n")
    gamma = extract_text(gif, lax).strip("\n")
    if not alpha.strip():
        sys.exit(f"fontMask: ait= yielded no text from {ait.name}")

    font_bytes = bit.read_bytes()
    probe = TTFont(io.BytesIO(font_bytes), recalcTimestamp=False)
    char_to_glyph = probe.getBestCmap()
    glyph_order = probe.getGlyphOrder()

    token_lists = [("ait", build_tokens(gamma, alpha))]
    # DETERMINISTIC: map= blocks follow in command-line order.
    for i, spec in enumerate(a["map"]):
        under, _, disp = spec.partition(":")
        token_lists.append((f"map{i}", [("map", parse_codepoint(under), disp.strip())]))

    shards, blocks, missing, passthrough = assign_shards(
        token_lists, char_to_glyph, glyph_order, lax=lax)
    if missing:
        sys.exit(f"fontMask: not present in {bit.name}: {missing}\n"
                 f"(every character of ait= must have a glyph in bit= — "
                 f"pass lax=1 to let uncovered characters through un-remapped)")

    out_dir.mkdir(parents=True, exist_ok=True)
    shard_stem = bit.stem.replace(".", "-")
    for si, mapping in enumerate(shards):
        make_shard_font(font_bytes, mapping, out_dir / f"{shard_stem}-s{si}.woff2")

    notice = " ".join(gamma.split())
    if len(notice) > 300:
        notice = notice[:297] + "..."
    write_bundle(out_dir, shards, blocks, family, shard_stem, notice,
                 with_index=a.get("nul") != "1", passthrough=passthrough)

    total = sum(len(s) for s in shards)
    print(f"fontMask: {len(shards)} shard(s), {total} remapped codepoints -> {out_dir}/")
    for si, s in enumerate(shards):
        f = out_dir / f"{shard_stem}-s{si}.woff2"
        print(f"  {f.name:<28} {len(s):>4} mappings  {f.stat().st_size:>7,} bytes")
    if passthrough:
        chars = " ".join(f"{c}×{n}" for c, n in sorted(passthrough.items()))
        print(f"  lax passthrough: {sum(passthrough.values())} occurrence(s) "
              f"NOT remapped — verbatim in DOM: {chars}")


if __name__ == "__main__":
    main(sys.argv[1:])
