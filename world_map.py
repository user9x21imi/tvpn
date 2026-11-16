#!/usr/bin/env python3
"""Rasterize Natural Earth country polygons into terminal Braille cells, offline."""
import functools
import json
import math
from pathlib import Path

COUNTRIES = {'NL': 'NLD', 'FR': 'FRA', 'CA': 'CAN', 'US': 'USA'}
# Earth in equirectangular projection, omit Antarctica to use the screen well.
NORTH, SOUTH = 84, -60


@functools.lru_cache(maxsize=1)
def land():
    return json.loads(Path(__file__).with_name('world-land.json').read_text())


def position(lon, lat, width, height):
    return (min(width-1, max(0, int((lon+180)/360*width))),
            min(height-1, max(0, int((NORTH-lat)/(NORTH-SOUTH)*height))))


@functools.lru_cache(maxsize=24)
def render(width, height, country):
    """Return (character, is_selected_country) for every terminal cell."""
    columns, rows = width*2, height*4
    pixels = [bytearray(columns) for _ in range(rows)]
    selected = COUNTRIES.get(country, '')
    for feature in land():
        if feature['id'] == 'ATA':
            continue
        polygons = feature['coordinates']
        if feature['type'] == 'Polygon':
            polygons = [polygons]
        ink = 2 if feature['id'] == selected else 1
        for rings in polygons:
            # Even/odd fill includes lakes and polygon holes.
            edges = [(a, b) for ring in rings for a, b in zip(ring, ring[1:]) if a[1] != b[1]]
            if not edges:
                continue
            low = min(p[1] for ring in rings for p in ring)
            high = max(p[1] for ring in rings for p in ring)
            for y in range(rows):
                latitude = NORTH - (y+.5)/rows*(NORTH-SOUTH)
                if not low <= latitude <= high:
                    continue
                crossings = sorted(a[0]+(latitude-a[1])*(b[0]-a[0])/(b[1]-a[1])
                                   for a, b in edges if (a[1] > latitude) != (b[1] > latitude))
                for west, east in zip(crossings[::2], crossings[1::2]):
                    start = max(0, math.ceil((west+180)/360*columns-.5))
                    end = min(columns, math.ceil((east+180)/360*columns-.5))
                    for x in range(start, end):
                        pixels[y][x] = max(ink, pixels[y][x])
    result = []
    # Unicode Braille bit order: left 1,2,3,7; right 4,5,6,8.
    bits = ((0, 1, 2, 6), (3, 4, 5, 7))
    for y in range(height):
        row = []
        for x in range(width):
            mask, selected_mask = 0, 0
            for dx in range(2):
                for dy in range(4):
                    pixel = pixels[y*4+dy][x*2+dx]
                    if pixel:
                        mask |= 1 << bits[dx][dy]
                        if pixel == 2:
                            selected_mask |= 1 << bits[dx][dy]
            # A terminal cell has one foreground colour. Never paint neighbouring
            # countries' dots merely because this cell also contains the selection.
            visible = selected_mask or mask
            row.append((chr(0x2800+visible) if visible else ' ', bool(selected_mask)))
        result.append(row)
    return result


if __name__ == '__main__':
    for row in render(100, 24, 'NL'):
        print(''.join(char for char, _ in row))
