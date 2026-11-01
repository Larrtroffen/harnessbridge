import Foundation
import AppKit

enum AppInfo {
    static let name = "HarnessBridge"
    static let displayName = "HarnessBridge"
    static let chineseName = ""
    static let tagline = "Agent Session Converter"
    static let version = "1.6.2"
    static let bundleID = "com.deepseek.sessionconverter"
}

// MARK: - Formatting helpers
enum Fmt {
    static func dateFromMs(_ ms: Double?) -> Date? {
        guard let ms, ms > 0 else { return nil }
        return Date(timeIntervalSince1970: ms / 1000.0)
    }

    static func time(_ ms: Double?) -> String {
        guard let d = dateFromMs(ms) else { return "—" }
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f.string(from: d)
    }

    static func bytes(_ n: Int?) -> String {
        guard let n, n > 0 else { return "—" }
        if n < 1024 { return "\(n) B" }
        if n < 1024 * 1024 { return String(format: "%.1f KB", Double(n) / 1024.0) }
        return String(format: "%.1f MB", Double(n) / 1024.0 / 1024.0)
    }

    static func duration(_ seconds: TimeInterval) -> String {
        if seconds < 1 { return String(format: "%.0f ms", seconds * 1000) }
        return String(format: "%.2f s", seconds)
    }

    static func shortPath(_ path: String?, limit: Int = 64) -> String {
        guard let path, !path.isEmpty else { return "—" }
        if path.count <= limit { return path }
        return "…" + path.suffix(limit - 1)
    }

    static func int(_ v: Int?) -> String { v.map(String.init) ?? "—" }

    static func time(_ epochMs: Int64) -> String {
        time(Double(epochMs))
    }

    static func date(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f.string(from: date)
    }

    static func escape(_ s: String) -> String { s }
}

// MARK: - Paths / backend discovery
enum Paths {
    static let defaults = UserDefaults.standard
    static let workspaceKey = "HBWorkspacePath"
    static let outputKey = "HBOutputRootPath"
    private static let legacyWorkspaceKeys = ["SFWorkspacePath", "SCWorkspacePath"]
    private static let legacyOutputKeys = ["SFOutputRootPath", "SCOutputRootPath"]

    static var workspaceOverride: String? {
        get { defaults.string(forKey: workspaceKey) ?? legacyWorkspaceKeys.lazy.compactMap { defaults.string(forKey: $0) }.first }
        set {
            if let newValue, !newValue.isEmpty { defaults.set(newValue, forKey: workspaceKey) }
            else { defaults.removeObject(forKey: workspaceKey) }
        }
    }

    static var outputRootOverride: String? {
        get { defaults.string(forKey: outputKey) ?? legacyOutputKeys.lazy.compactMap { defaults.string(forKey: $0) }.first }
        set {
            if let newValue, !newValue.isEmpty { defaults.set(newValue, forKey: outputKey) }
            else { defaults.removeObject(forKey: outputKey) }
        }
    }

    static func asiURL(in workspace: URL) -> URL {
        workspace.appendingPathComponent("tools/agent-session-import/asi")
    }

    // MARK: - Portable bundle resources (self-contained DMG)

    static var bundleResourceRoot: URL? { Bundle.main.resourceURL }

    /// Bundled backend workspace: `<app>/Contents/Resources/backend` containing
    /// `tools/agent-session-import/asi` + `tools/coverage-report.py`.
    static var bundleBackendRoot: URL? {
        guard let res = bundleResourceRoot else { return nil }
        let backend = res.appendingPathComponent("backend", isDirectory: true)
        return hasASI(backend.path) ? backend : nil
    }

    static var isPortable: Bool { bundleBackendRoot != nil }

    static var bundledPython: String? {
        guard let res = bundleResourceRoot else { return nil }
        let python = res.appendingPathComponent("python/bin/python3")
        return FileManager.default.isExecutableFile(atPath: python.path) ? python.path : nil
    }

