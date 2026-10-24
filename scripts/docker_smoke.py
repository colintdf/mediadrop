"""Run inside a running container: upload real audio and verify the bind mount."""
import http.cookiejar
import io
import json
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request
import wave

base = 'http://127.0.0.1:12345'
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request(path, payload, raw=False):
    data = payload if raw else json.dumps(payload).encode()
    headers = {'X-MediaDrop': '1', 'Content-Type': 'application/octet-stream' if raw else 'application/json'}
    req = urllib.request.Request(base + path, data=data, headers=headers)
    with client.open(req, timeout=15) as response:
        return json.load(response)


password = json.loads(Path('/data/config.json').read_text())['password']
request('/api/login', {'password': password})
# Reuse the configured destination after the restart check.
with client.open(base + '/api/state') as response:
    state = json.load(response)
if not state['folders']:
    request('/api/folders', {'name': 'Container smoke test', 'path': '/music'})
    with client.open(base + '/api/state') as response:
        state = json.load(response)
folder = state['folders'][0]['id']
output = Path('/music/docker-smoke.mp3')
if not output.exists():
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(44100)
        stream.writeframes(b'\0\0' * 44100)
    upload = request('/api/upload?' + urllib.parse.urlencode({'folder': folder, 'name': 'docker-smoke.wav'}), audio.getvalue(), raw=True)
    for attempt in range(60):
        with client.open(base + '/api/state') as response:
            state = json.load(response)
        job = next(j for j in state['jobs'] if j['id'] == upload['job'])
        if job['status'] == 'failed':
            raise RuntimeError(job['error'])
        if job['status'] == 'done':
            break
        time.sleep(.25)
    else:
        raise RuntimeError('Conversion did not finish.')
assert output.is_file(), 'Converted file was not written to the mounted music folder.'
probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name,bit_rate', '-of', 'json', str(output)]))
assert probe['streams'][0]['codec_name'] == 'mp3'
assert int(probe['streams'][0]['bit_rate']) == 320000
assert password == json.loads(Path('/data/config.json').read_text())['password']
print('Container login, mounted music folder, 320 kbps conversion and saved settings passed.')
