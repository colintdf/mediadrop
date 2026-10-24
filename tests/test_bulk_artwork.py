import base64
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import test_server
from server import tag_args, read_tags
from artwork import Artwork, validate_settings


class BulkTests(unittest.TestCase):
    setUp = test_server.Integration.setUp
    tearDown = test_server.Integration.tearDown
    request = test_server.Integration.request
    login = test_server.Integration.login
    folder = test_server.Integration.folder
    wav = test_server.Integration.wav
    scan_wait = test_server.Integration.scan_wait
    audio_payload = test_server.Integration.audio_payload

    def tracks(self, album=False):
        self.login()
        self.folder()
        paths=[]
        for i in range(2):
            directory=self.dest/'An artist'
            if album:
                directory=directory/'An album'
            directory.mkdir(parents=True,exist_ok=True)
            path=directory/f'{i+1}.mp3'
            wav=self.root/f'{i}.wav'
            wav.write_bytes(self.wav())
            tags={'artist':'An artist','title':f'Title {i+1}','album':'An album' if album else f'Single {i+1}', 'track':str(i+1),'genre':f'Genre {i+1}'}
            subprocess.run(['ffmpeg','-v','error','-i',str(wav),'-c:a','libmp3lame','-b:a','320k',*tag_args(tags),str(path)],check=True)
            paths.append(path)
        self.scan_wait()
        return paths,list(self.app.library)

    def wait_bulk(self, plan_id):
        deadline=time.time()+15
        while time.time()<deadline:
            code,status=self.request('/api/bulk/status?id='+plan_id)
            self.assertEqual(code,200)
            if status['status']=='done':
                return status
            time.sleep(.02)
        self.fail('Bulk operation did not finish.')

    def test_singles_bulk_only_changes_explicit_shared_field(self):
        paths,ids=self.tracks()
        before=[self.audio_payload(p) for p in paths]
        code,plan=self.request('/api/bulk/prepare',{'ids':ids})
        self.assertEqual(code,200,plan)
        self.assertFalse(plan['allow_album'])
        for forbidden in ('title','album','track','disc'):
            code,_=self.request('/api/bulk/save',{'id':plan['id'],'metadata':{forbidden:'Combined'}})
            self.assertEqual(code,400)
        self.assertEqual(self.request('/api/bulk/save',{'id':plan['id'],'metadata':{'artist':'New artist'}})[0],202)
        status=self.wait_bulk(plan['id'])
        self.assertEqual(status['error'],'')
        self.assertTrue(all(r['ok'] for r in status['results']),status)
        for i,path in enumerate(paths):
            self.assertTrue(path.is_file())
            tags=read_tags(path)
            self.assertEqual(tags['artist'],'New artist')
            self.assertEqual(tags['title'],f'Title {i+1}')
            self.assertEqual(tags['album'],f'Single {i+1}')
            self.assertEqual(tags['genre'],f'Genre {i+1}')
            self.assertEqual(tags['track'],str(i+1))
            self.assertEqual(self.audio_payload(path),before[i])

    def test_same_album_can_be_changed_without_renaming_files(self):
        paths,ids=self.tracks(album=True)
        _,plan=self.request('/api/bulk/prepare',{'artist':'an artist','releases':['album:an album']})
        self.assertEqual(plan['count'],2)
        self.assertTrue(plan['allow_album'])
        self.assertEqual(self.request('/api/bulk/save',{'id':plan['id'],'metadata':{'album':'New album name','genre':''}})[0],202)
        status=self.wait_bulk(plan['id'])
        self.assertTrue(all(r['ok'] for r in status['results']),status)
        for i,path in enumerate(paths):
            self.assertTrue(path.is_file())
            tags=read_tags(path)
            self.assertEqual(tags['album'],'New album name')
            self.assertEqual(tags['genre'],'')
            self.assertEqual(tags['title'],f'Title {i+1}')
        self.assertFalse((self.dest/'An artist'/'New album name').exists())

    def test_artwork_settings_api_keeps_credentials_off_browser(self):
        self.login()
        self.app.artwork.load_lidarr=lambda add:add('An artist',None,'/api/v1/mediacover/artist/1/poster.jpg')
        code,result=self.request('/api/artwork/settings',{'provider':'lidarr','url':'http://127.0.0.1:8686','credential':'private-api-key'})
        self.assertEqual(code,200,result)
        deadline=time.time()+5
        while self.app.artwork.status['running'] and time.time()<deadline:
            time.sleep(.01)
        _,state=self.request('/api/state')
        self.assertEqual(state['artwork']['provider'],'lidarr')
        self.assertTrue(state['artwork']['has_credential'])
        self.assertNotIn('private-api-key',json.dumps(state))
        code,_=self.request('/api/artwork/settings',{'provider':'lidarr','url':'http://127.0.0.1:8686','credential':''})
        self.assertEqual(code,200)
        self.assertEqual(self.app.config['artwork']['credential'],'private-api-key')
        self.cookie=''
        self.assertEqual(self.request('/api/artwork/image?id='+'a'*64)[0],401)


    def test_bulk_conflict_validates_every_file_before_writing(self):
        paths,ids=self.tracks(album=True)
        _,plan=self.request('/api/bulk/prepare',{'ids':ids})
        before=paths[0].read_bytes()
        stat=paths[1].stat()
        import os
        os.utime(paths[1],ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000))
        self.request('/api/bulk/save',{'id':plan['id'],'metadata':{'artist':'Changed'}})
        status=self.wait_bulk(plan['id'])
        self.assertEqual(status['completed'],0)
        self.assertIn('No changes were made',status['error'])
        self.assertEqual(paths[0].read_bytes(),before)
        self.assertEqual(read_tags(paths[1])['artist'],'An artist')


class ProviderHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def do_GET(self):
        self.server.requests.append((self.path,dict(self.headers)))
        path=urlsplit(self.path).path
        artist={'id':1,'artistName':'An artist','images':[{'coverType':'poster','url':'/MediaCover/1/poster.jpg'}]}
        album={'id':2,'artistId':1,'title':'An album','images':[{'coverType':'cover','url':'/MediaCover/Albums/2/cover.jpg'}]}
        if path=='/api/v1/artist':
            payload=[artist]
        elif path=='/api/v1/album':
            payload=[album]
        elif path=='/library/sections':
            payload={'MediaContainer':{'Directory':[{'key':'1','type':'artist'}]}}
        elif path=='/library/sections/1/all':
            kind=parse_qs(urlsplit(self.path).query)['type'][0]
            item={'title':'An artist','thumb':'/library/metadata/1/thumb/123'} if kind=='8' else {'title':'An album','parentTitle':'An artist','thumb':'/library/metadata/2/thumb/123'}
            payload={'MediaContainer':{'Metadata':[item],'totalSize':1}}
        elif path.startswith('/api/v1/mediacover/') or path.startswith('/library/metadata/'):
            data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
            self.send_response(200)
            self.send_header('Content-Type','image/png')
            self.end_headers()
            self.wfile.write(data)
            return
        elif path=='/redirect':
            self.send_response(302)
            self.send_header('Location','http://example.invalid/secret')
            self.end_headers()
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),ProviderHandler)
        self.http.requests=[]
        self.url=f'http://127.0.0.1:{self.http.server_port}'
        threading.Thread(target=self.http.serve_forever,daemon=True).start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.temp.cleanup()

    def sync(self,art):
        art.sync()
        deadline=time.time()+10
        while art.status['running'] and time.time()<deadline:
            time.sleep(.01)
        self.assertFalse(art.status['running'])
        self.assertFalse(art.status['error'],art.status)

    def test_lidarr_images_cached_and_credentials_private(self):
        art=Artwork(self.root,{'provider':'lidarr','url':self.url,'credential':'secret-key','section':''})
        self.sync(art)
        self.assertEqual(art.status['matched'],2)
        image_id=art.url_for('AN ARTIST').split('=')[1]
        data,mime=art.image(image_id)
        self.assertEqual(mime,'image/png')
        count=len(self.http.requests)
        self.assertEqual(art.image(image_id)[0],data)
        self.assertEqual(len(self.http.requests),count)
        self.assertNotIn('secret-key',json.dumps(art.public()))
        self.assertTrue(all(h.get('X-Api-Key')=='secret-key' for _,h in self.http.requests))
        self.assertTrue(art.url_for('An artist','An album'))
        self.assertIsNone(art.url_for('Different artist','An album'))
        restored=Artwork(self.root,art.settings)
        self.assertEqual(restored.url_for('An artist'),art.url_for('An artist'))

    def test_plex_library_lookup_and_no_redirect_credentials(self):
        art=Artwork(self.root,{'provider':'plex','url':self.url,'credential':'secret-token','section':''})
        self.sync(art)
        self.assertTrue(art.url_for('An artist'))
        self.assertTrue(art.url_for('An artist','An album'))
        self.assertTrue(all(h.get('X-Plex-Token')=='secret-token' for _,h in self.http.requests))
        with self.assertRaises(ValueError):
            art.request('/redirect')
        self.assertEqual(self.http.requests[-1][0],'/redirect')

    def test_ambiguous_names_fall_back_and_settings_validate(self):
        art=Artwork(self.root,{'provider':'plex','url':self.url,'credential':'secret-token','section':''})
        art.load_plex=lambda add:(add('Duplicate',None,'/a'),add('Duplicate',None,'/b'))
        self.sync(art)
        self.assertIsNone(art.url_for('Duplicate'))
        for url in ('file:///etc/passwd','http://user:pass@localhost:32400','http://localhost:32400/?X-Plex-Token=secret'):
            with self.assertRaises(ValueError):
                validate_settings({'provider':'plex','url':url,'credential':'key'}, {})
        settings=validate_settings({'provider':'lidarr','url':self.url,'credential':''},{'provider':'lidarr','url':self.url,'credential':'keep-key'})
        self.assertEqual(settings['credential'],'keep-key')


if __name__=='__main__':
    unittest.main()
