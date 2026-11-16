#!/usr/bin/env python3
"""Choose a native backend, keeping the same unprivileged terminal panel."""
import argparse
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent


def backend(platform=sys.platform):
    if platform == 'win32':
        return ROOT/'platforms/windows/backend.py'
    if platform == 'darwin':
        return ROOT/'platforms/macos/launcher.sh'
    if platform.startswith('linux'):
        return ROOT/'Riseup-Amsterdam-SteamDeck.sh'
    raise RuntimeError('Supported platforms: Linux, macOS, Windows')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--region',default='amsterdam')
    options=parser.parse_args()
    sys.argv=[str(ROOT/'riseup-panel.py'),str(backend()),'--region',options.region]
    runpy.run_path(str(ROOT/'riseup-panel.py'),run_name='__main__')
