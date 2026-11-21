#!/usr/bin/env python3
"""Linux user installation; system setup is explicit and never connects a VPN."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import updater

ROOT=Path(__file__).resolve().parent


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--prefix',type=Path,default=Path.home()/'.local/share/riseup-vpn')
    p.add_argument('--no-launch',action='store_true')
    p.add_argument('--defer-system',action='store_true',help='Copy user files only; do not configure sudo/backend')
    a=p.parse_args(argv)
    try:
        import platform
        if sys.platform!='linux' or platform.machine()!='x86_64':raise updater.UpdateError('Linux x86_64 only')
        if os.geteuid()==0:raise updater.UpdateError('Run installer as the ordinary user, not root')
        try:import curses
        except ImportError as error:raise updater.UpdateError('Python curses is required') from error
        import shutil as which_tools
        required=['bash','curl','ip','flock']+([] if a.defer_system else ['sudo','visudo'])
        missing=[name for name in required if not which_tools.which(name)]
        if missing:raise updater.UpdateError('Missing Linux prerequisites: '+', '.join(missing))
        dest=a.prefix.expanduser().resolve()
        if dest==ROOT:raise updater.UpdateError('Source and destination must differ')
        dest.mkdir(parents=True,exist_ok=True)
        with updater.lifecycle(dest):
            updater.require_clean(dest)
            with tempfile.TemporaryDirectory(prefix='tvpn-install-') as tmp:
                stage=Path(tmp)/'source';stage.mkdir()
                excluded={'.git','.venv','__pycache__','settings','logs','tests','updates','build','dist'}
                for source in ROOT.rglob('*'):
                    rel=source.relative_to(ROOT)
                    if not source.is_file() or any(x in excluded or x.startswith('.') for x in rel.parts):continue
                    if source.name.endswith(updater.PRIVATE_SUFFIXES):continue
                    target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                def setup():
                    if not a.defer_system:
                        subprocess.run(['bash',str(stage/'install-passwordless.sh')],check=True)
                # Root installer checks the global backend lock itself before changing anything.
                updater.replace_files(dest,stage,finalize=setup)
        if not a.defer_system and dest==Path.home()/'.local/share/riseup-vpn':
            binary=Path.home()/'.local/bin/tvpn';binary.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dest/'bin/tvpn',binary);binary.chmod(0o755)
            desktop=Path.home()/'.local/share/applications/tvpn.desktop'
            desktop.parent.mkdir(parents=True,exist_ok=True)
            desktop.write_text('[Desktop Entry]\nType=Application\nName=TVPN\nTerminal=true\nIcon=network-vpn\nExec=bash "'+str(dest/'Riseup-Amsterdam-SteamDeck.sh')+'"\n',encoding='utf-8')
        print(json.dumps({'app_id':'tvpn','ok':True,'version':updater.local_version(dest),
                          'prefix':str(dest),'system_ready':not a.defer_system,'launched':False}))
        if not a.no_launch:
            if a.defer_system:raise updater.UpdateError('Deferred installation cannot launch VPN')
            os.execv('/bin/bash',['bash',str(dest/'Riseup-Amsterdam-SteamDeck.sh')])
        return 0
    except (updater.UpdateError,OSError,subprocess.CalledProcessError) as e:
        print(json.dumps({'app_id':'tvpn','ok':False,'error':str(e)},ensure_ascii=False));return 1


if __name__=='__main__':sys.exit(main())
