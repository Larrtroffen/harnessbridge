import Foundation

/// One-time compatibility migration from old brands (SessionConverter / SessionFerry):
///  - `~/Library/Application Support/<old>` → `.../HarnessBridge`
///  - UserDefaults keys `SC…`/`SF…` → `HB…` (only when the new key is absent)
///
/// Copy-only: the old files/folders are left untouched so nothing is lost.
enum AppDataMigration {
    enum Brand {
        static let name = "HarnessBridge"
        static let tagline = "Agent Session Converter"
        static let dataFolder = "HarnessBridge"
        static let outputFolder = "HarnessBridgeOut"
        static let bundleID = "io.github.larrtroffen.harnessbridge"
        /// Old brand folders to migrate from (copy-only).
        static let legacyDataFolders = ["SessionConverter", "SessionFerry"]
    }

    static var applicationSupportBase: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
    }

    static var newAppDataDirectory: URL { applicationSupportBase.appendingPathComponent(Brand.dataFolder, isDirectory: true) }
    static var legacyAppDataDirectories: [URL] {
        Brand.legacyDataFolders.map { applicationSupportBase.appendingPathComponent($0, isDirectory: true) }
    }

    /// Returns a user-facing note when something was migrated.
    @discardableResult
    static func migrateIfNeeded() -> String? {
        migrateUserDefaults()
        return migrateDataDirectory()
    }

    private static func migrateUserDefaults() {
        let defaults = UserDefaults.standard
        let dict = defaults.dictionaryRepresentation()
        for (key, value) in dict where key.hasPrefix("SC") || key.hasPrefix("SF") {
            let newKey = "HB" + key.dropFirst(2)
            if defaults.object(forKey: newKey) == nil {
                defaults.set(value, forKey: newKey)
            }
        }
    }

    private static func migrateDataDirectory() -> String? {
        let fm = FileManager.default
        guard let source = legacyAppDataDirectories.first(where: { fm.fileExists(atPath: $0.path) }) else { return nil }
        var copied: [String] = []
        do {
            try fm.createDirectory(at: newAppDataDirectory, withIntermediateDirectories: true)
            // history: merge old + new records by id (new wins), newest first, cap 200.
            let oldHistory = source.appendingPathComponent("history.json")
            let newHistory = newAppDataDirectory.appendingPathComponent("history.json")
            if fm.fileExists(atPath: oldHistory.path) {
                if !fm.fileExists(atPath: newHistory.path) {
                    try fm.copyItem(at: oldHistory, to: newHistory)
                    copied.append("history.json")
                } else if let merged = Self.mergeHistory(old: oldHistory, new: newHistory) {
                    try merged.write(to: newHistory, options: .atomic)
                    copied.append("history.json(合并)")
                }
            }
            let oldCache = source.appendingPathComponent("detect-cache.json")
            let newCache = newAppDataDirectory.appendingPathComponent("detect-cache.json")
            if fm.fileExists(atPath: oldCache.path), !fm.fileExists(atPath: newCache.path) {
                try fm.copyItem(at: oldCache, to: newCache)
                copied.append("detect-cache.json")
            }
            let oldJournals = source.appendingPathComponent("journals", isDirectory: true)
            let newJournals = newAppDataDirectory.appendingPathComponent("journals", isDirectory: true)
            if fm.fileExists(atPath: oldJournals.path) {
                try fm.createDirectory(at: newJournals, withIntermediateDirectories: true)
                let oldFiles = (try? fm.contentsOfDirectory(at: oldJournals, includingPropertiesForKeys: nil)) ?? []
                var copiedJournals = 0
                for file in oldFiles {
                    let dest = newJournals.appendingPathComponent(file.lastPathComponent)
                    if !fm.fileExists(atPath: dest.path) {
                        try fm.copyItem(at: file, to: dest)
                        copiedJournals += 1
                    }
                }
                if copiedJournals > 0 { copied.append("journals(\(copiedJournals))") }
            }
        } catch {
            NSLog("HarnessBridge: legacy data migration failed: \(error.localizedDescription)")
            return nil
        }
        guard !copied.isEmpty else { return nil }
        return "已从旧版应用（\(source.lastPathComponent)）迁移：\(copied.joined(separator: "、"))（旧数据保留）"
    }

    private static func mergeHistory(old: URL, new: URL) -> Data? {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let oldData = try? Data(contentsOf: old),
              let newData = try? Data(contentsOf: new),
              let oldRecords = try? decoder.decode([MigrationRecord].self, from: oldData),
              let newRecords = try? decoder.decode([MigrationRecord].self, from: newData) else { return nil }
        var seen = Set<UUID>()
        var merged: [MigrationRecord] = []
        for record in newRecords + oldRecords where !seen.contains(record.id) {
            seen.insert(record.id)
            merged.append(record)
        }
        merged.sort { $0.date > $1.date }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return try? encoder.encode(Array(merged.prefix(200)))
    }
}
