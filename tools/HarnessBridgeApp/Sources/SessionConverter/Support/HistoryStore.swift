import Foundation

/// Persists migration history at:
///   ~/Library/Application Support/HarnessBridge/history.json
final class HistoryStore {
    static let directoryURL: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent("HarnessBridge", isDirectory: true)
    }()

    static var fileURL: URL { directoryURL.appendingPathComponent("history.json") }
    static let maxRecords = 200

    private let fileManager = FileManager.default
    private let lock = NSLock()

    func load() -> [MigrationRecord] {
        lock.lock(); defer { lock.unlock() }
        guard let data = try? Data(contentsOf: Self.fileURL) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        if let records = try? decoder.decode([MigrationRecord].self, from: data) {
            return records.sorted { $0.date > $1.date }
        }
        return []
    }

    @discardableResult
    func append(_ record: MigrationRecord) -> [MigrationRecord] {
        lock.lock(); defer { lock.unlock() }
        var records = loadLocked()
        records.insert(record, at: 0)
        saveLocked(records)
        return records.sorted { $0.date > $1.date }
    }

    func delete(id: UUID) -> [MigrationRecord] {
        lock.lock(); defer { lock.unlock() }
        var records = loadLocked()
        records.removeAll { $0.id == id }
        saveLocked(records)
        return records.sorted { $0.date > $1.date }
    }

    func clear() {
        lock.lock(); defer { lock.unlock() }
        saveLocked([])
    }

    // MARK: - private helpers (caller holds lock)
    private func loadLocked() -> [MigrationRecord] {
        guard let data = try? Data(contentsOf: Self.fileURL) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode([MigrationRecord].self, from: data)) ?? []
    }

    private func saveLocked(_ records: [MigrationRecord]) {
        do {
            try fileManager.createDirectory(at: Self.directoryURL, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            encoder.dateEncodingStrategy = .iso8601
            let capped = Array(records.prefix(Self.maxRecords))
            let data = try encoder.encode(capped)
            // Data.write(.atomic) performs a real temp-file + rename on the same volume.
            try data.write(to: Self.fileURL, options: .atomic)
        } catch {
            // History persistence must never crash the app; surface via caller log.
            NSLog("HarnessBridge: failed to save history: \(error.localizedDescription)")
        }
    }
}
