# MediaDrop Ripper for Mac

A native SwiftUI CD client for MediaDrop. Requires macOS 14+, an audio CD drive,
and MediaDrop server 1.6+. The client bundles its own audio-only FFmpeg encoder,
LAME and libdiscid. No Python, Homebrew or Terminal is needed to run it.

## Install and use

Open this repository's Releases page and download the latest MediaDrop Ripper
DMG: arm64 for Apple Silicon or x86_64 for Intel. Open the DMG and drag the app
to Applications. Build artifacts are also available on the Mac CD client Actions run.
The initial app is ad-hoc signed, not Apple notarised. If blocked, open it once,
then use System Settings > Privacy & Security > Open Anyway for this app.

1. Connect to your local MediaDrop URL and choose an available music destination.
2. Insert a CD and click Find CD. Choose CD folder can select the mounted CD.
3. Pick the matching MusicBrainz edition and check album and per-track details.
   Compilation tracks may have different artists. Semicolon-separated performers
   remain intact and the album artist determines the album folder on the server.
4. Select tracks and choose Rip & upload selected. Choose MP3 at 320 kbps (default) or lossless FLAC before queueing.
5. If interrupted, use Retry pending. The app preserves encoded files and server
   job IDs across restarts. Reinsert the CD only for tracks not yet extracted.

Artwork is shown from Cover Art Archive when available. This first client does
not embed images in MP3s; the server's Plex/Lidarr integration supplies its tiles.
Metadata lookup never applies an edition with a different disc ID or track count.
You can always enter details manually if the CD is not in MusicBrainz.

## Extraction and recovery

macOS exposes audio CD tracks as AIFF files. The app copies these off the disc
before encoding. The optional second read compares two copies of each track;
it is **not** AccurateRip verification or secure extraction with cache defeat.
Scratched discs, mixed-mode media and individual drives need real hardware tests.
The app does not eject the disc automatically or alter any source file.

State and cached audio files are under `~/Library/Application Support/MediaDrop Ripper`.
Finished audio caches are removed after server completion, while completion IDs are
retained so the same disc/track/destination is not queued again accidentally.
If you change metadata after queueing, the queued item keeps its original tags.
Use the server editor to change metadata on an already uploaded track.

Retries use a persisted upload token. The server returns the original job for a
repeated token and refuses reuse with a different request. It retains these IDs
in its jobs file, so keep the server's persistent data volume. This prevents
network retries creating duplicates; it is not an audio fingerprint deduplicator.
A server-failed job stays attached to its queue entry for inspection. Fix the
server first, confirm no output was published, then use Remove next to that queue entry before deliberately ripping it again. Do not
clear the server's job history while a client has pending uploads.

Stop cancels the running extraction/encoding process or network task. Partial
encodes are discarded; completed encodes and accepted upload IDs are kept. Keep the
app running during work; it does not install a background agent.

## Build

GitHub Actions builds and tests separate Apple Silicon and Intel DMGs. Build on
macOS 14+ with Xcode command line tools and Homebrew installed:

```sh
bash client/build-macos.sh
```

The script builds a small FFmpeg 8.0.1 executable, relocates all non-system dylibs
into the app, bundles exact upstream source archives and license texts, ad-hoc
signs the bundle, runs the bundled encoder and core tests, then creates a DMG.
The installer never downloads dependencies on the user's machine. Developer ID
signing and notarisation can be added when the owner supplies Apple credentials.

## Server protocol

`GET /api/health` supplies the version, `/api/state` the available music folders.
Uploads are raw MP3 or FLAC bodies to `/api/upload?folder=ID&name=NAME&layout=album&format=mp3`, with
`X-MediaDrop: 1`, percent-encoded JSON in `X-MediaDrop-Tags`, and a persistent
`X-MediaDrop-Upload-ID`. The 202 response contains `job`; poll `/api/jobs/ID`
until done/failed. Local HTTP is supported for the user's private LAN.

Each app, helper and bundled dynamic library is checked for a deployment target
of macOS 14.0 or earlier. CI launches the Apple Silicon app on macOS 14 and the
Intel app on macOS 15. A physical CD drive is still needed for extraction testing.

Format is stored per queued track. Existing queues without a format remain MP3.
The same CD can be queued once per destination and format. This version encodes
one chosen format per operation; simultaneous archive/listening output is not yet
implemented. FLAC uploads require server 1.6 to retain FLAC on the server.
