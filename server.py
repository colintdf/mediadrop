#!/usr/bin/env python3
"""MediaDrop: a private LAN music inbox. Python 3.10+, FFmpeg, no pip packages."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import hashlib
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote
from artwork import Artwork, validate_settings
from artists import primary_artist, credited_artists, split_artists
from filename_metadata import metadata_from_filename

AUDIO = {'.mp3', '.wav', '.wave', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.aif', '.aiff', '.wma'}
ROOT = Path(__file__).resolve().parent


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2))
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def safe_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A filename is required.')
    if '/' in value or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid filename.')
    if len(value.encode('utf-8')) > 220 or value.startswith('.'):
        raise ValueError('Filename is too long or starts with a dot.')
    if Path(value).suffix.lower() not in AUDIO:
        raise ValueError('Choose a supported music file, such as MP3, WAV, FLAC or M4A.')
    return value


TAG_FIELDS = ('title', 'artist', 'album', 'album_artist', 'track', 'disc', 'date', 'genre')


def validate_metadata(value):
    if not isinstance(value, dict) or any(k not in TAG_FIELDS for k in value):
        raise ValueError('Invalid metadata fields.')
    result = {}
    for key, text in value.items():
        if not isinstance(text, str) or len(text) > 300 or any(ord(c) < 32 for c in text):
            raise ValueError('Metadata must be text of at most 300 characters per field.')
        text = text.strip()
        if key in ('track', 'disc') and text and not re.fullmatch(r'[1-9][0-9]{0,3}(/[1-9][0-9]{0,3})?', text):
            raise ValueError('Track and disc numbers must look like 1 or 1/12.')
        if key == 'date' and text and not re.fullmatch(r'[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?', text):
            raise ValueError('Use a four-digit year or a date such as 2026-10-23.')
        result[key] = text
    return result


def read_tags(path):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags', '-of', 'json', str(path)], capture_output=True, text=True, timeout=60)
    if probe.returncode:
        raise ValueError('Unable to read this track. Check the file and drive.')
    tags = {k.lower(): str(v) for k, v in json.loads(probe.stdout).get('format', {}).get('tags', {}).items()}
    return {k: tags.get(k, tags.get('year', '') if k == 'date' else '') for k in TAG_FIELDS}


def tag_args(tags):
    args = []
    for key, value in tags.items():
        args.extend(['-metadata', f'{key}={value}'])
    return args


def write_tags(source, output, tags):
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-map', '0', '-c', 'copy', '-map_metadata', '0', *tag_args(tags), *( ['-id3v2_version', '3'] if output.suffix.lower() == '.mp3' else []), str(output)]
    result = subprocess.run(command, capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('Could not save tags; the original track has been kept. ' + result.stderr.decode(errors='replace')[:500])


def revision(path):
    stat = path.stat()
    return hashlib.sha256(f'{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()


def folder_part(value):
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', value).strip(' .')
    if not value or value in ('.', '..') or len(value.encode()) > 180:
        raise ValueError('Artist and release names must be valid folder names (up to 180 bytes).')
    return value


def single_release_defaults(tags, blocked=()):
    candidates = {'album': tags.get('title', ''), 'album_artist': primary_artist(tags), 'track': '1'}
    return {key: value for key, value in candidates.items()
            if value and key not in blocked and not str(tags.get(key) or '').strip()}


def organised_folder(root, tags, layout):
    root = check_directory(Path(root))
    if layout == 'flat':
        return root
    if layout not in ('album', 'single'):
        raise ValueError('Choose original folder, album or single.')
    artist = primary_artist(tags)
    release = tags.get('album') or (tags.get('title') if layout == 'single' else '')
    if not artist or not release:
        raise ValueError('Enter an artist and release name (album name or single title) to organise this track.')
    target = root / folder_part(artist)
    target = target / folder_part(release)
    # Refuse symlink routes outside the selected library.
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('The destination points outside the selected music folder.')
    target.mkdir(parents=True, exist_ok=True)
    return check_directory(target)


def library_identity(track):
    tags = track['metadata']
    parts = Path(track['relative']).parts
    artist = primary_artist(tags, parts[0] if len(parts) >= 2 else '') or 'Unknown artist'
    kind = track.get('layout', 'single')
    release = (tags.get('album') or (parts[1] if kind == 'album' and len(parts) >= 3 else '') or tags.get('title') or Path(track['name']).stem).strip()
    return artist, artist.casefold(), release, kind + ':' + release.casefold()


def library_credits(track):
    parts = Path(track['relative']).parts
    names = credited_artists(track['metadata'], parts[0] if len(parts) >= 2 else '')
    return [{'name': name, 'key': name.casefold()} for name in names]


def credited_to(track, artist_key):
    return any(artist['key'] == artist_key for artist in library_credits(track))


def release_key(track, artist_key):
    _, primary, _, release_id = library_identity(track)
    if primary == artist_key:
        return release_id
    # A guest can appear on two different artists' albums with the same title.
    return 'appearance:' + hashlib.sha256((primary + '\0' + release_id).encode()).hexdigest()


def browse_library(items, view, artist_key='', release_id=''):
    if view == 'artists':
        groups = {}
        for track in items:
            _, primary, _, release = library_identity(track)
            for artist in library_credits(track):
                group = groups.setdefault(artist['key'], {'key': artist['key'], 'name': artist['name'], 'track_count': 0, '_releases': set()})
                group['track_count'] += 1
                group['_releases'].add((primary, release))
        result = []
        for group in groups.values():
            group['release_count'] = len(group.pop('_releases'))
            result.append(group)
        return sorted(result, key=lambda g: g['name'].casefold())
    selected = [t for t in items if credited_to(t, artist_key)]
    if view == 'releases':
        groups = {}
        for track in selected:
            artist, primary, release, _ = library_identity(track)
            key = release_key(track, artist_key)
            group = groups.setdefault(key, {'key': key, 'name': release, 'artist': artist, 'kind': track['layout'],
                                           'appears_on': primary != artist_key, 'track_count': 0,
                                           'year': track['metadata'].get('date', '')[:4]})
            group['track_count'] += 1
        return sorted(groups.values(), key=lambda g: (g['appears_on'], g['kind'] != 'album', g['name'].casefold(), g['artist'].casefold()))
    if release_id:
        selected = [t for t in selected if release_key(t, artist_key) == release_id]
    def number(text):
        try:
            return int((text or '0').split('/')[0])
        except ValueError:
            return 0
    return sorted(selected, key=lambda t: (number(t['metadata'].get('disc')), number(t['metadata'].get('track')), t['name'].casefold()))


def check_directory(path):
    if not path.is_dir():
        raise ValueError('Folder is unavailable. Check that the drive is connected.')
    if not os.access(path, os.W_OK | os.X_OK):
        raise ValueError('MediaDrop cannot write to this folder. Check its permissions.')
    return path


def publish(temp, folder, name):
    """Reserve an output name without overwriting; works on external filesystems too."""
    base = Path(name)
    for n in range(10000):
        target = folder / (name if n == 0 else f'{base.stem} ({n}){base.suffix}')
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        # Placeholder reserves the name; completed content replaces it atomically.
        os.close(fd)
        try:
            os.replace(temp, target)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target
    raise ValueError('Too many files with the same name.')


class App:
    def __init__(self, data, worker=True):
        self.data = Path(data).expanduser().resolve()
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.incoming = self.data / 'incoming'
        self.incoming.mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.tag_lock = threading.RLock()
        self.bulk_plans = {}
        self.scan_lock = threading.Lock()
        self.scan_state = {'running': False, 'scanned': 0, 'errors': 0}
        self.library = json.loads((self.data / 'library.json').read_text()) if (self.data / 'library.json').exists() else {}
        self.upload_slots = threading.BoundedSemaphore(3)
        self.active_uploads = set()
        self.queue = queue.Queue()
        self.stopping = threading.Event()
        self.process = None
        self.worker = None
        config_path = self.data / 'config.json'
        self.config = json.loads(config_path.read_text()) if config_path.exists() else {'folders': []}
        self.config.pop('password', None)
        self.jobs = json.loads((self.data / 'jobs.json').read_text()) if (self.data / 'jobs.json').exists() else []
        self.artwork = Artwork(self.data, self.config.get('artwork', {'provider':'none'}))
        self.save_config()
        for job in self.jobs:
            if job['status'] in ('queued', 'converting', 'checking'):
                if (self.incoming / job['id']).is_file():
                    job.update(status='queued', progress=0)
                    self.queue.put(job['id'])
                else:
                    job.update(status='failed', error='Upload was interrupted. Please upload again.')
        # Incomplete HTTP uploads are never considered jobs.
        known = {j['id'] for j in self.jobs if j['status'] == 'queued'}
        for path in self.incoming.iterdir():
            if path.name not in known and path.is_file():
                path.unlink()
        self.save_jobs()
        if worker:
            self.worker = threading.Thread(target=self.work, daemon=True)
            self.worker.start()

    def save_config(self):
        atomic_json(self.data / 'config.json', self.config)

    def save_jobs(self):
        atomic_json(self.data / 'jobs.json', self.jobs)

    def update(self, job, **values):
        with self.lock:
            job.update(values)
            self.save_jobs()

    def folder(self, folder_id):
        with self.lock:
            folder = next((dict(f) for f in self.config['folders'] if f['id'] == folder_id and f['type'] == 'music'), None)
        if not folder:
            raise ValueError('Choose a music destination first.')
        check_directory(Path(folder['path']))
        return folder

    def library_record(self, root_id, root, path, tags=None, suppressed=None, layout=None):
        relative = str(path.relative_to(root))
        key = 'lib_' + hashlib.sha256((str(root) + '/' + relative).encode()).hexdigest()
        stat = path.stat()
        previous = self.library.get(key, {})
        fresh = previous.get('size') == stat.st_size and previous.get('modified') == stat.st_mtime_ns
        raw = tags if tags is not None else previous.get('file_metadata', previous['metadata']) if fresh else read_tags(path)
        suppressed = sorted(set(previous.get('suppressed_inference', []) if suppressed is None else suppressed))
        metadata, inferred = metadata_from_filename(path.name, raw, blocked=suppressed)
        release_type = layout if layout in ('single','album') else previous.get('release_type')
        return {'id': key, 'folder_id': root_id, 'relative': relative, 'name': path.name,
                'size': stat.st_size, 'modified': stat.st_mtime_ns, 'metadata': metadata,
                'file_metadata': raw, 'inferred': inferred, 'suppressed_inference': suppressed,
                'layout': release_type or ('album' if len(Path(relative).parts) >= 3 else 'single'),
                'release_type': release_type, 'indexed_at': time.time()}

    def scan(self):
        if not self.scan_lock.acquire(blocking=False):
            return False
        with self.lock:
            self.scan_state = {'running': True, 'scanned': 0, 'errors': 0}
        def run():
            try:
                with self.lock:
                    folders = [dict(f) for f in self.config['folders'] if f['type'] == 'music']
                for folder in folders:
                    root = Path(folder['path'])
                    if not root.is_dir():
                        continue
                    started = time.time()
                    seen = set()
                    traversal_errors = []
                    for directory, dirs, files in os.walk(root, followlinks=False, onerror=traversal_errors.append):
                        dirs[:] = [d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink()]
                        for filename in files:
                            if self.stopping.is_set():
                                return
                            path = Path(directory) / filename
                            if filename.startswith('.') or path.suffix.lower() not in AUDIO or path.is_symlink():
                                continue
                            key = 'lib_' + hashlib.sha256((str(root) + '/' + str(path.relative_to(root))).encode()).hexdigest()
                            seen.add(key)
                            try:
                                # A tag edit and an index refresh cannot race on the same file.
                                with self.tag_lock:
                                    record = self.library_record(folder['id'], root, path)
                                    with self.lock:
                                        self.library[record['id']] = record
                            except (ValueError, OSError, subprocess.TimeoutExpired):
                                with self.lock:
                                    self.scan_state['errors'] += 1
                            with self.lock:
                                self.scan_state['scanned'] += 1
                    with self.lock:
                        if not traversal_errors:
                            self.library = {k:v for k,v in self.library.items() if v['folder_id'] != folder['id'] or k in seen or v.get('indexed_at', 0) >= started}
                        self.scan_state['errors'] += len(traversal_errors)
                        atomic_json(self.data / 'library.json', self.library)
            finally:
                with self.lock:
                    self.scan_state['running'] = False
                self.scan_lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True

    def index_path(self, root, path, tags, suppressed=None, layout=None):
        with self.lock:
            folder = next((f for f in self.config['folders'] if f['path'] == str(root) and f['type'] == 'music'), None)
            if folder:
                record = self.library_record(folder['id'], root, path, tags, suppressed, layout)
                self.library[record['id']] = record
                atomic_json(self.data / 'library.json', self.library)

    def track(self, job_id):
        if isinstance(job_id, str) and job_id.startswith('lib_'):
            with self.lock:
                record = self.library.get(job_id)
                if not record:
                    raise ValueError('This library track is no longer indexed. Rescan your library.')
                folder = self.folder(record['folder_id'])
                root = Path(folder['path'])
                path = root / record['relative']
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                    raise ValueError('Track unavailable or outside its music folder.')
                return {'id': job_id, 'destination': str(path.parent), 'library_root': str(root), 'output': path.name, 'layout': record['layout']}, path
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == job_id and j['status'] == 'done'), None)
        if not job:
            raise ValueError('This track is not ready to edit.')
        name = job.get('output', '')
        if not name or Path(name).name != name:
            raise ValueError('Invalid track filename.')
        parent = check_directory(Path(job['destination']))
        path = parent / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Track unavailable. Check that it has not been moved or deleted.')
        return job, path

    def read_metadata(self, job, path):
        root = Path(job.get('library_root', job['destination']))
        key = 'lib_' + hashlib.sha256((str(root) + '/' + str(path.relative_to(root))).encode()).hexdigest()
        with self.lock:
            suppressed = list(self.library.get(key, {}).get('suppressed_inference', []))
        raw = read_tags(path)
        metadata, inferred = metadata_from_filename(path.name, raw, blocked=suppressed)
        return {'metadata': metadata, 'file_metadata': raw, 'inferred': inferred, 'suppressed_inference': suppressed}

    def edit_metadata(self, value, infer_missing=True):
        tags = validate_metadata(value.get('metadata', {}))
        with self.tag_lock:
            job, path = self.track(value.get('id'))
            original_root = Path(job.get('library_root', job['destination']))
            original_key = 'lib_' + hashlib.sha256((str(original_root) + '/' + str(path.relative_to(original_root))).encode()).hexdigest()
            current = revision(path)
            if current != value.get('revision'):
                raise ValueError('This file changed since you opened it. Close and reopen the editor.')
            details = self.read_metadata(job, path)
            suppressed = set(details['suppressed_inference'])
            for key, text in tags.items():
                if key in ('artist', 'title'):
                    if text:
                        suppressed.discard(key)
                    else:
                        suppressed.add(key)
            merged, inferred = metadata_from_filename(path.name, {**details['file_metadata'], **tags}, blocked=suppressed | set(tags))
            updates = {**(inferred if infer_missing else {}), **tags}
            validate_metadata(updates)
            layout = value.get('layout', 'keep')
            if layout == 'single':
                defaults = single_release_defaults(merged, blocked=set(tags))
                merged.update(defaults)
                updates.update(defaults)
            if layout == 'keep':
                destination = path.parent
                root = Path(job.get('library_root', job['destination']))
            else:
                root = Path(self.folder(value.get('folder'))['path'])
                destination = organised_folder(root, merged, layout)
            fd, tmp = tempfile.mkstemp(prefix='.mediadrop-tags-', suffix=path.suffix, dir=destination)
            os.close(fd)
            temp = Path(tmp)
            try:
                if updates:
                    write_tags(path, temp, updates)
                else:
                    shutil.copyfile(path, temp)
                actual = read_tags(temp)
                if any(actual.get(k, '') != v for k, v in updates.items()):
                    raise ValueError('This audio format could not store every requested tag. The original file has been kept. Convert to MP3 for full tag support.')
                if revision(path) != current:
                    raise ValueError('The file changed while saving. Reopen the editor and try again.')
                os.chmod(temp, path.stat().st_mode & 0o777)
                if destination.resolve() == path.parent.resolve():
                    os.replace(temp, path)
                    output = path
                else:
                    output = publish(temp, destination, path.name)
                    try:
                        path.unlink()
                    except OSError:
                        output.unlink(missing_ok=True)
                        raise ValueError('Could not remove the old copy. The original track has been kept.')
                if not job['id'].startswith('lib_'):
                    self.update(job, destination=str(destination), library_root=str(root), output=output.name,
                            metadata=actual, bytes=output.stat().st_size,
                            layout=job.get('layout', 'flat') if layout == 'keep' else layout)
                with self.lock:
                    self.library.pop(original_key, None)
                    atomic_json(self.data / 'library.json', self.library)
                self.index_path(root, output, actual, suppressed, job.get('layout') if layout == 'keep' else layout)
                # Keep upload-history entries in sync when editing through the library.
                with self.lock:
                    for item in self.jobs:
                        if item.get('status') == 'done' and Path(item['destination']) / item.get('output', '') == path:
                            item.update(destination=str(destination), output=output.name, library_root=str(root), metadata=actual, bytes=output.stat().st_size)
                    self.save_jobs()
                effective, hints = metadata_from_filename(output.name, actual, blocked=suppressed)
                return {'metadata': effective, 'inferred': hints, 'revision': revision(output), 'path': str(output)}
            finally:
                temp.unlink(missing_ok=True)

    def prepare_bulk(self, value):
        ids = value.get('ids')
        with self.lock:
            if ids is None:
                artist = value.get('artist')
                releases = value.get('releases')
                folder = value.get('folder')
                query = str(value.get('q', '')).casefold()
                if not isinstance(artist, str) or not artist:
                    raise ValueError('Choose tracks or releases before bulk editing.')
                if releases is not None and (not isinstance(releases, list) or not releases or any(not isinstance(r, str) for r in releases)):
                    raise ValueError('Choose at least one release.')
                active = {f['id'] for f in self.config['folders'] if f['type'] == 'music'}
                ids = [t['id'] for t in self.library.values() if t['folder_id'] in active
                       and (not folder or t['folder_id'] == folder)
                       and credited_to(t, artist)
                       and (releases is None or release_key(t, artist) in releases)
                       and (not query or query in (' '.join(t['metadata'].values()) + ' ' + t['relative']).casefold())]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 200 or any(not isinstance(i, str) or not i.startswith('lib_') for i in ids):
                raise ValueError('Choose between 1 and 200 library tracks per batch.')
            ids = list(dict.fromkeys(ids))
        files = []
        paths = set()
        identities = []
        with self.tag_lock:
            for track_id in ids:
                job, path = self.track(track_id)
                if path.resolve() in paths:
                    continue
                paths.add(path.resolve())
                details = self.read_metadata(job, path)
                tags = details['metadata']
                with self.lock:
                    record = self.library[track_id]
                artist, _, release, _ = library_identity({**record, 'metadata': tags})
                identities.append((record['layout'], artist.casefold(), release.casefold()))
                files.append({'id': track_id, 'revision': revision(path), 'name': path.name, 'metadata': tags, 'inferred': details['inferred']})
        allow_album = all(i[0] == 'album' for i in identities) and len(set(identities)) == 1
        allowed = ['artist', 'album_artist', 'genre', 'date'] + (['album'] if allow_album else [])
        common = {k: files[0]['metadata'].get(k, '') if len({f['metadata'].get(k, '') for f in files}) == 1 else None for k in allowed}
        plan_id = uuid.uuid4().hex
        with self.lock:
            now = time.time()
            self.bulk_plans = {k:p for k,p in self.bulk_plans.items() if p.get('status') == 'running' or p['created'] > now - 3600}
            self.bulk_plans[plan_id] = {'id': plan_id, 'created': now, 'files': files, 'allowed': allowed,
                                      'status': 'ready', 'completed': 0, 'results': [], 'error': ''}
        return {'id': plan_id, 'count': len(files), 'common': common, 'allowed': allowed,
                'allow_album': allow_album, 'names': [f['name'] for f in files],
                'inferred_count': sum(bool(f['inferred']) for f in files)}

    def start_bulk(self, value):
        changes = validate_metadata(value.get('metadata', {}))
        fill_missing = value.get('fill_missing_from_filename') is True
        with self.lock:
            plan = self.bulk_plans.get(value.get('id'))
            if not plan or plan['status'] != 'ready' or plan['created'] < time.time() - 900:
                raise ValueError('This bulk edit has expired or already started. Select the tracks again.')
            if (not changes and not fill_missing) or any(k not in plan['allowed'] for k in changes):
                raise ValueError('Choose only permitted shared metadata fields. Titles, track numbers and single names cannot be bulk changed.')
            plan['status'] = 'running'
        def run():
            try:
                with self.tag_lock:
                    # Validate every file before changing any file.
                    for item in plan['files']:
                        _, path = self.track(item['id'])
                        if revision(path) != item['revision']:
                            raise ValueError('A selected file changed. No changes were made. Reopen the bulk editor.')
                    for item in plan['files']:
                        if self.stopping.is_set():
                            raise ValueError('Server stopped. Completed files were saved; unprocessed files are unchanged.')
                        try:
                            self.edit_metadata({'id': item['id'], 'revision': item['revision'], 'metadata': changes, 'layout': 'keep'}, infer_missing=fill_missing)
                            result = {'name': item['name'], 'ok': True}
                        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                            result = {'name': item['name'], 'ok': False, 'error': str(exc)}
                        with self.lock:
                            plan['results'].append(result)
                            plan['completed'] += 1
            except Exception as exc:
                with self.lock:
                    plan['error'] = str(exc)
            finally:
                with self.lock:
                    plan['status'] = 'done'
        threading.Thread(target=run, daemon=True).start()
        return {'id': plan['id'], 'started': True}

    def bulk_status(self, plan_id):
        with self.lock:
            plan = self.bulk_plans.get(plan_id)
            if not plan:
                raise ValueError('Bulk edit status unavailable. If the server restarted, check your library before retrying.')
            return {'id': plan_id, 'status': plan['status'], 'total': len(plan['files']),
                    'completed': plan['completed'], 'results': list(plan['results']), 'error': plan['error']}

    def stop(self):
        self.stopping.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        if self.worker:
            self.worker.join(timeout=10)

    def work(self):
        while not self.stopping.is_set():
            try:
                job_id = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.lock:
                job = next(j for j in self.jobs if j['id'] == job_id)
            try:
                self.convert(job)
            except Exception as exc:
                self.update(job, status='queued' if self.stopping.is_set() else 'failed', error=str(exc)[:1000])
            finally:
                if not self.stopping.is_set() or job['status'] == 'done':
                    (self.incoming / job_id).unlink(missing_ok=True)
                self.queue.task_done()

    def convert(self, job):
        source = self.incoming / job['id']
        root = check_directory(Path(job.get('library_root', job['destination'])))
        dest = root
        self.update(job, status='checking', progress=0)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,bits_per_raw_sample:format=duration', '-of', 'json', str(source)], capture_output=True, text=True, timeout=60)
        if probe.returncode:
            raise ValueError('This file could not be read as audio. The upload may be damaged or protected.')
        info = json.loads(probe.stdout)
        audio = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), None)
        if not audio:
            raise ValueError('No audio track found.')
        duration = float(info.get('format', {}).get('duration') or 0)
        output_format = job.get('output_format', 'mp3')
        if output_format not in ('mp3', 'flac'):
            raise ValueError('Choose MP3 or FLAC output.')
        if output_format == 'flac' and (audio['codec_name'].startswith('pcm_f') or int(audio.get('bits_per_raw_sample') or 0) > 24):
            raise ValueError('FLAC conversion supports integer audio up to 24 bits here. Keep this higher-precision source unchanged.')
        extension = '.' + output_format
        copy = Path(job['name']).suffix.lower() == extension and audio['codec_name'] == output_format
        fd, tmp = tempfile.mkstemp(prefix='.mediadrop-', suffix=extension, dir=dest)
        os.close(fd)
        temp = Path(tmp)
        try:
            if copy:
                shutil.copyfile(source, temp)
            else:
                self.update(job, status='converting')
                encoding = ['-c:a', 'flac', '-compression_level', '8'] if output_format == 'flac' else ['-ac', '2', '-ar', '44100', '-c:a', 'libmp3lame', '-b:a', '320k', '-id3v2_version', '3']
                cmd = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-map', '0:a:0', '-map_metadata', '0', '-vn', *encoding, '-progress', 'pipe:1', '-nostats', str(temp)]
                with tempfile.TemporaryFile() as log:
                    with self.lock:
                        if self.stopping.is_set():
                            raise ValueError('Server is stopping.')
                        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True)
                        self.process = proc
                    try:
                        last = 0
                        for line in proc.stdout:
                            if line.startswith('out_time_us=') and duration:
                                try:
                                    progress = min(99, round(int(line.split('=', 1)[1]) / 1e6 / duration * 100))
                                except ValueError:
                                    continue
                                if progress != last:
                                    self.update(job, progress=progress)
                                    last = progress
                        code = proc.wait()
                        if code:
                            log.seek(0)
                            detail = log.read(2000).decode(errors='replace').strip()
                            raise ValueError('Conversion failed. ' + detail)
                    finally:
                        if proc.poll() is None:
                            proc.kill()
                            proc.wait()
                        proc.stdout.close()
                        with self.lock:
                            self.process = None
            overrides = validate_metadata(job.get('metadata', {}))
            suppressed = {k for k,v in overrides.items() if k in ('artist','title') and not v}
            effective, inferred = metadata_from_filename(job['name'], {**read_tags(temp), **overrides}, blocked=set(overrides))
            defaults = single_release_defaults(effective, blocked=set(overrides)) if job.get('layout') == 'single' else {}
            updates = {**inferred, **defaults, **overrides}
            if updates:
                tag_temp = temp.with_name(temp.stem + '-tags' + extension)
                try:
                    write_tags(temp, tag_temp, updates)
                    os.replace(tag_temp, temp)
                finally:
                    tag_temp.unlink(missing_ok=True)
            metadata = read_tags(temp)
            dest = organised_folder(root, metadata, job.get('layout', 'flat'))
            if dest != temp.parent:
                moved = dest / temp.name
                shutil.move(str(temp), moved)
                temp = moved
            check_directory(dest)
            output = publish(temp, dest, Path(job['name']).stem + extension)
            self.index_path(root, output, metadata, suppressed, job.get('layout'))
            self.update(job, status='done', progress=100, output=output.name, bytes=output.stat().st_size, converted=not copy, metadata=metadata, destination=str(dest), library_root=str(root))
        finally:
            temp.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    server_version = 'MediaDrop/1.6'

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def reply(self, status, value):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == '/api/health':
            return self.reply(200, {'status': 'ok', 'version': '1.6'})
        if route.startswith('/api/jobs/'):
            job_id = route.removeprefix('/api/jobs/')
            with self.app.lock:
                job = next((j for j in self.app.jobs if j['id'] == job_id), None)
                result = {k: job[k] for k in ('id', 'status', 'progress', 'error') if k in job} if job else None
            return self.reply(200, result) if result else self.reply(404, {'error': 'Upload job not found. Check the server before uploading again.'})
        if route == '/api/state':
            with self.app.lock:
                folders = [dict(f, available=Path(f['path']).is_dir()) for f in self.app.config['folders']]
                jobs = [{k: v for k, v in j.items() if k != 'destination'} for j in self.app.jobs[-100:]]
            return self.reply(200, {'folders': folders, 'jobs': jobs, 'conversion': bool(shutil.which('ffmpeg') and shutil.which('ffprobe')), 'artwork': self.app.artwork.public()})
        if route == '/api/artwork/image':
            try:
                payload, mime = self.app.artwork.image(parse_qs(urlsplit(self.path).query).get('id', [''])[0])
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (ValueError, OSError) as exc:
                self.reply(404, {'error': str(exc)})
            return
        if route == '/api/bulk/status':
            try:
                plan_id = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                return self.reply(200, self.app.bulk_status(plan_id))
            except ValueError as exc:
                return self.reply(400, {'error': str(exc)})
        if route == '/api/library':
            args = parse_qs(urlsplit(self.path).query)
            query = args.get('q', [''])[0].casefold()[:300]
            folder_id = args.get('folder', [''])[0]
            try:
                page = max(0, int(args.get('page', ['0'])[0]))
            except ValueError:
                return self.reply(400, {'error': 'Invalid page.'})
            with self.app.lock:
                folder_map = {f['id']: f for f in self.app.config['folders'] if f['type'] == 'music'}
                items = [dict(v) for v in self.app.library.values() if v['folder_id'] in folder_map and (not folder_id or v['folder_id'] == folder_id)]
                scan = dict(self.app.scan_state)
            if query:
                items = [v for v in items if query in (' '.join(v['metadata'].values()) + ' ' + v['relative']).casefold()]
            for item in items:
                item['folder'] = folder_map[item['folder_id']]['name']
                names = split_artists(item['metadata'].get('artist'))
                item['credits'] = [{'name':name,'key':name.casefold()} for name in names] if names else library_credits(item)
            view = args.get('view', [''])[0]
            if view:
                if view not in ('artists', 'releases', 'tracks'):
                    return self.reply(400, {'error': 'Invalid library view.'})
                track_total = len(items)
                result = browse_library(items, view, args.get('artist', [''])[0], args.get('release', [''])[0])
                total = len(result)
                for entry in result:
                    if view == 'artists':
                        entry['image'] = self.app.artwork.url_for(entry['name'])
                    elif view == 'releases':
                        entry['image'] = self.app.artwork.url_for(entry['artist'], entry['name'])
                per_page = 50 if view == 'tracks' else 24
                return self.reply(200, {'view': view, 'items': result[page * per_page:(page + 1) * per_page],
                                       'total': total, 'track_total': track_total, 'page': page,
                                       'page_size': per_page, 'scan': scan})
            items.sort(key=lambda v: (v['metadata'].get('artist', '').casefold(), v['metadata'].get('album', '').casefold(), v['name'].casefold()))
            total = len(items)
            return self.reply(200, {'tracks': items[page * 50:(page + 1) * 50], 'total': total, 'page': page, 'scan': scan})
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/style.css': ('style.css', 'text/css'), '/app.js': ('app.js', 'application/javascript')}
        if route not in files:
            return self.reply(404, {'error': 'Not found.'})
        name, mime = files[route]
        content = (ROOT / 'web' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        self.connection.settimeout(120)
        try:
            # Custom request header plus same-origin checks block drive-by form uploads.
            origin = self.headers.get('Origin')
            if self.headers.get('X-MediaDrop') != '1' or (origin and origin != 'http://' + self.headers.get('Host', '')):
                return self.reply(403, {'error': 'Request blocked. Open MediaDrop directly.'})
            route = urlsplit(self.path).path
            if route == '/api/upload':
                return self.upload()
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Expected JSON.')
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 65536:
                raise ValueError('Request is too large.')
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError('Expected a settings object.')
            if route == '/api/artwork/settings':
                settings = validate_settings(value, self.app.config.get('artwork', {}))
                self.app.artwork.configure(settings)
                with self.app.lock:
                    self.app.config['artwork'] = settings
                    self.app.save_config()
                self.app.artwork.sync()
                return self.reply(200, {'ok': True})
            if route == '/api/artwork/sync':
                return self.reply(202, {'started': self.app.artwork.sync()})
            if route == '/api/bulk/prepare':
                return self.reply(200, self.app.prepare_bulk(value))
            if route == '/api/bulk/save':
                return self.reply(202, self.app.start_bulk(value))
            if route == '/api/library/scan':
                return self.reply(202, {'started': self.app.scan()})
            if route == '/api/metadata/read':
                with self.app.tag_lock:
                    job, path = self.app.track(value.get('id'))
                    details = self.app.read_metadata(job, path)
                    return self.reply(200, {'metadata': details['metadata'], 'inferred': details['inferred'], 'revision': revision(path), 'path': str(path)})
            if route == '/api/metadata/save':
                return self.reply(200, self.app.edit_metadata(value))
            if route == '/api/folders':
                name = str(value.get('name', '')).strip()
                raw = str(value.get('path', '')).strip()
                if not name or len(name) > 80 or not raw:
                    raise ValueError('Enter a folder name and its full path on the server Mac.')
                path = Path(raw).expanduser()
                if not path.is_absolute():
                    raise ValueError('Use an absolute path, for example /Volumes/Media/Music.')
                path = check_directory(path.resolve())
                with self.app.lock:
                    if len(self.app.config['folders']) >= 50:
                        raise ValueError('Maximum of 50 destinations reached.')
                    self.app.config['folders'].append({'id': uuid.uuid4().hex, 'name': name, 'path': str(path), 'type': 'music'})
                    self.app.save_config()
                self.app.scan()
                return self.reply(201, {'ok': True})
            if route == '/api/folders/remove':
                with self.app.lock:
                    self.app.config['folders'] = [f for f in self.app.config['folders'] if f['id'] != value.get('id')]
                    self.app.save_config()
                return self.reply(200, {'ok': True})
            return self.reply(404, {'error': 'Not found.'})
        except (ValueError, OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
            self.reply(400, {'error': str(exc)})

    def upload(self):
        if not self.app.upload_slots.acquire(blocking=False):
            return self.reply(429, {'error': 'Three uploads are already running. Try again shortly.'})
        source = None
        upload_id = None
        reserved = False
        try:
            args = parse_qs(urlsplit(self.path).query)
            name = safe_name(args.get('name', [''])[0])
            encoded = self.headers.get('X-MediaDrop-Tags', '%7B%7D')
            if len(encoded) > 30000:
                raise ValueError('Metadata is too large.')
            metadata = validate_metadata(json.loads(unquote(encoded)))
            output_format = args.get('format', ['mp3'])[0]
            if output_format not in ('mp3', 'flac'):
                raise ValueError('Choose MP3 or FLAC output.')
            layout = args.get('layout', ['flat'])[0]
            if layout not in ('flat', 'album', 'single'):
                raise ValueError('Invalid folder layout.')
            if layout != 'flat':
                preview, _ = metadata_from_filename(name, metadata, blocked=set(metadata))
                artist = primary_artist(preview)
                release = preview.get('album') or (preview.get('title') if layout == 'single' else '')
                # Embedded tags are read after upload; don't reject tagged files
                # just because their filename cannot supply every value.
                if artist:
                    folder_part(artist)
                if release:
                    folder_part(release)
            folder = self.app.folder(args.get('folder', [''])[0])
            if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
                raise ValueError('Install FFmpeg on the server Mac, then restart MediaDrop.')
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 10 * 1024 ** 3:
                raise ValueError('Choose a non-empty file smaller than 10 GB.')
            upload_id = self.headers.get('X-MediaDrop-Upload-ID')
            fingerprint = hashlib.sha256(json.dumps([folder['id'], name, metadata, layout, length] + ([output_format] if output_format != 'mp3' else []), sort_keys=True).encode()).hexdigest()
            if upload_id:
                if not re.fullmatch(r'[A-Za-z0-9-]{16,80}', upload_id):
                    raise ValueError('Invalid upload identifier.')
                with self.app.lock:
                    existing = next((j for j in self.app.jobs if j.get('client_upload_id') == upload_id), None)
                    if existing:
                        if existing.get('upload_fingerprint') != fingerprint:
                            raise ValueError('This upload identifier already belongs to a different file or destination.')
                        return self.reply(202, {'job': existing['id'], 'reused': True})
                    if upload_id in self.app.active_uploads:
                        return self.reply(409, {'error': 'This upload is already being received. Retry shortly.'})
                    self.app.active_uploads.add(upload_id)
                    reserved = True
            if shutil.disk_usage(self.app.incoming).free < length + 128 * 1024 ** 2:
                raise ValueError('The server has insufficient space for this upload.')
            job_id = uuid.uuid4().hex
            source = self.app.incoming / job_id
            with source.open('xb') as stream:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError('Upload interrupted. Please try again.')
                    stream.write(chunk)
                    remaining -= len(chunk)
            job = {'id': job_id, 'name': name, 'folder': folder['name'], 'destination': folder['path'], 'status': 'queued', 'progress': 0, 'created': time.time(), 'bytes': length, 'metadata': metadata, 'layout': layout, 'library_root': folder['path']}
            job['output_format'] = output_format
            if upload_id:
                job.update(client_upload_id=upload_id, upload_fingerprint=fingerprint)
            with self.app.lock:
                self.app.jobs.append(job)
                self.app.save_jobs()
            source = None
            self.app.queue.put(job_id)
            self.reply(202, {'job': job_id})
        finally:
            if source:
                source.unlink(missing_ok=True)
            if reserved:
                with self.app.lock:
                    self.app.active_uploads.discard(upload_id)
            self.app.upload_slots.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=12345)
    parser.add_argument('--data', default=os.environ.get('MEDIADROP_DATA', str(Path.home() / 'Library/Application Support/MediaDrop')))
    args = parser.parse_args()
    os.umask(0o077)
    # Prevent two instances from processing the same queue (macOS and Linux).
    import fcntl
    data = Path(args.data).expanduser()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_file = (data / 'server.lock').open('a')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('MediaDrop is already running. Open http://localhost:12345')
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.app = App(data)
    server.app.scan()
    print('\nMediaDrop is ready\n', flush=True)
    print(f'  This Mac:     http://localhost:{args.port}')
    if os.environ.get('MEDIADROP_CONTAINER'):
        print(f'  Your network: http://YOUR-MAC-IP:{args.port}')
    else:
        print(f'  Your network: http://{socket.gethostname().removesuffix(".local")}.local:{args.port}')
    if os.environ.get('MEDIADROP_CONTAINER'):
        print('Running in Docker. Settings and queue are stored in /data.\nKeep this service on your trusted local network.\n', flush=True)
    else:
        print('Leave this window open. Press Ctrl+C to stop.\nKeep this service on your trusted local network.\n', flush=True)
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nMediaDrop stopped. Queued conversions resume next time.')
    finally:
        server.app.stop()
        server.server_close()


if __name__ == '__main__':
    main()
