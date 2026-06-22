"""Reflow hard-wrapped Markdown paragraphs in ADR files.

Lines broken at ~80 columns are joined back into continuous paragraph text.
Preserves: headings, horizontal rules, blank lines, fenced code blocks,
           list items (with their indented continuations), and table rows.
Bold metadata lines (**Key:** value) are kept separate from each other.
"""
import re
import sys
from pathlib import Path


LIST_RE = re.compile(r'^\s*(?:[-*+]|\d+[.)]) ')
# Matches bold metadata keys: **Status:** or **Context layer:** etc.
# The key is letters/spaces/punctuation (no *), followed by :** — e.g. **Depends on:**
METADATA_RE = re.compile(r'^\*\*[A-Za-z][^*]*:\*\*')


def reflow(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    buf: str | None = None        # accumulated line
    buf_is_list = False           # buffer holds a list item
    in_code = False

    def flush():
        nonlocal buf, buf_is_list
        if buf is not None:
            out.append(buf)
            buf = None
            buf_is_list = False

    for raw in lines:
        line = raw.rstrip()

        # ── code fence ──────────────────────────────────────────────────────
        if re.match(r'^\s*```', line):
            flush()
            in_code = not in_code
            out.append(line)
            continue

        if in_code:
            out.append(line)
            continue

        # ── blank line ───────────────────────────────────────────────────────
        if not line.strip():
            flush()
            out.append('')
            continue

        # ── heading ──────────────────────────────────────────────────────────
        if line.startswith('#'):
            flush()
            out.append(line)
            continue

        # ── horizontal rule ──────────────────────────────────────────────────
        stripped = line.strip()
        if re.match(r'^(-{3,}|={3,}|\*{3,})$', stripped):
            flush()
            out.append(line)
            continue

        # ── table row ────────────────────────────────────────────────────────
        if line.lstrip().startswith('|'):
            flush()
            out.append(line)
            continue

        # ── list item ────────────────────────────────────────────────────────
        if LIST_RE.match(line):
            if buf is not None:
                flush()
            buf = line
            buf_is_list = True
            continue

        # ── indented continuation of a list item ─────────────────────────────
        if re.match(r'^\s+', line) and buf_is_list:
            buf = buf + ' ' + line.strip()
            continue

        # ── bold metadata key-value line (**Status:** / **Context layer:** …) ─
        # Each such line is its own atom — flush whatever came before so that
        # consecutive metadata lines stay on separate lines.  This does NOT apply
        # to bold phrases mid-paragraph (e.g. "**circular** — …") which do not
        # match METADATA_RE and fall through to the paragraph logic below.
        if METADATA_RE.match(line):
            flush()
            buf = line
            buf_is_list = False
            continue

        # ── regular paragraph continuation or start ───────────────────────────
        if buf is not None and not buf_is_list:
            # If the buffer ends with a hyphen the word was split across lines;
            # join without a space so "higher-\nrank" → "higher-rank".
            sep = '' if buf.endswith('-') else ' '
            buf = buf + sep + line.strip()
        elif buf is not None and buf_is_list:
            # Non-indented line after a list item → new paragraph
            flush()
            buf = line
            buf_is_list = False
        else:
            buf = line
            buf_is_list = False

    flush()
    return '\n'.join(out) + '\n'


def process_file(path: Path) -> bool:
    original = path.read_text(encoding='utf-8')
    reflowed = reflow(original)
    if reflowed == original:
        return False
    path.write_text(reflowed, encoding='utf-8')
    return True


if __name__ == '__main__':
    adr_dir = Path(__file__).parent.parent / 'docs' / 'adr'
    files = sorted(adr_dir.glob('*.md'))
    changed = 0
    for f in files:
        if process_file(f):
            print(f'  reflowed  {f.name}')
            changed += 1
        else:
            print(f'  unchanged {f.name}')
    print(f'\n{changed}/{len(files)} files updated.')
