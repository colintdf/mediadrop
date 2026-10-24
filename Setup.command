#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo 'MediaDrop setup'
echo 'This installs Python and FFmpeg through Homebrew. No pip packages are needed.'
if ! command -v brew >/dev/null 2>&1; then
  echo ''
  echo 'Install Homebrew from https://brew.sh first, then run this file again.'
  open 'https://brew.sh'
  read -r -p 'Press Return to close.'
  exit 1
fi
if brew install python ffmpeg; then
  chmod +x Start.command
  echo ''
  echo 'Ready. Double-click Start.command to start MediaDrop.'
else
  echo 'Setup did not finish. Review the error above, then try again.'
fi
read -r -p 'Press Return to close.'
