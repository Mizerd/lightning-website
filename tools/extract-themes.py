#!/usr/bin/env python3
"""Read all eleven palettes out of the CLIENT's qml/AppTheme.qml.

    python3 tools/extract-themes.py [path/to/lightning]   # writes public/themes.json

WHY THIS EXISTS. The site has always claimed its colours are "read from
qml/AppTheme.qml", and that was true of exactly two of them -- Indigo Night's
surfaces and the Storm bolt -- hand-copied. The eleven swatches were a hand-kept
table of accent colours and nothing else, and the README says in as many words
that "if a palette changes there it has to be changed here too".

Now the whole palette of every theme is extracted, so clicking a swatch can
recolour the page the way the application actually looks rather than the way
somebody remembered it.

THE TWO REPOSITORIES STILL CANNOT SEE EACH OTHER AT BUILD TIME. This script is
run by hand, with a checkout of the client present, and its output is committed
as `public/themes.json`. That is the same arrangement the swatch table had; what
changes is that the copy is now generated and complete instead of typed and
partial. Re-run it when a palette moves.

HOW IT PARSES. AppTheme.qml defines colour literals as
`readonly property color _stoBolt: "#FFD447"` and then each theme as
`readonly property var _storm: ({ background: _stoDeep, ... })`. So: build a
symbol table of the literals, then resolve each theme's role -> symbol mapping
through it. `Qt.alpha(sym, a)` is resolved to rgba(). Anything unresolved is
reported rather than guessed at -- a silently missing role would show up as a
wrong colour on a live page.
"""
import json
import os
import re
import sys

# id -> the name the site shows, in the order AppTheme.qml documents them.
THEME_IDS = [
    (9,  "Indigo Night"), (8,  "Moss Light"),   (10, "Deep Teal"),
    (11, "Storm"),        (1,  "Lightning Light"), (2, "Lightning Dark"),
    (3,  "Graphite"),     (4,  "Midnight"),     (5,  "Nordic"),
    (6,  "Purple Dusk"),  (7,  "Warm"),
]

# The QML object each id resolves to, from rawPaletteForTheme().
THEME_VAR = {
    1: "_light", 2: "_dark", 3: "_graphite", 4: "_midnight", 5: "_nord",
    6: "_purple", 7: "_warm", 8: "_moss", 9: "_indigo", 10: "_teal",
    11: "_storm",
}

# The site's token <- the application's role. Only what the page paints with.
# The application stacks three grounds -- background (darkest, the timeline),
# sidebar (the room list), surface (cards) -- and the page borrows the same
# order, so a theme reads on the web the way it reads in the client rather than
# being re-invented for it.
ROLE_MAP = {
    "page":     "background",
    "raised":   "sidebar",
    "elevated": "surface",
    "hairline": "border",
    "border":   "borderStrong",
    "text":     "textPrimary",
    "text-2":   "textSecondary",
    "text-3":   "textMuted",
    "accent":   "accent",
    "link":     "link",
}


def colour_literals(src):
    """Every `readonly property color _name: "#rrggbb"` in the file."""
    out = {}
    for m in re.finditer(r'readonly\s+property\s+color\s+(_\w+)\s*:\s*"(#[0-9A-Fa-f]{6,8})"', src):
        out[m.group(1)] = m.group(2)
    return out


def palette_body(src, var):
    """The `({ ... })` body of one theme's `readonly property var _x`."""
    m = re.search(r'readonly\s+property\s+var\s+' + re.escape(var) + r'\s*:\s*\(\{', src)
    if not m:
        return None
    i = m.end()
    depth = 1
    while i < len(src) and depth:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    return src[m.end():i - 1]


def resolve(expr, literals):
    """A role's value: a literal, a symbol, or Qt.alpha(symbol, a)."""
    expr = expr.strip()
    m = re.fullmatch(r'Qt\.alpha\(\s*(\w+)\s*,\s*([0-9.]+)\s*\)', expr)
    if m:
        base = literals.get(m.group(1))
        if not base:
            return None
        r, g, b = (int(base[k:k + 2], 16) for k in (1, 3, 5))
        return "rgba(%d,%d,%d,%s)" % (r, g, b, m.group(2))
    if re.fullmatch(r'"#[0-9A-Fa-f]{6,8}"', expr):
        return expr.strip('"')
    return literals.get(expr)


def strip_comments(body):
    """Drop `//` comments.

    The palette bodies carry prose, and prose carries colons -- "measured
    1.00:1" parsed as a role and swallowed the `background:` that followed it
    on the next line. Quotes are respected even though no palette currently
    holds a string with `//` in it, because the next one might.
    """
    out = []
    for line in body.splitlines():
        quoted, cut = False, len(line)
        i = 0
        while i < len(line) - 1:
            if line[i] == '"':
                quoted = not quoted
            elif not quoted and line[i] == '/' and line[i + 1] == '/':
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def roles_of(body, literals):
    """role -> resolved colour, for one palette body."""
    body = strip_comments(body)
    out = {}
    # Split on commas that are not inside parentheses, so Qt.alpha(a, b) holds.
    depth, cur, parts = 0, "", []
    for ch in body:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    for part in parts:
        if ':' not in part:
            continue
        role, _, expr = part.partition(':')
        value = resolve(expr, literals)
        if value:
            out[role.strip()] = value
    return out


def main():
    client = sys.argv[1] if len(sys.argv) > 1 else "/home/roksme/git/lightning"
    theme_qml = os.path.join(client, "qml", "AppTheme.qml")
    if not os.path.exists(theme_qml):
        sys.exit("extract-themes: no AppTheme.qml at %s" % theme_qml)
    src = open(theme_qml, encoding="utf-8").read()
    literals = colour_literals(src)
    print("colour literals: %d" % len(literals))

    themes, problems = [], []
    for tid, name in THEME_IDS:
        body = palette_body(src, THEME_VAR[tid])
        if body is None:
            problems.append("%s: no %s object" % (name, THEME_VAR[tid]))
            continue
        roles = roles_of(body, literals)
        tokens = {}
        for token, role in ROLE_MAP.items():
            if role in roles:
                tokens[token] = roles[role]
            elif role == "link" and "accent" in roles:
                tokens[token] = roles["accent"]      # AppTheme's own fallback
            elif role in ("sidebar", "surface") and "background" in roles:
                tokens[token] = roles["background"]
            else:
                problems.append("%s: no %s" % (name, role))
        # `dark` drives the page's own light/dark decisions, and AppTheme
        # computes it by id, not by luminance, for every preset.
        tokens["dark"] = tid not in (1, 7, 8)
        themes.append({"id": tid, "name": name, "tokens": tokens})

    if problems:
        # Never emit a partial palette: a missing role renders as a wrong
        # colour on a live page and nothing would say so.
        for p in problems:
            print("  UNRESOLVED %s" % p, file=sys.stderr)
        sys.exit("extract-themes: %d role(s) unresolved" % len(problems))

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "public", "themes.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"source": "qml/AppTheme.qml", "themes": themes}, fh,
                  indent=2, ensure_ascii=False)
        fh.write("\n")
    print("wrote %s -- %d themes, %d tokens each"
          % (out, len(themes), len(ROLE_MAP) + 1))


if __name__ == "__main__":
    main()
