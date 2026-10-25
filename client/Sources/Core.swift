import Foundation
import CryptoKit

struct RipError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
    init(_ message: String) { self.message = message }
}
struct Destination: Identifiable, Decodable, Hashable {
    let id: String
    let name: String
    let type: String
    let available: Bool
}
struct ServerState: Decodable { let folders: [Destination]; let conversion: Bool }
struct ServerJob: Decodable { let id: String; let status: String; let error: String? }
struct UploadReply: Decodable { let job: String }
struct DiscTrack: Identifiable {
    let id: Int
    let source: URL
    var title: String
    var artist: String = ""
    var selected = true
}
struct RipItem: Identifiable, Codable {
    var id = UUID().uuidString
    let disc: String
    let source: URL
    let number: Int
    let server: URL
    let folder: String
    let tags: [String: String]
    let filename: String
    var token = UUID().uuidString
    var job: String?
    var encoded = false
    var status = "Waiting"
    var error = ""
}
struct ReleaseChoice: Identifiable {
    let id: String
    let title: String
    let artist: String
    let date: String
    let country: String
    let disc: Int
    let tracks: [(String, String)]
    var label: String { "\(artist) · \(title) · \(date) \(country) · Disc \(disc)" }
}

enum Core {
    static func serverURL(_ text: String) throws -> URL {
        guard let parts = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(parts.scheme?.lowercased() ?? ""),
              parts.host != nil, parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/", let url = parts.url else {
            throw RipError("Enter your server address, for example http://192.168.0.111:12345")
        }
        return url
    }
    static func key(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    static func number(_ url: URL) -> Int {
        let text = url.deletingPathExtension().lastPathComponent
        let pattern = try! NSRegularExpression(pattern: "[0-9]+")
        if let match = pattern.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)), let range = Range(match.range, in: text) { return Int(text[range]) ?? 999 }
        return 999
    }
    static func credit(_ raw: Any?) -> String {
        let credits = raw as? [[String: Any]] ?? []
        var names: [String] = []
        for credit in credits {
            let artist = credit["artist"] as? [String: Any] ?? [:]
            if let name = credit["name"] as? String ?? artist["name"] as? String, !names.contains(name) { names.append(name) }
        }
        return names.joined(separator: ";")
    }
    static func releases(_ data: Data, discID: String, trackCount: Int) throws -> [ReleaseChoice] {
        let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        var result: [ReleaseChoice] = []
        for release in root["releases"] as? [[String: Any]] ?? [] {
            guard let id = release["id"] as? String, let title = release["title"] as? String else { continue }
            for medium in release["media"] as? [[String: Any]] ?? [] {
                let discs = medium["discs"] as? [[String: Any]] ?? []
                guard discs.contains(where: { $0["id"] as? String == discID }) else { continue }
                let tracks = medium["tracks"] as? [[String: Any]] ?? []
                guard tracks.count == trackCount else { continue }
                let artist = credit(release["artist-credit"])
                let mapped = tracks.map { track -> (String, String) in
                    let recording = track["recording"] as? [String: Any] ?? [:]
                    let name = track["title"] as? String ?? recording["title"] as? String ?? ""
                    let performer = credit(track["artist-credit"] ?? recording["artist-credit"])
                    return (name, performer.isEmpty ? artist : performer)
                }
                result.append(ReleaseChoice(id: id + ":" + String(medium["position"] as? Int ?? 1), title: title, artist: artist,
                    date: release["date"] as? String ?? "", country: release["country"] as? String ?? "",
                    disc: medium["position"] as? Int ?? 1, tracks: mapped))
            }
        }
        return result
    }
    static func uploadRequest(item: RipItem) throws -> URLRequest {
        var parts = URLComponents(url: item.server.appendingPathComponent("api/upload"), resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "folder", value: item.folder), URLQueryItem(name: "name", value: item.filename), URLQueryItem(name: "layout", value: "album")]
        var request = URLRequest(url: parts.url!)
        request.httpMethod = "POST"
        request.timeoutInterval = 1800
        request.setValue("1", forHTTPHeaderField: "X-MediaDrop")
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.setValue(item.token, forHTTPHeaderField: "X-MediaDrop-Upload-ID")
        let tags = String(data: try JSONEncoder().encode(item.tags), encoding: .utf8)!
        let safe = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        request.setValue(tags.addingPercentEncoding(withAllowedCharacters: safe), forHTTPHeaderField: "X-MediaDrop-Tags")
        return request
    }
}
