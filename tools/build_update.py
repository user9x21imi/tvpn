#!/usr/bin/env python3
"""Build a reproducible update bundle and its separately published manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from updater import PRIVATE_SUFFIXES,version_tuple


def build(root,version):
    root=Path(root)
    version_tuple(version)
    (root/'VERSION').write_text(version+'\n', encoding='utf-8')
    archive=root/'assets/updates'/f'{version}.zip'
    if archive.exists():raise ValueError('Эта версия уже собрана; увеличьте номер версии')
    archive.parent.mkdir(parents=True,exist_ok=True)
    excluded={'.git','.venv','__pycache__','tests','.update.lock'}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as bundle:
        for path in sorted(root.rglob('*')):
            relative=path.relative_to(root)
            if not path.is_file() or any(part in excluded for part in relative.parts):continue
            if relative.as_posix() in ('update.json','assets/update-bundle.zip') or relative.parts[:2]==('assets','updates'):continue
            if path.name.startswith('.') and path.name not in ('.gitignore',):continue
            if path.name.endswith(PRIVATE_SUFFIXES):continue
            info=zipfile.ZipInfo(relative.as_posix(),date_time=(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if path.stat().st_mode&0o111 else 0o100644)<<16
            bundle.writestr(info,path.read_bytes())
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest={'version':version,'url':f'https://raw.githubusercontent.com/user9x21imi/riseup-vpn-panel/main/assets/updates/{version}.zip',
              'sha256':digest,'size':archive.stat().st_size}
    (root/'update.json').write_text(json.dumps(manifest,indent=2)+'\n', encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',required=True)
    args=parser.parse_args()
    print(json.dumps(build(ROOT,args.version),indent=2))
