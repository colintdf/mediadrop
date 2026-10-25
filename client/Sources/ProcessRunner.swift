import Foundation

// Commands receive argument arrays, never a shell. Output goes to files so a
// full pipe cannot deadlock a long CD extraction.
final class ProcessRunner: @unchecked Sendable {
    private let lock = NSLock()
    private var active: Process?
    private var cancelled = false
    func reset() { lock.lock(); cancelled = false; lock.unlock() }
    func cancel() {
        lock.lock(); cancelled = true
        if let active, active.isRunning { active.terminate() }
        lock.unlock()
    }
    func run(_ executable: URL, _ args: [String]) async throws -> Data {
        try await Task.detached { [self] in
            let base = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            let out = base.appendingPathExtension("out"), err = base.appendingPathExtension("err")
            FileManager.default.createFile(atPath: out.path, contents: nil)
            FileManager.default.createFile(atPath: err.path, contents: nil)
            let stdout = try FileHandle(forWritingTo: out), stderr = try FileHandle(forWritingTo: err)
            defer { try? stdout.close(); try? stderr.close(); try? FileManager.default.removeItem(at: out); try? FileManager.default.removeItem(at: err) }
            let process = Process()
            process.executableURL = executable; process.arguments = args
            process.standardOutput = stdout; process.standardError = stderr
            try self.start(process)
            process.waitUntilExit()
            self.clear()
            guard process.terminationStatus == 0 else {
                let message = String(data: (try? Data(contentsOf: err)) ?? Data(), encoding: .utf8) ?? ""
                throw RipError(message.isEmpty ? "The operation stopped. Check the disc and try again." : String(message.suffix(1500)))
            }
            return try Data(contentsOf: out)
        }.value
    }
    private func start(_ process: Process) throws {
        lock.lock(); defer { lock.unlock() }
        guard !cancelled else { throw CancellationError() }
        try process.run(); active = process
    }
    private func clear() { lock.lock(); active = nil; lock.unlock() }
}
