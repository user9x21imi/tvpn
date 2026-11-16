"""Bold dot lettering with one visible terminal column between every letter."""
import functools
import json
from pathlib import Path


@functools.lru_cache(maxsize=24)
def render(width, available_height):
    data = json.loads(Path(__file__).with_name('stoped-mask.json').read_text())
    source_width, source_height = data['width'], data['height']
    source = [format(int(row, 16), f'0{source_width}b') for row in data['rows']]
    occupied = [any(row[x] == '1' for row in source) for x in range(source_width)]
    spans, start = [], None
    for x, ink in enumerate(occupied + [False]):
        if ink and start is None:
            start = x
        elif not ink and start is not None:
            spans.append((start, x))
            start = None
    # Reserve spacing AFTER rasterization: a one-pixel source gap otherwise
    # disappears when multiple source pixels shrink into one terminal cell.
    width = max(len(spans)*2-1, width-2)
    height = max(1, min(available_height, round(width*source_height/source_width/2)))
    budget = width-(len(spans)-1)
    ink_width = sum(right-left for left, right in spans)
    rendered = []
    consumed = 0
    for left, right in spans:
        next_consumed = consumed+right-left
        glyph_width = max(1, round(next_consumed/ink_width*budget)-round(consumed/ink_width*budget))
        consumed = next_consumed
        glyph = []
        for y in range(height):
            ya, yb = int(y/height*source_height), int((y+1)/height*source_height)
            line = ''
            for x in range(glyph_width):
                xa = left+int(x/glyph_width*(right-left))
                xb = left+int((x+1)/glyph_width*(right-left))
                pixels = [source[yy][xx] == '1' for yy in range(ya,max(ya+1,yb))
                          for xx in range(xa,max(xa+1,xb))]
                line += '●' if sum(pixels)/len(pixels) >= .35 else ' '
            glyph.append(line)
        visible = [x for x in range(glyph_width) if any(row[x] != ' ' for row in glyph)]
        if visible:
            glyph = [row[visible[0]:visible[-1]+1] for row in glyph]
        rendered.append(glyph)
    return [' '.join(glyph[y] for glyph in rendered) for y in range(height)]
