import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from artists import split_artists, primary_artist
from server import browse_library, organised_folder
from artwork import Artwork, identity


class ArtistTests(unittest.TestCase):
    def track(self,name,artist,album_artist='',album='The Now Now'):
        return {'id':name,'name':name+'.mp3','relative':'Gorillaz/'+album+'/'+name+'.mp3','layout':'album',
                'metadata':{'artist':artist,'album_artist':album_artist,'album':album,'title':name}}

    def test_explicit_semicolon_lists_only(self):
        self.assertEqual(split_artists(' Gorillaz; Snoop Dogg ;Jamie Principle;gorillaz;;'),['Gorillaz','Snoop Dogg','Jamie Principle'])
        for name in ['Earth, Wind & Fire','AC/DC','Simon & Garfunkel','Tyler, The Creator','Artist feat. Another']:
            self.assertEqual(split_artists(name),[name])
        self.assertEqual(primary_artist({'artist':'Gorillaz;Snoop Dogg'}),'Gorillaz')
        self.assertEqual(primary_artist({'artist':'Guest;Another','album_artist':'Various Artists'}),'Various Artists')
        self.assertEqual(primary_artist({'artist':'Guest','album_artist':' ;Gorillaz; Damon Albarn'}),'Gorillaz')

    def test_artist_membership_and_guest_album_subset(self):
        items=[self.track('Hollywood','Gorillaz;Snoop Dogg;Jamie Principle','Gorillaz'),self.track('Humility','Gorillaz','Gorillaz')]
        artists=browse_library(items,'artists')
        counts={a['name']:a['track_count'] for a in artists}
        self.assertEqual(counts,{'Gorillaz':2,'Snoop Dogg':1,'Jamie Principle':1})
        own=browse_library(items,'releases','gorillaz')[0]
        guest=browse_library(items,'releases','snoop dogg')[0]
        self.assertFalse(own['appears_on'])
        self.assertTrue(guest['appears_on'])
        self.assertEqual(guest['artist'],'Gorillaz')
        self.assertEqual([t['id'] for t in browse_library(items,'tracks','snoop dogg',guest['key'])],['Hollywood'])
        self.assertEqual(len(browse_library(items,'tracks','gorillaz',own['key'])),2)

    def test_guest_releases_with_same_title_do_not_merge(self):
        tracks=[self.track('First','Gorillaz;Guest','Gorillaz',album='Greatest Hits'),self.track('Second','Another band;Guest','Another band',album='Greatest Hits')]
        releases=browse_library(tracks,'releases','guest')
        self.assertEqual(len(releases),2)
        self.assertEqual(len({r['key'] for r in releases}),2)
        for release in releases:
            self.assertEqual(len(browse_library(tracks,'tracks','guest',release['key'])),1)

    def test_folder_and_artwork_use_main_artist_without_tag_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            tags={'artist':'Gorillaz;Snoop Dogg;Jamie Principle','album':'The Now Now'}
            folder=organised_folder(root,tags,'album')
            self.assertEqual(folder,root/'Gorillaz'/'The Now Now')
            self.assertEqual(tags['artist'],'Gorillaz;Snoop Dogg;Jamie Principle')
            art=Artwork(root,{'provider':'none'})
            art.matches[identity('Gorillaz','The Now Now')]='g'*64
            self.assertEqual(art.url_for(tags['artist'],'The Now Now'),'/api/artwork/image?id='+'g'*64)
            self.assertIsNone(art.url_for('Snoop Dogg','The Now Now'))
            tags['album_artist']='Various Artists'
            self.assertEqual(organised_folder(root,tags,'album'),root/'Various Artists'/'The Now Now')


if __name__=='__main__':
    unittest.main()
