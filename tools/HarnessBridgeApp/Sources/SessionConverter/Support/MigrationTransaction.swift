import Foundation

// MARK: - Move/restore transaction (app-side fallback when the backend does not
// yet expose --session-mode / migrate-restore). Never deletes: rename only.

struct SourceMoveEntry: Codable, Sendable {
    var sessionID: String
    var targetID: String
    var sourcePath: String
    var backupPath: String
    var installedPath: String?
    var movedAt: Date
}

struct MigrationJournal: Codable, Sendable {
    var createdAt: Date
    var targetID: String
    var entries: [SourceMoveEntry]
}

enum MigrationJournalStore {
    static var directoryURL: URL {
        HistoryStore.directoryURL.appendingPathComponent("journals", isDirectory: true)
    }

    static func write(entries: [SourceMoveEntry], targetID: String) -> URL? {
        guard !entries.isEmpty else { return nil }
        let journal = MigrationJournal(createdAt: Date(), targetID: targetID, entries: entries)
        do {
            try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)
            let stamp = Paths.stamp()
            let url = directoryURL.appendingPathComponent("migration-\(stamp).json")
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            encoder.dateEncodingStrategy = .iso8601
            try encoder.encode(journal).write(to: url, options: .atomic)
            return url
        } catch {
            NSLog("HarnessBridge: failed to write migration journal: \(error.localizedDescription)")
            return nil
        }
    }

    static func load(_ url: URL) -> MigrationJournal? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(MigrationJournal.self, from: data)
    }

    static func latest() -> (url: URL, journal: MigrationJournal)? {
        let fm = FileManager.default
        guard let files = try? fm.contentsOfDirectory(at: directoryURL,
                                                      includingPropertiesForKeys: [.contentModificationDateKey],
                                                      options: [.skipsHiddenFiles]) else { return nil }
        let sorted = files.filter { $0.pathExtension == "json" }.sorted { a, b in
            let da = (try? a.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast
            let db = (try? b.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast
            return da > db
        }
        guard let url = sorted.first, let journal = load(url) else { return nil }
        return (url, journal)
    }
}

enum SourceTransaction {
    /// Moves a source session file out of its store without deleting it:
    /// `foo.jsonl` → `foo.jsonl.migrated-<timestamp>.bak` in the same folder.
    static func moveSourceFile(_ path: String, timestamp: String = Paths.stamp()) throws -> String {
        let fm = FileManager.default
        guard fm.fileExists(atPath: path) else {
            throw ProductError.userFacing("找不到原始会话文件：\(path)")
        }
        if path.contains(".migrated-") {
            return path   // already moved
        }
        let backup = path + ".migrated-\(timestamp).bak"
        try fm.moveItem(atPath: path, toPath: backup)
        return backup
    }

    struct RestoreOutcome: Sendable {
        var restored: Int
        var missing: [String]
        var failed: [String]
    }

    /// Reverses the renames recorded in a journal. Never touches installed target files.
    static func restore(_ journal: MigrationJournal) -> RestoreOutcome {
        let fm = FileManager.default
        var restored = 0
        var missing: [String] = []
        var failed: [String] = []
        for entry in journal.entries {
            if fm.fileExists(atPath: entry.sourcePath) {
                continue   // source already present
            }
            if !fm.fileExists(atPath: entry.backupPath) {
                missing.append(entry.backupPath)
                continue
            }
            do {
                try fm.moveItem(atPath: entry.backupPath, toPath: entry.sourcePath)
                restored += 1
            } catch {
                failed.append("\(entry.backupPath): \(error.localizedDescription)")
            }
        }
        return RestoreOutcome(restored: restored, missing: missing, failed: failed)
    }

    static func restore(journalPath: String) -> RestoreOutcome? {
        let url = URL(fileURLWithPath: journalPath)
        guard let journal = MigrationJournalStore.load(url) else { return nil }
        return restore(journal)
    }
}
