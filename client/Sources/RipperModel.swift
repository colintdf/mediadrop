import Foundation
import AppKit
import SwiftUI

@MainActor
final class RipperModel: ObservableObject {
    @Published var server = UserDefaults.standard.string(forKey: "server") ?? "http://192.168.0.111:12345"
    @Published var folders: [Destination] = []
    @Published var folder = UserDefaults.standard.string(forKey: "folder") ?? ""
    @Published var tracks: [DiscTrack] = []
    @Published var album = ""
    @Published var artist = ""
    @Published var date = ""
    @Published var genre = ""
    @Published var discNumber = "1"
    @Published var choices: [ReleaseChoice] = []
    @Published var release = ""
    @Published var cover: NSImage?
    @Published var queue: [RipItem] = []
    @Published var busy = false
    @Published var message = "Connect your MediaDrop server, then insert an audio CD."
    @Published var error = ""
    @Published var progress = 0.0
    @Published var doubleRead = false
    private var device = ""
    private var discID = ""
    private var lastLookup = Date.distantPast
    private var discKey = ""
    private var stopped = false
    private var task: Task<Void, Never>?
    private let runner = ProcessRunner()
    private let session: URLSession
    let storage: URL

    init() {
        storage = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("MediaDrop Ripper")
        try? FileManager.default.createDirectory(at: storage, withIntermediateDirectories: true)
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 3600
        session = URLSession(configuration: config)
        if let data = try? Data(contentsOf: storage.appendingPathComponent("queue.json")), let saved = try? JSONDecoder().decode([RipItem].self, from: data) { queue = saved }
    }
    private func save() throws {
        try JSONEncoder().encode(queue).write(to: storage.appendingPathComponent("queue.json"), options: .atomic)
    }
    private func tool(_ name: String) throws -> URL {
        guard let url = Bundle.main.url(forResource: name, withExtension: nil, subdirectory: "Tools"), FileManager.default.isExecutableFile(atPath: url.path) else { throw RipError("The app is missing \(name). Download a fresh copy of the DMG.") }
        return url
    }
    private func perform(_ work: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true; error = ""; stopped = false; runner.reset()
        task = Task {
            defer { busy = false; task = nil }
            do { try await work() }
            catch { self.error = stopped ? "Stopped. Saved MP3s and upload progress are kept for retry." : error.localizedDescription }
        }
    }
    func stop() { stopped = true; runner.cancel(); task?.cancel() }
    private func checkStop() throws { if stopped || Task.isCancelled { throw CancellationError() } }
    private func checked(_ data: Data, _ response: URLResponse) throws -> Data {
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw RipError(detail?["error"] as? String ?? "The server returned an error. Check its address and update MediaDrop.")
        }
        return data
    }
    func connect() { perform { try await self.connectServer() } }
    private func connectServer() async throws {
        let base = try Core.serverURL(server)
        let (health, response) = try await session.data(from: base.appendingPathComponent("api/health"))
        let info = try JSONSerialization.jsonObject(with: checked(health, response)) as? [String: Any] ?? [:]
        let version = info["version"] as? String ?? "0"
        guard version.compare("1.5", options: .numeric) != .orderedAscending else { throw RipError("Update the MediaDrop server to version 1.5 or later before using the ripper.") }
        let (data, reply) = try await session.data(from: base.appendingPathComponent("api/state"))
        let state = try JSONDecoder().decode(ServerState.self, from: checked(data, reply))
        folders = state.folders.filter { $0.type == "music" && $0.available }
        guard !folders.isEmpty else { throw RipError("Add an available music folder in your server's web interface first.") }
        if !folders.contains(where: { $0.id == folder }) { folder = folders[0].id }
        UserDefaults.standard.set(base.absoluteString, forKey: "server")
        UserDefaults.standard.set(folder, forKey: "folder")
        message = "Connected · \(folders.count) music destination\(folders.count == 1 ? "" : "s") available"
    }
    func findCD() { perform {
        self.message = "Looking for an audio CD…"
        let volumes = try FileManager.default.contentsOfDirectory(at: URL(fileURLWithPath: "/Volumes"), includingPropertiesForKeys: nil)
        var candidates: [(URL, String)] = []
        for volume in volumes {
            let data = try await self.runner.run(URL(fileURLWithPath: "/usr/sbin/diskutil"), ["info", "-plist", volume.path])
            let info = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] ?? [:]
            let fs = (info["FilesystemType"] as? String ?? "").lowercased()
            if fs.contains("cdda") || info["Content"] as? String == "CD_DA" {
                candidates.append((volume, info["DeviceNode"] as? String ?? ""))
            }
        }
        guard candidates.count == 1 else { throw RipError(candidates.isEmpty ? "No mounted audio CD found. Insert a disc, or use Choose CD folder to select its volume." : "More than one audio CD is mounted. Use Choose CD folder to select one.") }
        try await self.loadDisc(candidates[0].0, device: candidates[0].1)
    } }
    func chooseCD() {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.directoryURL = URL(fileURLWithPath: "/Volumes"); panel.prompt = "Choose audio CD"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        perform {
            let data = try await self.runner.run(URL(fileURLWithPath: "/usr/sbin/diskutil"), ["info", "-plist", url.path])
            let info = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] ?? [:]
            try await self.loadDisc(url, device: info["DeviceNode"] as? String ?? "")
        }
    }
    private func loadDisc(_ url: URL, device: String) async throws {
        let files = try FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: [.fileSizeKey, .isRegularFileKey]).filter {
            ["aiff", "aif", "cdda", "wav"].contains($0.pathExtension.lowercased()) && !$0.lastPathComponent.hasPrefix(".")
        }.sorted { Core.number($0) == Core.number($1) ? $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending : Core.number($0) < Core.number($1) }
        guard !files.isEmpty else { throw RipError("This folder contains no readable audio CD tracks (AIFF). Check that the disc is an audio CD.") }
        self.device = device; discID = ""; choices = []; release = ""; cover = nil
        album = url.lastPathComponent == "Audio CD" ? "" : url.lastPathComponent
        artist = ""; date = ""; genre = ""; discNumber = "1"
        tracks = files.enumerated().map { DiscTrack(id: $0.offset + 1, source: $0.element, title: "Track \($0.offset + 1)") }
        if !device.isEmpty, let helper = try? tool("discid"), let result = try? await runner.run(helper, [device]) { discID = String(data: result, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "" }
        // Fallback is a queue key only, never presented as a MusicBrainz Disc ID.
        discKey = discID.isEmpty ? Core.key(url.path + files.map { "\($0.lastPathComponent):\((try? $0.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)" }.joined(separator: "|")) : discID
        message = "\(tracks.count) tracks ready. Review the details before ripping."
        if !discID.isEmpty { try await lookupDisc() }
        else { message += " Disc lookup unavailable; enter the album and track names manually." }
    }
    func lookup() { perform { try await self.lookupDisc() } }
    private func lookupDisc() async throws {
        guard !discID.isEmpty else { throw RipError("A readable disc ID is needed for automatic lookup. You can enter the details manually.") }
        message = "Looking up the CD on MusicBrainz…"
        let delay = 1.1 - Date().timeIntervalSince(lastLookup)
        if delay > 0 { try await Task.sleep(nanoseconds:UInt64(delay * 1_000_000_000)) }
        try checkStop(); lastLookup = Date()
        var parts = URLComponents(string: "https://musicbrainz.org/ws/2/discid/\(discID)")!
        parts.queryItems = [URLQueryItem(name: "fmt", value: "json"), URLQueryItem(name: "inc", value: "recordings+artist-credits+discids"), URLQueryItem(name: "cdstubs", value: "no")]
        var request = URLRequest(url: parts.url!); request.setValue("MediaDrop-Ripper/1.0 (https://github.com/colintdf/mediadrop)", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode != 404 else { message = "This disc is not in MusicBrainz. Enter its details below."; return }
        choices = try Core.releases(checked(data, response), discID: discID, trackCount: tracks.count)
        if choices.count == 1 { release = choices[0].id; applyRelease() }
        message = choices.isEmpty ? "No exact disc match found. Enter the details manually." : "\(choices.count) matching release\(choices.count == 1 ? "" : "s"). Review the chosen edition and track names."
    }
    func applyRelease() {
        guard let choice = choices.first(where: { $0.id == release }), choice.tracks.count == tracks.count else { return }
        album = choice.title; artist = choice.artist; date = choice.date; discNumber = String(choice.disc)
        for index in tracks.indices { tracks[index].title = choice.tracks[index].0; tracks[index].artist = choice.tracks[index].1 }
        cover = nil
        let releaseID = choice.id.components(separatedBy: ":")[0]
        Task {
            if let (data, response) = try? await session.data(from: URL(string: "https://coverartarchive.org/release/\(releaseID)/front-250")!),
               (response as? HTTPURLResponse)?.statusCode == 200, self.release == choice.id { cover = NSImage(data: data) }
        }
    }
    func rip() { perform {
        try await self.connectServer()
        let base = try Core.serverURL(self.server)
        guard !self.artist.trimmingCharacters(in: .whitespaces).isEmpty, !self.album.trimmingCharacters(in: .whitespaces).isEmpty else { throw RipError("Enter the album artist and album title first.") }
        guard Int(self.discNumber).map({ $0 > 0 && $0 < 10000 }) == true else { throw RipError("Enter a disc number between 1 and 9999.") }
        let selected = self.tracks.filter { $0.selected }
        guard !selected.isEmpty else { throw RipError("Select at least one track.") }
        guard selected.allSatisfy({ !$0.title.trimmingCharacters(in: .whitespaces).isEmpty }) else { throw RipError("Give each selected track a title.") }
        let fields = [self.artist,self.album,self.date,self.genre] + selected.flatMap { [$0.title,$0.artist] }
        guard fields.allSatisfy({ $0.count <= 300 && !$0.unicodeScalars.contains(where: { $0.value < 32 }) }) else { throw RipError("Metadata fields must be at most 300 characters without line breaks.") }
        if !self.date.isEmpty && self.date.range(of: #"^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$"#, options: .regularExpression) == nil { throw RipError("Use a four-digit year or YYYY-MM-DD for the date.") }
        for track in selected {
            // A disc/track/destination is queued once. Completed copies are kept
            // in the manifest to prevent accidental duplicate albums next time.
            if self.queue.contains(where: { $0.disc == self.discKey && $0.number == track.id && $0.server == base && $0.folder == self.folder }) { continue }
            let tags = ["title":track.title,"artist":track.artist.isEmpty ? self.artist : track.artist,"album":self.album,"album_artist":self.artist,"track":String(track.id),"disc":self.discNumber,"date":self.date,"genre":self.genre]
            let filename = Core.filename(number:track.id,title:track.title)
            self.queue.append(RipItem(disc:self.discKey,source:track.source,number:track.id,server:base,folder:self.folder,tags:tags,filename:filename))
        }
        try self.save(); try await self.processQueue()
    } }
    func retry() { perform { try await self.processQueue() } }
    private func encodedURL(_ item: RipItem) -> URL { storage.appendingPathComponent(item.id + ".mp3") }
    private func processQueue() async throws {
        let pending = queue.indices.filter { queue[$0].status != "Complete" }
        guard !pending.isEmpty else { message = "These tracks have already been uploaded to this destination."; return }
        var failures = 0
        for (offset,index) in pending.enumerated() {
            try checkStop(); progress = Double(offset) / Double(pending.count)
            do {
                queue[index].error = ""
                if queue[index].job == nil {
                    let output = encodedURL(queue[index])
                    if !queue[index].encoded || !FileManager.default.fileExists(atPath: output.path) {
                        guard FileManager.default.fileExists(atPath: queue[index].source.path) else { throw RipError("Reinsert the original CD to rip this track. Already ripped MP3s can upload without the disc.") }
                        queue[index].status = "Ripping"; message = "Reading track \(queue[index].number) · \(queue[index].tags["title"] ?? "")"
                        let local = storage.appendingPathComponent(queue[index].id + ".aiff")
                        defer { try? FileManager.default.removeItem(at: local) }
                        // Copy before encoding so network failures never require a
                        // second disc read. macOS exposes CD audio as AIFF files.
                        _ = try await runner.run(URL(fileURLWithPath: "/bin/cp"), [queue[index].source.path, local.path])
                        if doubleRead {
                            message = "Comparing a second read of track \(queue[index].number)…"
                            let second = storage.appendingPathComponent(queue[index].id + "-check.aiff")
                            defer { try? FileManager.default.removeItem(at: second) }
                            _ = try await runner.run(URL(fileURLWithPath: "/bin/cp"), [queue[index].source.path, second.path])
                            _ = try await runner.run(URL(fileURLWithPath: "/usr/bin/cmp"), [local.path,second.path])
                        }
                        try checkStop(); queue[index].status = "Encoding 320 kbps"
                        let temporary = storage.appendingPathComponent(queue[index].id + "-partial.mp3")
                        defer { try? FileManager.default.removeItem(at: temporary) }
                        var args = ["-hide_banner","-nostdin","-v","error","-y","-i",local.path,"-map","0:a:0","-vn","-ac","2","-ar","44100","-c:a","libmp3lame","-b:a","320k","-id3v2_version","3"]
                        for (key,value) in queue[index].tags.sorted(by: { $0.key < $1.key }) { args += ["-metadata","\(key)=\(value)"] }
                        args.append(temporary.path)
                        _ = try await runner.run(try tool("ffmpeg"),args)
                        try? FileManager.default.removeItem(at: output)
                        try FileManager.default.moveItem(at: temporary, to: output)
                        queue[index].encoded = true; try save()
                    }
                    try checkStop(); queue[index].status = "Uploading"; message = "Uploading track \(queue[index].number)…"
                    let request = try Core.uploadRequest(item:queue[index])
                    let (data,response) = try await session.upload(for:request,fromFile:output)
                    queue[index].job = try JSONDecoder().decode(UploadReply.self,from:checked(data,response)).job
                    try save()
                }
                queue[index].status = "Server processing"; try save()
                let id = queue[index].job!
                var finished = false
                for _ in 0..<600 {
                    try checkStop()
                    // A dedicated endpoint retains access to jobs older than the
                    // web interface's most recent 100 uploads.
                    let (data,response) = try await session.data(from:queue[index].server.appendingPathComponent("api/jobs/\(id)"))
                    let job = try JSONDecoder().decode(ServerJob.self,from:checked(data,response))
                    if job.status == "done" { finished = true; break }
                    if job.status == "failed" { throw RipError("Server could not finish this track: \(job.error ?? "unknown error"). Check the server before retrying.") }
                    try await Task.sleep(nanoseconds:1_000_000_000)
                }
                guard finished else { throw RipError("The server is still processing. Retry to check the same job.") }
                queue[index].status = "Complete"; try save()
                try? FileManager.default.removeItem(at:encodedURL(queue[index]))
            } catch {
                queue[index].status = "Needs attention"; queue[index].error = error.localizedDescription
                try save(); try checkStop(); failures += 1
            }
        }
        progress = 1
        message = failures == 0 ? "Finished. Your music is in MediaDrop." : "\(failures) track(s) need attention. Fix the issue and choose Retry pending."
    }
    func forget(_ id: String) {
        guard !busy, let index = queue.firstIndex(where: { $0.id == id && $0.status != "Complete" }) else { return }
        let alert = NSAlert()
        alert.messageText = "Remove this pending track?"
        alert.informativeText = "Check MediaDrop first: an accepted upload may already exist on the server. Removing this queue entry lets you deliberately rip it again and could create a duplicate."
        alert.addButton(withTitle:"Keep track"); alert.addButton(withTitle:"Remove from queue")
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        let old = queue
        let file = encodedURL(queue[index])
        queue.remove(at:index)
        do { try save(); try? FileManager.default.removeItem(at:file) }
        catch { queue = old; self.error = error.localizedDescription }
    }
    func clearCompleted() {
        // Keep completion identities on disk: clearing a visual list must not
        // silently disable duplicate protection. The list hides these by default.
        message = "Completed tracks remain recorded to prevent duplicate uploads."
    }
    func openServer() { if let url = try? Core.serverURL(server) { NSWorkspace.shared.open(url) } }
    func revealCache() { NSWorkspace.shared.open(storage) }
}
