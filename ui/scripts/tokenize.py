#!/usr/bin/env python3
"""One-off migration helper: rewrite literal CSS values in <style> blocks to design tokens.

Maps each literal to the nearest step of the scale (ties round down), so small visual
shifts are intended consolidation. Run on a file, then review the diff by hand:

    python3 scripts/tokenize.py src/routes/memory/+page.svelte
"""
import re
import sys

SPACE = [(2, '0-5'), (4, '1'), (6, '1-5'), (8, '2'), (12, '3'), (16, '4'), (20, '5'), (24, '6'), (32, '8'), (40, '10'), (48, '12'), (64, '16')]
RADIUS = [(6, 'xs'), (8, 'sm'), (12, 'md'), (16, 'lg'), (20, 'xl'), (28, '2xl')]
FS = [(11, '2xs'), (12, 'xs'), (13, 'sm'), (14, 'md'), (16, 'base'), (18, 'lg'), (20, 'xl'), (24, '2xl'), (30, '3xl'), (36, '4xl')]
FW = {'400': 'regular', '500': 'medium', '550': 'medium', '600': 'semibold', '620': 'semibold', '650': 'bold'}
Z = {'1': 'raised', '2': 'raised', '5': 'nav', '20': 'popover', '30': 'tabbar', '60': 'palette', '61': 'palette', '70': 'sheet', '71': 'sheet', '80': 'fullscreen', '90': 'dialog', '91': 'dialog', '100': 'toast', '120': 'system'}


def nearest(px, scale):
    best = min(scale, key=lambda s: (abs(s[0] - px), s[0]))
    return best[1]


def px_of(tok):
    m = re.fullmatch(r'(-?)(\d*\.?\d+)(px|rem)', tok)
    if not m:
        return None
    v = float(m.group(2)) * (16 if m.group(3) == 'rem' else 1)
    return (m.group(1) == '-', v)


def space(tok):
    r = px_of(tok)
    if not r:
        return tok
    neg, v = r
    if v == 0 or v <= 1:
        return tok
    t = f'var(--space-{nearest(v, SPACE)})'
    return f'calc({t} * -1)' if neg else t


def dur(m):
    s = float(m.group(1)) * (1000 if m.group(2) == 's' else 1)
    if s <= 100:
        name = 'instant'
    elif s <= 165:
        name = 'fast'
    elif s <= 230:
        name = 'base'
    elif s <= 360:
        name = 'slow'
    elif s <= 650:
        name = 'slower'
    else:
        return m.group(0)
    return f'var(--dur-{name})'


def decl(prop, val):
    p = prop.strip()
    v = val.strip()
    if 'var(' in v and p not in ('transition', 'animation'):
        return val
    if p in ('padding', 'margin', 'gap', 'row-gap', 'column-gap') or re.fullmatch(r'(padding|margin)-(top|bottom|left|right|inline|block)(-start|-end)?', p):
        if any(x in v for x in ('calc', 'clamp', 'env', '%', 'em ', 'auto')) and not re.search(r'\d(px|rem)', v):
            return val
        parts = v.split()
        if any(('(' in x) for x in parts):
            return val
        return ' ' + ' '.join(space(x) for x in parts)
    if p == 'border-radius':
        if v == '50%':
            return ' var(--radius-round)'
        if v in ('999px', '9999px'):
            return ' var(--radius-pill)'
        r = px_of(v)
        if r:
            return f' var(--radius-{nearest(r[1], RADIUS)})'
        return val
    if p == 'font-size':
        r = px_of(v)
        if r and v.endswith('rem'):
            return f' var(--fs-{nearest(r[1], FS)})'
        return val
    if p == 'font-weight' and v in FW:
        return f' var(--fw-{FW[v]})'
    if p == 'z-index' and v in Z:
        return f' var(--z-{Z[v]})'
    if p in ('transition', 'animation', 'transition-duration'):
        return re.sub(r'(?<![\w.-])(\d*\.?\d+)(ms|s)\b', dur, val)
    return val


def migrate_css(css):
    return re.sub(r'(?m)^(\s*)([a-z-]+)\s*:([^;{}]+);', lambda m: f'{m.group(1)}{m.group(2)}:{decl(m.group(2), m.group(3))};', css)


def main(path):
    src = open(path).read()
    if path.endswith('.css'):
        out = migrate_css(src)
    else:
        out = re.sub(r'(<style[^>]*>)([\s\S]*?)(</style>)', lambda m: m.group(1) + migrate_css(m.group(2)) + m.group(3), src)
    open(path, 'w').write(out)


if __name__ == '__main__':
    for f in sys.argv[1:]:
        main(f)
