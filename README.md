# MediaDrop 1.2

A private music inbox for your media centre Mac, with a responsive web interface on port **12345**. Upload from a browser on the Mac or another device on the same home network.

## Docker

To run MediaDrop with your other containers, follow the [Docker setup guide](docs/docker.md). The included image installs FFmpeg, runs as UID 501 / GID 20 by default, and uses a persistent settings volume plus a music bind mount. It listens on port **12345** and restarts with Docker using the supplied Compose configuration.

## Start here (native Mac installation)

1. Unzip this folder somewhere permanent on the media centre Mac, such as `~/Applications/MediaDrop`.
2. Install [Homebrew](https://brew.sh) if it is not installed. Double-click **Setup.command** to install Python and FFmpeg. If these are already installed, skip setup. Requires Python 3.10 or later.
3. Double-click **Start.command**. Leave its Terminal window open. The browser opens at **http://localhost:12345**. If macOS asks whether Python may accept incoming connections, allow it for access from other devices.
4. Copy the password from that Terminal window into the sign-in screen.
5. Click **Manage folders**. Add a display name and an existing folder's full path **on the server Mac**, for example `/Volumes/Media/Music`. In Finder, select a folder and press **Option + Command + C** to copy its path. Grant Terminal access to removable volumes if macOS asks.
6. Choose a destination and drop music files onto the upload area, or click to browse. Multiple files are supported. Tracks are staged first: click **Edit details** to enter tags and choose their folder layout, then click **Upload staged tracks**.

From another device, open the network address printed in Terminal, or `http://YOUR-MAC-IP:12345`. Find the Mac's local IP in System Settings > Network. The upload device does not need FFmpeg or Python.

If macOS blocks a launcher, inspect the included plain-text scripts and use Finder's Open action or run from Terminal:

```sh
cd "/path/to/MediaDrop"
bash Setup.command
bash Start.command
```

No installer, subscription, cloud service, JavaScript build step or pip packages. The interface uses system fonts and works without an internet connection after setup. Optional artwork connections need access to your Plex or Lidarr server. FFmpeg and Python installation require internet access.

## What it does

- Multiple named music destinations, with music-only filtering. Film and TV sections are marked for a future version.
- WAV, FLAC, M4A, AAC, OGG, OPUS, AIFF and WMA converted to MP3 using FFmpeg's LAME encoder, constant **320 kbps**, 44.1 kHz stereo (multichannel sources are downmixed). Conversion errors appear in the queue. DRM-protected files are unsupported.
- Valid MP3 uploads with no tag changes are checked and copied byte for byte, without another lossy encode. Tag edits rewrite the container using stream copy; the audio is never re-encoded.
- Metadata supported by FFmpeg is copied where possible. Embedded artwork is not copied during conversion in this version. Existing MP3 artwork stays intact.
- Output uses the original filename with an `.mp3` suffix. Existing names get ` (1)`, ` (2)`, etc. Existing files are never overwritten.
- Upload progress in the browser, persistent server conversion queue, conversion progress and readable error messages.
- Uploads stream to disk. Conversions run one at a time, limiting load on the media centre Mac. You can keep adding files while conversion is running.
- After a file has fully uploaded, the server owns conversion. You can close the browser once all browser uploads finish. Queued jobs resume after restarting the server.
- Original files on your upload device are untouched. Server staging files are deleted after processing, including failures. Re-upload the original if a job fails.
- Files up to 10 GB each. Individual files and batches of files are supported. Dropping directories and preserving uploaded folder trees are not included; artist and album folders can be created from the track details.

## Track metadata and folder layout

Drop or browse files to stage them. They do not upload until you click **Upload staged tracks**. Each staged track has **Edit details** for title, artist, album, album artist, track number, disc number, year/date and genre. Only fields you change replace the file's existing tags; untouched fields are preserved. To remove a tag before upload, type into its field and then clear it. Use the shared-fields checkbox to apply only artist, album artist, year and genre fields that you changed to other staged tracks. Their titles, album names, track numbers and destinations stay individual.

Choose where a track belongs, with a destination path preview:

- **Single:** `Music/Artist/track.mp3`
- **Album:** `Music/Artist/Album/track.mp3`
- **Directly in selected music folder:** keep the original upload behaviour.

There are no extra `Albums` or `Singles` folders. Album artist is used for the artist folder when supplied, otherwise artist is used. Singles have no release subfolder, even if they have an album tag. Album tracks require an album name. Filename characters unsuitable for folders are replaced with underscores. Existing names receive a number rather than being overwritten. Files retain their original filenames, with an MP3 extension for converted uploads.

After uploading, use **Edit details** on the completed transfer or in **Your music library**. The editor reads the current tags from the actual file. Save tags in place or select a music destination and Single/Album layout to move the track. Clearing a field removes that tag. A file changed by another application while the editor was open must be reopened before saving. Existing files are never automatically reorganised by a scan or a tag change; choose a layout to move them.

## Your existing music library

**Your music library** scans every configured music destination recursively, including audio that was already there before MediaDrop. Start with a grid of artist tiles. Open an artist to see their albums and singles, then open a release for its track list and metadata editor. Artist grouping prefers album artist, then artist, then the artist folder name when tags are missing. Breadcrumbs return to the artist or the full library. Search across tags and filenames, or filter by destination. There are 24 artist/release tiles or 50 tracks per page, with counts computed from the full matching library. Track lists are ordered by disc and track number. Scans read metadata; they do not convert or move existing files.

A scan runs at server startup and after adding a destination. Use **Scan folders** after adding, removing or changing files outside MediaDrop. The index caches unchanged files so repeat scans are quicker. New uploads and edits through MediaDrop update the index immediately. Large first scans can take time; the progress count is shown in the interface. Keep your media drives mounted. Hidden files and symbolic links are skipped. Removing a destination hides its indexed tracks without deleting the actual music.

Under the standard music-root layout, files directly in an artist folder are listed as singles and files inside its album subfolders are listed as album tracks. This display classification is based on the path; the actual tags remain editable.

Existing supported audio formats are indexed. Metadata editing uses FFmpeg stream copy to preserve the existing audio format and quality. Some formats cannot represent every tag: if a requested tag cannot be stored, MediaDrop rejects the change and retains the original file. MP3 has full support for the fields in this editor. Other tags and artwork are retained where FFmpeg supports them; unusual vendor-specific metadata may not survive a rewrite. Converted uploads still omit embedded artwork in this version.

## Bulk metadata editing

Inside an artist, tick the release cards you want to edit, then choose **Edit selected**. In a release track list, tick individual tracks or use **Select this page**. **Edit all artist tracks** selects all tracks for the current artist within the active destination/search filter. A batch can contain up to **200 tracks**; select smaller batches for larger collections.

The bulk editor shows common values and marks mixed values. Every field starts **unchecked**. Check only the fields to change. An unchecked field is omitted from the update, preserving every track's original value. An explicitly checked, empty field removes that tag.

- Artist, album artist, genre and year/date can be bulk changed.
- Album name is available only when all selected tracks belong to one album. It is protected for singles and selections spanning different releases.
- Track titles, track/disc numbers, filenames, destinations and folder layouts are never changed by a bulk edit. Editing a shared artist tag may change which artist tile a track appears under, but its file stays in place.
- Each file is checked against its version when you opened the editor. A preflight conflict stops the batch before any writes. Changes are saved atomically per file without re-encoding audio. The result lists successes and failures; a format/permission failure on one file does not undo already completed files.
- Keep the server running until the batch finishes. Bulk progress is shown in the dialog. Bulk plans/results are temporary; if the server restarts mid-batch, completed edits remain saved and you should inspect the library before retrying.

Individual track edits still support changing titles and explicitly moving tracks between the appropriate artist/album folders.

## Artist photos and release artwork

Click **Artwork** in the top bar. Choose **Plex Media Server** or **Lidarr**, enter that server's full URL and credential, then choose **Save and sync artwork**.

- Plex example: `http://192.168.1.20:32400`, with your **X-Plex-Token**. Leave the optional music library section ID blank to include all accessible music libraries, or supply one numeric section ID.
- Lidarr example: `http://192.168.1.20:8686`, with its **API key** from Lidarr's settings. A reverse-proxy URL including its base path can also be used.

This connects to **your existing server** and uses artist photos and release covers already in its library. It does not install Plex/Lidarr, automatically identify unknown music, fetch from a public Plex metadata service, or change either provider's metadata. Library tiles remain usable without a connected provider.

Matching uses case-insensitive artist and release names, with album artist preferred. Ambiguous duplicate-name matches are skipped. Missing images use the illustrated fallback tiles. Accurate tags improve the matches. Artist/release references are synced first; images load as tiles appear and are cached privately on the MediaDrop server. **Refresh artwork from server** refreshes the references and cached images. Artwork is displayed in MediaDrop; it is not embedded in your audio files or saved into music folders.

Tokens/API keys stay in MediaDrop's private server configuration and are sent only to the configured provider in request headers. They are not returned to the browser or put into image URLs. Leave a saved credential blank to retain it when the provider and URL are unchanged. Selecting **No connected source** disconnects the provider and removes its saved credential. These credentials can grant access to the provider, so use the application on your trusted local network as described below. Provider redirects are rejected; use the final server URL. Self-signed HTTPS certificates need to be trusted by the Python runtime, or use the provider's HTTP URL on your trusted LAN.

Official references: [Plex server API](https://developer.plex.tv/pms/), [finding your Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/), and [Lidarr API](https://lidarr.audio/docs/api/).

## Updating from 1.0 or 1.1

Stop MediaDrop with **Control + C** in its Terminal window. Unzip the updated folder, replace the previous application folder, and run **Start.command**. Your password, destinations and upload history are kept separately and remain available. No need to run Setup again if Python and FFmpeg are installed. Refresh your browser after restarting. Existing completed uploads can be edited, and the new library scan picks up music already in your configured folders.

## Everyday use

The destination is captured when files enter the browser queue. Changing the selected folder affects newly added files. Removing a destination only removes its setting; it does not remove any music or change jobs already queued.

Keep external media drives mounted. Missing destination folders are never automatically recreated on the startup disk. Create folders in Finder first. To change a destination's name or path, remove its setting and add it again.

The password is generated at first start and stays the same between restarts. Sessions last 24 hours. Settings, password and job history are stored privately at:

```
~/Library/Application Support/MediaDrop/
```

The server retains job history and shows the most recent 100 transfers. Fully uploaded pending jobs survive restarts; unfinished browser uploads must be sent again. The browser does not retain files across a page reload.

To stop: press **Control + C** in the Terminal window. To start: double-click **Start.command**. Automatic launch at login and running as a menu bar app are not included in this version. The Mac must remain awake for remote access and conversions.

## Local network access

MediaDrop listens on all network interfaces by default, with a password, session cookies, origin checks and login rate limiting. It is intended for your trusted home network. It serves HTTP, not HTTPS: do not forward port 12345 on your router or expose it directly to the internet. Anyone signed in can manage destination folders on the server Mac.

For access on the Mac only:

```sh
python3 server.py --host 127.0.0.1
```

Other options:

```sh
python3 server.py --port 12345 --data "/path/to/private/settings"
```

Only one instance may use a settings directory. If another program already uses port 12345, stop it or choose a different port (the double-click launcher assumes the default).

## Troubleshooting

- **Cannot connect from another device:** use the Mac's local IP, check both devices are on the same network, allow incoming Python connections in the Mac firewall, and keep the Mac awake. Guest Wi-Fi may isolate devices.
- **Folder unavailable:** mount its external drive or network share in Finder, then check the saved path.
- **Permission denied:** give Terminal access to that location in macOS Privacy & Security settings. Folders and drives must be writable by the user running MediaDrop.
- **Conversion failed:** the queue displays the problem. Check the source plays normally and that the destination drive has space. Re-upload after fixing it.
- **No FFmpeg:** run Setup.command again. Launchers search both Apple Silicon and Intel Homebrew locations.
- **Forgotten password:** it is printed every time Start.command runs. To replace it, stop the server, edit the `password` value in `config.json`, then restart. This also invalidates browser sessions.

## Next phase: CD ripping client

Planned separately after this server: a companion Mac client that reads audio CDs, looks up album and track metadata, rips to MP3, and sends tracks directly to a selected MediaDrop music destination. This download contains the upload server only.

## Developer checks

```sh
python3 -m unittest discover -s tests -v
```

Integration checks exercise 320 kbps WAV-to-MP3 conversion, pre-upload tags, byte-for-byte MP3 copying, audio-preserving metadata edits and moves, album/single layouts, existing-file indexing and search, deleted-file rescans, conflict protection, duplicate handling, authentication, destination validation, symlink rejection and interrupted-job recovery. FFmpeg and FFprobe must be on PATH. Additional checks cover safe bulk edits, single/album-name protection, preflight conflicts, artist/release pagination, and read-only Plex/Lidarr artwork lookups against simulated provider responses. Live access to your own Plex/Lidarr instance still needs to be checked after configuration.
