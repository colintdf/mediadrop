"""Read-only Plex/Lidarr artwork lookup. Credentials never reach the browser."""
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from artists import split_artists


def normalise(value):
    return ' '.join(str(value or '').split()).casefold()


def identity(artist, release=None):
    return ('artist:' if release is None else 'release:') + normalise(artist) + ('' if release is None else '\0' + normalise(release))


def validate_settings(value, previous):
    provider = value.get('provider', 'none')
    if provider not in ('none', 'plex', 'lidarr'):
        raise ValueError('Choose Plex, Lidarr or no artwork provider.')
    if provider == 'none':
        return {'provider': 'none', 'url': '', 'credential': '', 'section': ''}
    url = str(value.get('url', '')).strip().rstrip('/')
    parsed = urllib.parse.urlsplit(url)
    try:
        valid = parsed.scheme in ('http', 'https') and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment or any(ord(c) < 33 for c in url):
        raise ValueError('Enter a server URL such as http://192.168.1.20:32400 without a token in the URL.')
    credential = value.get('credential', '')
    if not isinstance(credential, str) or len(credential) > 1024 or any(ord(c) < 33 for c in credential):
        raise ValueError('Enter a valid token or API key.')
    if not credential and previous.get('provider') == provider and previous.get('url') == url:
        credential = previous.get('credential', '')
    if not credential:
        raise ValueError('Enter your Plex token or Lidarr API key.')
    section = str(value.get('section', '')).strip()
    if section and not section.isdigit():
        raise ValueError('Plex library section ID must be a number, or blank for all music libraries.')
    return {'provider': provider, 'url': url, 'credential': credential, 'section': section}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Artwork:
    def __init__(self, data, settings):
        self.data = Path(data) / 'artwork'
        self.data.mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.sync_lock = threading.Lock()
        self.fetch_slots = threading.BoundedSemaphore(4)
        self.settings = dict(settings)
        self.catalog = {}
        self.matches = {}
        self.status = {'running': False, 'matched': 0, 'error': '', 'updated': 0}
        stored = self.data / 'index.json'
        if stored.exists():
            try:
                saved = json.loads(stored.read_text())
                if saved.get('fingerprint') == self.fingerprint():
                    self.catalog = saved['catalog']
                    self.matches = saved['matches']
                    self.status.update(matched=len(self.matches), updated=saved.get('updated', 0))
            except (ValueError, KeyError):
                pass

    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.settings, sort_keys=True).encode()).hexdigest()

    def public(self):
        with self.lock:
            return {k:v for k,v in self.settings.items() if k != 'credential'} | {'has_credential': bool(self.settings.get('credential')), 'status': dict(self.status)}

    def configure(self, settings):
        with self.lock:
            if self.status['running']:
                raise ValueError('Wait for the artwork sync to finish before changing the connection.')
            if settings != self.settings:
                self.settings = dict(settings)
                self.catalog = {}
                self.matches = {}
                self.status = {'running': False, 'matched': 0, 'error': '', 'updated': 0}

    def request(self, path, limit=32 * 1024 ** 2):
        if not path.startswith('/') or path.startswith('//') or '\\' in path or urllib.parse.urlsplit(path).scheme:
            raise ValueError('Invalid artwork server path.')
        settings = self.settings
        headers = {'Accept': 'application/json', 'User-Agent': 'MediaDrop/1.4'}
        headers['X-Plex-Token' if settings['provider'] == 'plex' else 'X-Api-Key'] = settings['credential']
        request = urllib.request.Request(settings['url'] + path, headers=headers)
        try:
            # Never forward credentials across a redirect.
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
                payload = response.read(limit + 1)
                if len(payload) > limit:
                    raise ValueError('Artwork server response was too large.')
                return payload
        except urllib.error.HTTPError as exc:
            raise ValueError(f'Artwork server returned HTTP {exc.code}. Check the URL and credentials.') from None
        except (OSError, urllib.error.URLError):
            raise ValueError('Could not connect to the artwork server. Check its URL and that it is running.') from None

    def json(self, path):
        try:
            return json.loads(self.request(path))
        except json.JSONDecodeError:
            raise ValueError('Artwork server did not return valid JSON. Check the server URL.') from None

    def sync(self):
        if not self.sync_lock.acquire(blocking=False):
            return False
        with self.lock:
            self.status.update(running=True, error='')
        def run():
            try:
                candidates = {}
                catalog = {}
                def add(artist, release, path):
                    if not artist or not path:
                        return
                    key = identity(artist, release)
                    image_id = hashlib.sha256((self.settings.get('provider', '') + self.settings.get('url', '') + path).encode()).hexdigest()
                    catalog[image_id] = path
                    candidates.setdefault(key, set()).add(image_id)
                if self.settings.get('provider') == 'lidarr':
                    self.load_lidarr(add)
                elif self.settings.get('provider') == 'plex':
                    self.load_plex(add)
                matches = {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}
                now = time.time()
                with self.lock:
                    self.matches = matches
                    self.catalog = catalog
                    self.status.update(matched=len(matches), updated=now)
                    temp = self.data / 'index.tmp'
                    temp.write_text(json.dumps({'fingerprint': self.fingerprint(), 'matches': matches, 'catalog': catalog, 'updated': now}))
                    temp.replace(self.data / 'index.json')
            except Exception as exc:
                with self.lock:
                    self.status['error'] = str(exc)[:300]
            finally:
                with self.lock:
                    self.status['running'] = False
                self.sync_lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True

    @staticmethod
    def lidarr_image(record, category):
        preferred = 'poster' if category == 'artist' else 'cover'
        image = next((i for i in record.get('images', []) if i.get('coverType', '').lower() == preferred), None)
        if not image or not isinstance(record.get('id'), int):
            return None
        filename = Path(urllib.parse.urlsplit(image.get('url') or image.get('remoteUrl') or '').path).name
        if not re.fullmatch(r'(poster|cover)(-\d+)?\.(jpg|jpeg|png|webp)', filename, re.I):
            filename = preferred + '.jpg'
        return f'/api/v1/mediacover/{category}/{record["id"]}/{filename}'

    def load_lidarr(self, add):
        artists = self.json('/api/v1/artist')
        if not isinstance(artists, list):
            raise ValueError('Unexpected Lidarr artist response.')
        names = {}
        for artist in artists:
            name = artist.get('artistName', '')
            names[artist.get('id')] = name
            add(name, None, self.lidarr_image(artist, 'artist'))
        albums = self.json('/api/v1/album')
        if not isinstance(albums, list):
            raise ValueError('Unexpected Lidarr album response.')
        for album in albums:
            artist = names.get(album.get('artistId')) or album.get('artist', {}).get('artistName')
            add(artist, album.get('title', ''), self.lidarr_image(album, 'album'))

    def plex_items(self, section, media_type):
        start = 0
        while start < 200000:
            query = urllib.parse.urlencode({'type': media_type, 'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 500})
            container = self.json(f'/library/sections/{section}/all?{query}').get('MediaContainer', {})
            items = container.get('Metadata', container.get('Directory', []))
            if not isinstance(items, list):
                raise ValueError('Unexpected Plex library response.')
            yield from items
            start += len(items)
            total = container.get('totalSize')
            if not items or (total is not None and start >= int(total)) or (total is None and len(items) < 500):
                return
        raise ValueError('Plex library is too large to sync in one pass.')

    def load_plex(self, add):
        container = self.json('/library/sections').get('MediaContainer', {})
        sections = container.get('Directory', [])
        section_id = self.settings.get('section')
        sections = [s for s in sections if s.get('type') == 'artist' and (not section_id or str(s.get('key')) == section_id)]
        if not sections:
            raise ValueError('No accessible Plex music library found. Check its section ID and token.')
        for section in sections:
            key = str(section.get('key', ''))
            if not key.isdigit():
                continue
            for kind in (8, 9):
                for item in self.plex_items(key, kind):
                    thumb = item.get('thumb', '')
                    if not re.fullmatch(r'/library/metadata/\d+/(thumb|art)(/\d+)?', thumb):
                        continue
                    artist = item.get('title', '') if kind == 8 else item.get('parentTitle', '')
                    add(artist, None if kind == 8 else item.get('title', ''), thumb)

    def url_for(self, artist, release=None):
        with self.lock:
            key = self.matches.get(identity(artist, release))
            names = split_artists(artist)
            if not key and len(names) > 1:
                key = self.matches.get(identity(names[0], release))
            return '/api/artwork/image?id=' + key if key else None

    def image(self, image_id):
        if not re.fullmatch(r'[a-f0-9]{64}', image_id):
            raise ValueError('Unknown image.')
        with self.lock:
            path = self.catalog.get(image_id)
            if not path:
                raise ValueError('Unknown image.')
        cached = self.data / (image_id + '.img')
        with self.fetch_slots:
            fresh = cached.exists() and cached.stat().st_mtime >= self.status.get('updated', 0)
            if fresh:
                payload = cached.read_bytes()
            else:
                try:
                    payload = self.request(path, limit=10 * 1024 ** 2)
                except ValueError:
                    if not cached.exists():
                        raise
                    payload = cached.read_bytes()
                    fresh = True
            if payload.startswith(b'\xff\xd8\xff'):
                mime = 'image/jpeg'
            elif payload.startswith(b'\x89PNG\r\n\x1a\n'):
                mime = 'image/png'
            elif payload[:4] == b'RIFF' and payload[8:12] == b'WEBP':
                mime = 'image/webp'
            else:
                raise ValueError('Artwork server returned an unsupported image.')
            if not fresh:
                temp = cached.with_suffix('.' + str(threading.get_ident()) + '.tmp')
                try:
                    temp.write_bytes(payload)
                    temp.replace(cached)
                finally:
                    temp.unlink(missing_ok=True)
            return payload, mime
