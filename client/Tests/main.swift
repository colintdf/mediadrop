import Foundation

func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { fatalError(message) }
}
let base = try Core.serverURL("http://192.168.0.111:12345")
expect(base.host == "192.168.0.111", "Server URL")
let trailing = try Core.serverURL("http://192.168.0.111:12345/")
expect(trailing == base,"Canonical server address prevents duplicate queues")
for invalid in ["file:///etc/passwd","http://user:pass@localhost:12345","http://host/path","http://host?token=a"] {
    do { _ = try Core.serverURL(invalid); fatalError("Invalid URL accepted") } catch {}
}
expect(Core.number(URL(fileURLWithPath:"/Volumes/Audio CD/10 Audio Track.aiff")) == 10,"Numeric track ordering")
let data = Data(#"{"releases":[{"id":"album-id","title":"Album","artist-credit":[{"name":"Artist"}],"media":[{"position":2,"discs":[{"id":"disc-id"}],"tracks":[{"title":"Song","artist-credit":[{"name":"Artist"},{"name":"Guest"}]}]}]}]}"#.utf8)
let releases = try Core.releases(data,discID:"disc-id",trackCount:1)
expect(releases.count == 1 && releases[0].disc == 2,"Correct disc match")
expect(releases[0].tracks[0].1 == "Artist;Guest","Multiartist credits")
let wrong = try Core.releases(data,discID:"wrong",trackCount:1)
expect(wrong.isEmpty,"Never apply wrong-disc metadata")
let mismatch = try Core.releases(data,discID:"disc-id",trackCount:2)
expect(mismatch.isEmpty,"Never apply wrong track count")
expect(Core.filename(number:1,title:String(repeating:"音",count:200)).utf8.count <= 204,"UTF-8 filename length")
expect(!Core.filename(number:1,title:"A/B").contains("/"),"Safe filename")
let item = RipItem(disc:"disc",source:URL(fileURLWithPath:"/a.aiff"),number:1,server:base,folder:"music",tags:["title":"Café & A+B","artist":"Artist;Guest"],filename:"01 - Song.mp3")
let request = try Core.uploadRequest(item:item)
expect(request.value(forHTTPHeaderField:"X-MediaDrop-Upload-ID") == item.token,"Stable retry token")
let header = request.value(forHTTPHeaderField:"X-MediaDrop-Tags")!.removingPercentEncoding!
let tags = try JSONDecoder().decode([String:String].self,from:Data(header.utf8))
expect(tags == item.tags,"Unicode metadata transport")
let restored = try JSONDecoder().decode(RipItem.self,from:JSONEncoder().encode(item))
expect(restored.token == item.token && restored.server == item.server,"Persistent retry identity")
print("PASS: server URLs, track ordering, exact-disc metadata, per-track artists, upload headers and persistent retry IDs")

var lossless = item
lossless.outputFormat = "flac"
let losslessRequest = try Core.uploadRequest(item:lossless)
expect(URLComponents(url:losslessRequest.url!,resolvingAgainstBaseURL:false)!.queryItems!.contains(URLQueryItem(name:"format",value:"flac")),"FLAC reaches server")
expect(restored.format == "mp3","Old queues retain MP3 default")
expect(Core.filename(number:1,title:"Song",format:"flac").hasSuffix(".flac"),"FLAC extension")

expect(Core.discDevices("/dev/disk7s1") == ["/dev/rdisk7","/dev/disk7","/dev/disk7s1"],"CD partition resolves to raw whole disc")
expect(Core.discDevices("/dev/rdisk7") == ["/dev/rdisk7","/dev/disk7"],"Raw paths are not duplicated")
expect(Core.discDevices("/Volumes/Audio CD").isEmpty,"Never fall back to an unrelated drive")
expect(Core.validDiscID("49HHV7Eb8UKF3aQiNmu1GR8vKTY-"),"Valid MusicBrainz ID")
expect(!Core.validDiscID("error: no disc"),"Reject diagnostic text as ID")
