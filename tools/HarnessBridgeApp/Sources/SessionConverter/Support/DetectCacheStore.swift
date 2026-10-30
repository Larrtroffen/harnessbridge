import Foundation

/// Persists the last successful harness detection so the first screen can render
/// immediately on launch (before the slow `asi detect` completes).
struct DetectCacheSnapshot: Codable, Sendable {
    var detectedAt: Date
    var harnesses: [HarnessInfo]
}

enum DetectCacheStore {
    static let directoryURL: URL = HistoryStore.directoryURL

    static var fileURL: URL {
        directoryURL.appendingPathComponent("detect-cache.json")
    }

    static func load() -> DetectCacheSnapshot? {
        guard let data = try? Data(contentsOf: fileURL) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(DetectCacheSnapshot.self, from: data)
    }

    @discardableResult
    static func save(harnesses: [HarnessInfo]) -> DetectCacheSnapshot? {
        guard !harnesses.isEmpty else { return nil }
        let snapshot = DetectCacheSnapshot(detectedAt: Date(), harnesses: harnesses)
        do {
            try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            encoder.dateEncodingStrategy = .iso8601
            let data = try encoder.encode(snapshot)
            try data.write(to: fileURL, options: .atomic)
            return snapshot
        } catch {
            NSLog("HarnessBridge: failed to save detect cache: \(error.localizedDescription)")
            return nil
        }
    }

    static func clear() {
        try? FileManager.default.removeItem(at: fileURL)
    }
}
