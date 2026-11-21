#!/usr/bin/env python3
"""Machine entry point for ttools. Never starts a VPN or a terminal UI."""
import argparse
import dataclasses
import json
import os
from pathlib import Path
import signal
import sys
import time
import updater

ROOT=Path(__file__).resolve().parent


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('version','check-update','status','doctor'):sub.add_parser(name)
    apply=sub.add_parser('update');apply.add_argument('--manifest',type=Path)
    stop=sub.add_parser('stop');stop.add_argument('--timeout',type=float,default=30)
    args=parser.parse_args(argv);root=args.root.resolve()
    try:
        if args.command=='version':result={'version':updater.local_version(root)}
        elif args.command=='check-update':
            found=updater.check(root)
            result={'version':updater.local_version(root),'available':dataclasses.asdict(found) if found else None}
        elif args.command=='status':result=updater.lifecycle_status(root)
        elif args.command=='doctor':
            import platform,shutil
            result={'platform':sys.platform,'architecture':platform.machine(),'version':updater.local_version(root),
                    'commands':{x:shutil.which(x) for x in ('bash','python3','curl','ip','flock','sudo','visudo')},
                    'protected_backend':Path('/var/lib/riseup-vpn/backend.sh').is_file(),
                    'network_tested':False,'system_rules_modified':False}
        elif args.command=='update':
            if args.manifest:
                found=updater.parse_manifest(json.loads(args.manifest.read_text(encoding='utf-8')),updater.local_version(root))
            else:found=updater.check(root)
            if found:updater.apply(found,root)
            state_file=root/'.cleanup.json'
            try:resume_region=json.loads(state_file.read_text(encoding='utf-8')).get('region','amsterdam')
            except (OSError,ValueError):resume_region='amsterdam'
            result={'version':updater.local_version(root),'updated':bool(found),'launched':False,'resume_region':resume_region}
        else:
            if not 0<args.timeout<=300:raise updater.UpdateError('timeout must be between 0 and 300 seconds')
            status=updater.lifecycle_status(root)
            if status['running']:
                # Only the process holding the lifecycle lock, never an arbitrary saved PID.
                pid=status.get('pid')
                if not pid:raise updater.UpdateError('Running process has no verified PID; stop it in its terminal')
                os.kill(pid,signal.SIGTERM)
                deadline=time.monotonic()+args.timeout
                while updater.lifecycle_status(root)['running']:
                    if time.monotonic()>=deadline:raise updater.UpdateError('Cleanup timeout; process not killed, update forbidden')
                    time.sleep(.1)
            updater.require_clean(root)
            with updater.backend_idle():pass
            try:state=json.loads((root/'.cleanup.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):state={'region':'amsterdam'}
            result={'stopped':True,'cleanup':'ok' if state.get('cleanup')=='ok' else 'no_session',
                    'selected_region':state.get('region','amsterdam'),'reconnected':False}

        print(json.dumps({'app_id':'tvpn','ok':True,**result},ensure_ascii=False));return 0
    except (updater.UpdateError,OSError,ValueError) as error:
        print(json.dumps({'app_id':'tvpn','ok':False,'error':str(error)},ensure_ascii=False));return 1


if __name__=='__main__':sys.exit(main())
