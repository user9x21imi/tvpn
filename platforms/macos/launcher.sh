#!/bin/bash
set -euo pipefail
region=amsterdam
while (( $# )); do
    case "$1" in --region) shift; region=${1:?} ;; --text|--events) ;; *) exit 2 ;; esac
    shift
done
case "$region" in amsterdam|paris|montreal|newyork|miami|seattle) ;; *) exit 2 ;; esac
exec sudo -n /Library/PrivilegedHelperTools/riseup-vpn-panel/backend.sh --text --region "$region" --events
