import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode, quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import App, Handler, safe_name, read_tags, organised_folder, browse_library, ROOT


class Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dest = self.root / 'Music'
        self.dest.mkdir()
        self.app = App(self.root / 'data')
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.app = self.app
        self.port = self.http.server_port
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.app.queue.join()
        self.app.stop()
        self.http.shutdown()
        self.http.server_close()
        self.temp.cleanup()

    def request(self, path, body=None, raw=None, origin=None, metadata=None, trusted=True):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        headers = {'X-MediaDrop': '1'} if trusted else {}
        if metadata is not None:
            headers['X-MediaDrop-Tags'] = quote(json.dumps(metadata))
        if origin:
            headers['Origin'] = origin
        payload = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        headers['Content-Type'] = 'application/octet-stream' if raw is not None else 'application/json'
        client.request('POST' if payload is not None else 'GET', path, payload, headers)
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    def folder(self):
        self.assertEqual(self.request('/api/folders', {'name': 'My music', 'path': str(self.dest)})[0], 201)
        return self.app.config['folders'][0]['id']

    def wav(self):
        path = self.root / 'source.wav'
        with wave.open(str(path), 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(44100)
            f.writeframes(b'\0\0' * 44100)
        return path.read_bytes()

    def upload(self, folder, name, data):
        return self.request('/api/upload?' + urlencode({'folder': folder, 'name': name}), raw=data)

    def test_wav_conversion_mp3_copy_and_duplicate(self):
        folder = self.folder()
        self.assertEqual(self.upload(folder, 'Test track.wav', self.wav())[0], 202)
        self.app.queue.join()
        self.assertEqual(self.app.jobs[-1]['status'], 'done', self.app.jobs[-1])
        first = self.dest / 'Test track.mp3'
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(first)]))
        self.assertEqual(probe['streams'][0]['codec_name'], 'mp3')
        payload = first.read_bytes()
        self.assertEqual(self.upload(folder, 'Test track.mp3', payload)[0], 202)
        self.app.queue.join()
        self.assertEqual((self.dest / 'Test track (1).mp3').read_bytes(), payload)
        self.assertEqual(first.read_bytes(), payload)
        self.assertFalse(self.app.jobs[-1]['converted'])
        self.assertEqual(list(self.app.incoming.iterdir()), [])

    def test_password_free_access_origin_and_folder_validation(self):
        self.assertEqual(self.request('/api/state')[0], 200)
        self.assertEqual(self.request('/api/folders', {'name':'Bad','path':str(self.dest)}, trusted=False)[0],403)
        self.assertEqual(self.request('/api/folders', {'name':'Bad','path':'relative'})[0], 400)
        self.assertEqual(self.request('/api/folders', {'name':'Bad','path':str(self.root/'missing')})[0], 400)
        self.assertEqual(self.request('/api/folders', {'name':'Bad','path':str(self.dest)}, origin='http://evil.example')[0], 403)
        folder = self.folder()
        self.assertEqual(self.upload(folder, '../escape.wav', self.wav())[0], 400)
        self.app.config['folders'][0]['type'] = 'films'
        self.assertEqual(self.upload(folder, 'song.wav', self.wav())[0], 400)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_invalid_audio_is_failed_and_source_removed(self):
        folder = self.folder()
        self.assertEqual(self.upload(folder, 'Not audio.wav', b'not a wav')[0], 202)
        self.app.queue.join()
        self.assertEqual(self.app.jobs[-1]['status'], 'failed')
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(list(self.app.incoming.iterdir()), [])

    def test_missing_external_folder_not_recreated(self):
        folder = self.folder()
        self.dest.rmdir()
        self.assertEqual(self.upload(folder, 'song.wav', self.wav())[0], 400)
        self.assertFalse(self.dest.exists())

    def test_restart_recovers_queued_jobs(self):
        app = App(self.root / 'recovery', worker=False)
        job = {'id':'abc', 'name':'Recover.wav', 'folder':'Music', 'destination':str(self.dest), 'status':'converting', 'progress':42, 'bytes':10}
        (app.incoming / 'abc').write_bytes(self.wav())
        app.jobs.append(job)
        app.save_jobs()
        recovered = App(self.root / 'recovery', worker=False)
        self.assertEqual(recovered.jobs[0]['status'], 'queued')
        self.assertEqual(recovered.queue.get_nowait(), 'abc')
        recovered.convert(recovered.jobs[0])
        self.assertEqual(recovered.jobs[0]['status'], 'done')
        self.assertTrue((self.dest / 'Recover.mp3').is_file())

    def scan_wait(self):
        self.app.scan()
        limit = time.time() + 10
        while self.app.scan_state['running'] and time.time() < limit:
            time.sleep(0.02)
        self.assertFalse(self.app.scan_state['running'])

    def audio_payload(self, path):
        return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-c', 'copy', '-f', 'data', '-'])

    def test_320k_upload_tags_and_album_layout(self):
        folder = self.folder()
        tags = {'title':'My title', 'artist':'Björk', 'album':'A record', 'album_artist':'Björk', 'track':'1/12', 'disc':'1/2', 'date':'2026', 'genre':'Electronic'}
        code, response = self.request('/api/upload?' + urlencode({'folder':folder, 'name':'Song.wav', 'layout':'album'}), raw=self.wav(), metadata=tags)
        self.assertEqual(code, 202, response)
        self.app.queue.join()
        job = self.app.jobs[-1]
        self.assertEqual(job['status'], 'done', job)
        output = self.dest / 'Björk' / 'A record' / 'Song.mp3'
        self.assertTrue(output.is_file())
        self.assertEqual(read_tags(output), tags)
        probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=bit_rate','-of','json',str(output)]))
        self.assertEqual(int(probe['streams'][0]['bit_rate']), 320000)
        self.assertFalse((self.dest/'Björk'/'Albums').exists())

    def test_existing_library_scan_edit_move_and_conflict(self):
        folder = self.folder()
        artist = self.dest/'An artist'
        artist.mkdir()
        wav = self.root/'input.wav'
        wav.write_bytes(self.wav())
        single = artist/'Single.mp3'
        subprocess.run(['ffmpeg','-v','error','-i',str(wav),'-c:a','libmp3lame','-b:a','320k','-metadata','artist=An artist','-metadata','title=Old title',str(single)],check=True)
        album = artist/'An album'
        album.mkdir()
        album_track = album/'Album track.mp3'
        album_track.write_bytes(single.read_bytes())
        self.scan_wait()
        code, library = self.request('/api/library')
        self.assertEqual(code, 200)
        self.assertEqual(library['total'],2)
        record = next(t for t in library['tracks'] if t['name']=='Single.mp3')
        self.assertEqual(record['layout'],'single')
        self.assertEqual(next(t for t in library['tracks'] if t['name']=='Album track.mp3')['layout'],'album')
        before = self.audio_payload(single)
        _, editor = self.request('/api/metadata/read',{'id':record['id']})
        request = {'id':record['id'],'revision':editor['revision'],'metadata':{'title':'New title','album':'New album'},'folder':folder,'layout':'album'}
        code, saved = self.request('/api/metadata/save', request)
        self.assertEqual(code,200,saved)
        moved=artist/'New album'/'Single.mp3'
        self.assertFalse(single.exists())
        self.assertEqual(self.audio_payload(moved), before)
        self.assertEqual(read_tags(moved)['title'],'New title')
        _, updated=self.request('/api/library?q=New+title')
        self.assertEqual(updated['total'],1)
        new_id=updated['tracks'][0]['id']
        _, editor=self.request('/api/metadata/read',{'id':new_id})
        request={'id':new_id,'revision':editor['revision'],'metadata':{'genre':'Rock'},'layout':'keep'}
        self.assertEqual(self.request('/api/metadata/save',request)[0],200)
        self.assertEqual(self.request('/api/metadata/save',request)[0],400)
        _, editor=self.request('/api/metadata/read',{'id':new_id})
        self.assertEqual(self.request('/api/metadata/save',{'id':new_id,'revision':editor['revision'],'metadata':{'title':''},'layout':'keep'})[0],200)
        self.assertEqual(read_tags(moved)['title'],'')

    def test_scan_removes_deleted_and_excludes_symlinks(self):
        self.folder()
        self.upload(self.app.config['folders'][0]['id'],'Known.wav', self.wav())
        self.app.queue.join()
        (self.dest/'outside.mp3').symlink_to(self.root/'source.wav')
        self.scan_wait()
        self.assertEqual(self.request('/api/library')[1]['total'],1)
        (self.dest/'Known.mp3').unlink()
        self.scan_wait()
        self.assertEqual(self.request('/api/library')[1]['total'],0)

    def test_tags_rejected_before_upload_and_folder_sanitization(self):
        folder=self.folder()
        path='/api/upload?'+urlencode({'folder':folder,'name':'Bad.wav','layout':'single'})
        self.assertEqual(self.request(path,raw=self.wav(),metadata={'artist':'x','bad':'value'})[0],400)
        self.assertEqual(self.request(path,raw=self.wav(),metadata={'track':'-1'})[0],400)
        out=organised_folder(self.dest,{'artist':'../Artist','album':'A/B'},'album')
        self.assertTrue(out.is_relative_to(self.dest))
        single=organised_folder(self.dest,{'artist':'Artist'},'single')
        self.assertEqual(single,self.dest/'Artist')
        outside=self.root/'elsewhere'
        outside.mkdir()
        (self.dest/'Escape').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):
            organised_folder(self.dest,{'artist':'Escape','album':'Album'},'album')


    def test_artist_release_browsing_covers_full_library(self):
        folder = self.folder()
        self.scan_wait()
        with self.app.lock:
            for number in range(60):
                self.app.library[str(number)] = {'id':str(number),'folder_id':folder,'name':f'{number}.mp3',
                    'relative':f'Artist/Album/{number}.mp3','layout':'album',
                    'metadata':{'artist':'Guest singer','album_artist':'An artist','album':'An album',
                                'track':str(number+1),'disc':'1','date':'2026'}}
            self.app.library['single'] = {'id':'single','folder_id':folder,'name':'Single.mp3',
                'relative':'Artist/Single.mp3','layout':'single',
                'metadata':{'artist':'An artist','title':'A single'}}
        _, artists = self.request('/api/library?view=artists')
        self.assertEqual(artists['total'], 1)
        artist = artists['items'][0]
        self.assertEqual(artist['track_count'],61)
        self.assertEqual(artist['release_count'],2)
        _, releases = self.request('/api/library?'+urlencode({'view':'releases','artist':artist['key']}))
        self.assertEqual(releases['total'],2)
        album = next(r for r in releases['items'] if r['kind']=='album')
        self.assertEqual(album['track_count'],60)
        _, tracks = self.request('/api/library?'+urlencode({'view':'tracks','artist':artist['key'],'release':album['key'],'page':'1'}))
        self.assertEqual(tracks['total'],60)
        self.assertEqual(len(tracks['items']),10)
        self.assertEqual(tracks['items'][0]['metadata']['track'],'51')
        _, search = self.request('/api/library?'+urlencode({'view':'artists','q':'A single'}))
        self.assertEqual(search['track_total'],1)
        self.assertEqual(self.request('/api/library?view=invalid')[0],400)


    def test_healthcheck_is_public_and_contains_no_settings(self):
        code,health = self.request('/api/health')
        self.assertEqual(code,200)
        self.assertEqual(health,{'status':'ok','version':'1.3'})
        self.assertEqual(self.request('/api/state')[0],200)

    def test_container_data_environment_and_sigterm_shutdown(self):
        import os
        data = self.root/'container-settings'
        env = dict(os.environ, MEDIADROP_DATA=str(data), MEDIADROP_CONTAINER='1', PYTHONUNBUFFERED='1')
        proc = subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--host','127.0.0.1','--port','0'], env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            import select
            ready,_,_ = select.select([proc.stdout],[],[],10)
            self.assertTrue(ready,'Server startup timed out.')
            deadline=time.time()+5
            while not (data/'config.json').exists() and time.time()<deadline:
                time.sleep(.01)
            self.assertTrue((data/'config.json').is_file())
            proc.terminate()
            stdout,stderr = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode,0,stderr)
            self.assertNotIn('.local:',stdout)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


    def test_legacy_password_removed_without_losing_settings(self):
        data=self.root/'legacy'
        data.mkdir()
        folder={'id':'original','name':'Original folder','type':'music','path':str(self.dest)}
        (data/'config.json').write_text(json.dumps({'password':'old-password','folders':[folder]}))
        app=App(data,worker=False)
        self.assertNotIn('password',app.config)
        self.assertNotIn('password',json.loads((data/'config.json').read_text()))
        self.assertEqual(app.config['folders'],[folder])
        self.assertEqual(self.request('/api/login',{'password':'anything'})[0],404)
        self.assertEqual(self.request('/api/logout',{})[0],404)


if __name__ == '__main__':
    unittest.main()