    static var bundledZstd: String? {
        guard let res = bundleResourceRoot else { return nil }
        let zstd = res.appendingPathComponent("bin/zstd")
        return FileManager.default.isExecutableFile(atPath: zstd.path) ? zstd.path : nil
    }

    static func hasASI(_ workspacePath: String) -> Bool {
        let asi = asiURL(in: URL(fileURLWithPath: workspacePath))
        return FileManager.default.isExecutableFile(atPath: asi.path)
    }

    /// Multi-level backend discovery:
    /// env override → UserDefaults → app bundle Resources/workspace-path.txt →
    /// walk up from bundle/executable → well-known default path.
    static func discoverWorkspace() -> URL? {
        let env = ProcessInfo.processInfo.environment
        for key in ["HARNESSBRIDGE_WORKSPACE", "HARNESS_BRIDGE_WORKSPACE", "SESSION_FERRY_WORKSPACE", "SESSION_CONVERTER_WORKSPACE"] {
            if let value = env[key], hasASI(value) { return URL(fileURLWithPath: value) }
        }
        // Portable app: the bundled backend is authoritative (no repo/prefs needed).
        if let bundled = bundleBackendRoot { return bundled }
        if let saved = workspaceOverride, hasASI(saved) {
            return URL(fileURLWithPath: saved)
        }
        if let res = Bundle.main.resourceURL {
            let marker = res.appendingPathComponent("workspace-path.txt")
            if let text = try? String(contentsOf: marker, encoding: .utf8) {
                let path = text.trimmingCharacters(in: .whitespacesAndNewlines)
                if !path.isEmpty, hasASI(path) { return URL(fileURLWithPath: path) }
            }
        }
        var starts: [URL] = []
        starts.append(Bundle.main.bundleURL)
        starts.append(URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent())
        starts.append(URL(fileURLWithPath: FileManager.default.currentDirectoryPath))
        for start in starts {
            if let found = walkUp(start) { return found }
        }
        return bundleBackendRoot
    }

    private static func walkUp(_ start: URL) -> URL? {
        var url = start.standardizedFileURL
        for _ in 0..<10 {
            if hasASI(url.path) { return url }
            let parent = url.deletingLastPathComponent()
            if parent.path == url.path { break }
            url = parent
        }
        return nil
    }

    static func outputRoot() -> URL {
        if let override = outputRootOverride, !override.isEmpty {
            return URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/HarnessBridgeOut", isDirectory: true)
    }

    static func ensureDirectory(_ url: URL) throws {
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    static func stamp() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: Date())
    }

    static func pathExists(_ path: String?) -> Bool {
        guard let path, !path.isEmpty else { return false }
        return FileManager.default.fileExists(atPath: path)
    }

    static func findPython3() -> String {
        if let bundled = bundledPython { return bundled }
        let candidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
        for c in candidates where FileManager.default.isExecutableFile(atPath: c) {
            return c
        }
        return "/usr/bin/python3"
    }

    static func revealInFinder(_ path: String?) {
        guard let path, !path.isEmpty else { return }
        let url = URL(fileURLWithPath: path)
        if FileManager.default.fileExists(atPath: path) {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        }
    }

    static func open(_ path: String?) {
        guard let path, !path.isEmpty else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }
}

// MARK: - Console log entry
struct LogEntry: Identifiable, Sendable {
    let id = UUID()
    let date: Date
    let command: String
    let duration: TimeInterval
    let exitCode: Int32
    let timedOut: Bool
    let stdoutTail: String
    let stderrTail: String

    var isOK: Bool { exitCode == 0 && !timedOut }

    static func from(_ result: CommandResult) -> LogEntry {
        LogEntry(date: Date(),
                 command: result.command,
                 duration: result.duration,
                 exitCode: result.exitCode,
                 timedOut: result.timedOut,
                 stdoutTail: Self.tail(result.stdout),
                 stderrTail: Self.tail(result.stderr))
    }

    private static func tail(_ text: String, limit: Int = 4000) -> String {
        if text.count <= limit { return text }
        return "…" + text.suffix(limit)
    }
}
