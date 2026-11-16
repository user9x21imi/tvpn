"""Large tightly spaced dot lettering; portable pre-rasterized glyphs, no font install."""
import functools
import json
from pathlib import Path


@functools.lru_cache(maxsize=24)
def render(width, available_height):
    data = json.loads(Path(__file__).with_name('stoped-mask.json').read_text())
    source_width, source_height = data['width'], data['height']
    source = [format(int(row, 16), f'0{source_width}b') for row in data['rows']]
    # Account for terminal cells being approximately twice as tall as wide.
    width = max(1, width-2)
    height = max(1, round(width*source_height/source_width/2))
    if height > available_height:
        height = max(1, available_height)
        width = max(1, round(height*2*source_width/source_height))
    result = []
    for y in range(height):
        line = ''
        ya, yb = int(y/height*source_height), int((y+1)/height*source_height)
        for x in range(width):
            xa, xb = int(x/width*source_width), int((x+1)/width*source_width)
            pixels = [source[yy][xx] == '1' for yy in range(ya, max(ya+1,yb))
                      for xx in range(xa, max(xa+1,xb))]
            line += '●' if sum(pixels)/len(pixels) >= .35 else ' '
        result.append(line)
    return result
