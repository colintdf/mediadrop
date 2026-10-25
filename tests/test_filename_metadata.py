import json
import time
from urllib.parse import urlencode
import test_server
from filename_metadata import infer_filename, metadata_from_filename
from server import read_tags, revision
import unittest


class FilenameTests(unittest.TestCase):
    def test_parser(self):
        for name, artist, title in [
            ('01 - Gorillaz - Hollywood.wav', 'Gorillaz', 'Hollywood'),
            ('1-01 - Artist - Song.mp3', 'Artist', 'Song'),
            ('50 Cent - In Da Club.mp3','50 Cent','In Da Club'),
            ('808 State - Pacific.mp3','808 State','Pacific'),
            ('10cc - Dreadlock Holiday.mp3','10cc','Dreadlock Holiday'),
            ('Artist_Name – Track_Name.wav','Artist Name','Track Name'),
            ('Artist - Song - Remix.mp3','Artist','Song - Remix')]:
            self.assertEqual(infer_filename(name), {'artist':artist,'title':title})
        self.assertEqual(infer_filename('1979.mp3'), {'title':'1979'})
        self.assertEqual(infer_filename('01 Song.mp3'), {'title':'Song'})
        self.assertEqual(metadata_from_filename('Artist - Song.mp3', {'artist':'Real','title':'Tagged'})[1],{})
        self.assertEqual(metadata_from_filename('Artist - Song.mp3', {'artist':'Real'}, blocked=['title'])[1],{})


# Only define new integration tests on a harness subclass whose inherited tests
# are excluded from discovery below.
class NewBehaviour(test_server.Integration):
    def test_single_folder_and_explicit_clear(self):
        folder=self.folder()
        url='/api/upload?'+urlencode({'folder':folder,'name':'Artist - Song.wav','layout':'single'})
        self.assertEqual(self.request(url,raw=self.wav())[0],202)
        self.app.queue.join()
        job=self.app.jobs[-1]
        self.assertEqual(job['status'],'done',job)
        path=self.dest/'Artist'/'Song'/'Artist - Song.mp3'
        self.assertTrue(path.exists())
        tags=read_tags(path)
        self.assertEqual([tags[k] for k in ('artist','title','album','album_artist','track')],['Artist','Song','Song','Artist','1'])
        self.scan_wait()
        item=next(iter(self.app.library.values()))
        self.assertEqual(item['layout'],'single')
        self.app.edit_metadata({'id':item['id'],'revision':revision(path),'metadata':{'title':''}})
        self.scan_wait()
        self.assertEqual(next(iter(self.app.library.values()))['metadata']['title'],'')

    def test_scan_and_bulk_filename_are_opt_in(self):
        self.folder()
        for name in ('Artist - One.wav','Artist - Two.wav'):
            (self.dest/name).write_bytes(self.wav())
        original={p.name:p.read_bytes() for p in self.dest.iterdir()}
        self.scan_wait()
        records=list(self.app.library.values())
        self.assertEqual({t['metadata']['title'] for t in records},{'One','Two'})
        self.assertTrue(all(p.read_bytes()==original[p.name] for p in self.dest.iterdir()))
        def save(changes,fill=False):
            plan=self.app.prepare_bulk({'ids':list(self.app.library)})
            self.app.start_bulk({'id':plan['id'],'metadata':changes,'fill_missing_from_filename':fill})
            for _ in range(200):
                status=self.app.bulk_status(plan['id'])
                if status['status']=='done':break
                time.sleep(.02)
            self.assertFalse(status['error'],status)
            self.assertTrue(all(r['ok'] for r in status['results']),status)
        save({'genre':'Jazz'})
        self.assertTrue(all(not read_tags(p)['title'] for p in self.dest.iterdir()))
        save({},True)
        self.assertEqual({read_tags(p)['title'] for p in self.dest.iterdir()},{'One','Two'})

# unittest discovers inherited test methods; attach just the shared harness.
for cls in (NewBehaviour,):
    for name in dir(test_server.Integration):
        if name.startswith('test_') and name not in cls.__dict__:
            setattr(cls,name,None)
del cls
