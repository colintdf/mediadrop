#!/bin/bash
# Finder launcher. All paths are quoted so the folder can live anywhere.
cd -- "$(dirname -- "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; assert sys.version_info >= (3,10)' >/dev/null 2>&1; then
  echo 'MediaDrop needs Python 3.10 or later.'
  echo 'Install Homebrew from https://brew.sh, then double-click Setup.command.'
  read -r -p 'Press Return to close.'
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo 'FFmpeg is missing. Double-click Setup.command first.'
  read -r -p 'Press Return to close.'
  exit 1
fi
# Open the browser after Python has had a moment to start.
(sleep 2; open 'http://localhost:12345') &
python3 server.py
read -r -p 'Press Return to close.'
