import Foundation

// MARK: - Product navigation
enum AppPage: String, CaseIterable, Identifiable {
    case home, wizard, migrateAll, sessions, history, settings, help, advanced, detail

    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: return "首页"
        case .wizard: return "迁移会话"
        case .migrateAll: return "一键迁移"
        case .sessions: return "浏览会话"
        case .history: return "迁移历史"
        case .settings: return "设置"
        case .help: return "帮助"
        case .advanced: return "高级工具"
        case .detail: return "会话详情"
        }
    }

    var systemImage: String {
        switch self {
        case .home: return "house"
        case .wizard: return "arrow.right.circle"
        case .migrateAll: return "square.stack.3d.up.fill"
        case .sessions: return "list.bullet.rectangle"
        case .history: return "clock.arrow.circlepath"
        case .settings: return "gearshape"
        case .help: return "questionmark.circle"
        case .advanced: return "wrench.and.screwdriver"
        case .detail: return "doc.text.magnifyingglass"
        }
    }
}

// MARK: - Harness card info
struct HarnessInfo: Identifiable, Codable, Sendable, Hashable {
    var id: String
    var name: String
    var colorHex: String
    var detected: Bool
    var sessionCount: Int
    var recentAtMs: Double?
    var storePath: String
    var family: String? = nil
    var sessionDirHint: String? = nil
    var installSupported: Bool = false
    var installExperimental: Bool = false
    var howToSee: String? = nil

    var recentText: String {
        guard let ms = recentAtMs else { return L("暂无会话") }
        return L("最近 ") + Fmt.time(ms)
    }

    var summaryText: String {
        if !detected { return L("未检测到") }
        return sessionCount > 0 ? L10n.sessions(sessionCount) : L("已安装 · 暂无会话")
    }
}

enum HarnessCatalog {
    static let primary: [(id: String, name: String, color: String, family: String)] = [
        ("claude", "Claude Code", "#D97757", "Claude Code 系"),
        ("codex", "Codex", "#10A37F", "Codex 系"),
        ("dsh", "DeepSeek Harness", "#22C55E", "DeepSeek Harness"),
        ("qoder", "Qoder", "#3B82F6", "Claude Code 系"),
        ("omp", "OMP", "#8B5CF6", "树状会话系"),
    ]

    static func name(for id: String) -> String {
        if let item = primary.first(where: { $0.id == id }) { return item.name }
        return SourceGroups.names[id] ?? id
    }

    static func color(for id: String) -> String {
        if let item = primary.first(where: { $0.id == id }) { return item.color }
        return "#64748B"
    }

    static func storePath(for id: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        switch id {
        case "claude": return "\(home)/.claude/projects"
        case "codex": return "\(home)/.codex/sessions"
        case "dsh": return "\(home)/.dsh/sessions"
        case "qoder": return "\(home)/.qoder/projects"
        case "omp": return "\(home)/.omp/agent/sessions"
        default: return ""
        }
    }

    static func isStorePresent(_ id: String) -> Bool {
        let path = storePath(for: id)
        guard !path.isEmpty else { return false }
        return FileManager.default.fileExists(atPath: path)
    }
}

// MARK: - Migration targets (user-facing labels)
struct MigrationTarget: Identifiable, Sendable, Hashable {
    var id: String          // dsh / claude / codex / omp / qoder / atif
    var title: String
    var subtitle: String
    var badge: String       // 推荐 / 已验证 / 实验性 / 仅导出
    var isExportOnly: Bool

    static let all: [MigrationTarget] = [
        MigrationTarget(id: "dsh", title: "DeepSeek Harness",
                        subtitle: "把会话迁移到 DeepSeek Harness，重启后可在应用中看到",
                        badge: "推荐", isExportOnly: false),
        MigrationTarget(id: "claude", title: "Claude Code",
                        subtitle: "生成 Claude Code 会话文件（格式级，暂不自动注册）",
                        badge: "实验性", isExportOnly: false),
        MigrationTarget(id: "codex", title: "Codex",
                        subtitle: "生成 Codex 会话文件（格式级，暂不自动注册）",
                        badge: "实验性", isExportOnly: false),
        MigrationTarget(id: "omp", title: "OMP",
                        subtitle: "生成 OMP 会话文件（格式级，暂不自动注册）",
                        badge: "实验性", isExportOnly: false),
        MigrationTarget(id: "qoder", title: "Qoder",
                        subtitle: "生成 Qoder 会话文件（格式级，暂不自动注册）",
                        badge: "实验性", isExportOnly: false),
        MigrationTarget(id: "atif", title: "导出为通用交换文件",
                        subtitle: "导出可审计的标准交换文件（JSON），供备份或跨工具使用",
                        badge: "仅导出", isExportOnly: true),
    ]

    static func find(_ id: String) -> MigrationTarget {
        all.first { $0.id == id } ?? all[0]
    }
}

// MARK: - Session preview
struct SessionPreview: Sendable {
    var title: String
    var cwd: String?
    var model: String?
    var messageCount: Int?
    var toolCallCount: Int?
    var firstUserMessage: String?
    var recentMessages: [String]
    var warnings: [String]
    var sourceNote: String  // 说明数据来自后端预览还是列表元数据
}

// MARK: - Migration
enum MigrationMode: String, Sendable, CaseIterable {
    case install     // 写入目标 Harness 的会话库（默认）
    case export      // 仅导出到文件夹（高级）
    var label: String { L(self == .install ? "直接迁移" : "仅导出") }
}

enum SessionMode: String, Sendable, CaseIterable {
    case keep        // 保留原始会话（默认）
    case move        // 成功安装后把源会话移出为 .bak（可恢复）
    var label: String { L(self == .keep ? "保留原始会话" : "移出原始会话") }
}

struct MigrationOptions: Sendable {
    var outputDir: String
    var keepOriginalCwd: Bool = true
    var customCwd: String = ""
    var keepSystem: Bool = false
    var registerToProject: Bool = false
    var mode: MigrationMode = .install
    var sessionMode: SessionMode = .keep
    var overwrite: Bool = false
    var sourceRoot: String? = nil          // 测试/高级：源根目录覆盖（--root）
    var targetHome: String? = nil          // 测试/高级：目标 home 覆盖（--dsh-home 等）
    var environment: [String: String]? = nil  // 测试隔离：子进程环境覆盖（如 HOME）
    var installIntoRealStore: Bool { mode == .install }
    var targetCwd: String? {
        if keepOriginalCwd { return nil }
        let trimmed = customCwd.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

struct MigrationItemResult: Codable, Identifiable, Sendable {
    var id: String { sessionID }
    var sessionID: String
    var title: String
    var ok: Bool
    var outputDir: String?
    var artifact: String?
    var verifyStatus: String?
    var lossy: [String]
    var warnings: [String]
    var error: String?
    // v1.4 install fields
    var installedPath: String? = nil
    var verified: Bool? = nil
    var skipped: Bool = false
    var skipReason: String? = nil
    var installStatus: String? = nil
    var sourceBackupPath: String? = nil
    var sourceMoved: Bool = false
    var targetStorePath: String? = nil
    var sourceMoveStatus: String? = nil
    var sourcePath: String? = nil
    var journalPath: String? = nil
}

struct MigrationReport: Sendable {
    var sourceID: String
    var targetID: String
    var items: [MigrationItemResult]
    var outputDir: String
    var elapsed: TimeInterval

    var okCount: Int { items.filter(\.ok).count }
    var failCount: Int { items.count - okCount }
    var hasLossy: Bool { items.contains { !$0.lossy.isEmpty || !$0.warnings.isEmpty } }
}

// MARK: - History record
struct MigrationRecord: Codable, Identifiable, Sendable {
    var id: UUID
    var date: Date
    var sourceID: String
    var sourceName: String
    var targetID: String
    var targetName: String
    var mode: String            // export / install
    var outputDir: String
    var sessionCount: Int
    var okCount: Int
    var failCount: Int
    var items: [MigrationItemResult]
    var isSelfTest: Bool
    var note: String?
    // v1.4 install metadata (optional: old history entries decode unchanged)
    var targetStorePath: String? = nil
    var sessionMode: String? = nil
    var skippedCount: Int? = nil
    var journalPath: String? = nil
    var migrateAll: Bool? = nil
    var cancelled: Bool? = nil

    var statusText: String {
        if failCount == 0 { return L("全部成功") }
        if okCount == 0 { return L("失败") }
        return L("部分成功")
    }
}

// MARK: - Session detail (product v1.2)
struct TokenUsage: Sendable, Equatable {
    var inputTokens: Int?
    var outputTokens: Int?
    var cacheReadTokens: Int?
    var cacheWriteTokens: Int?
    var totalTokens: Int?
    var available: Bool

    static let unavailable = TokenUsage(available: false)

    var hasAnyValue: Bool {
        [inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens, totalTokens]
            .contains { ($0 ?? 0) > 0 }
    }
}

struct ToolUsageStat: Sendable, Identifiable, Equatable {
    var id: String { name }
    var name: String
    var count: Int
}

struct DetailMessageCounts: Sendable, Equatable {
    var user: Int?
    var assistant: Int?
    var tool: Int?
    var reasoning: Int?
    var system: Int?
    var compaction: Int?

    var total: Int {
        [user, assistant, tool, reasoning, system, compaction].reduce(0) { $0 + ($1 ?? 0) }
    }
}

struct DetailStats: Sendable, Equatable {
    var messages = DetailMessageCounts()
    var toolCalls: Int?
    var toolResults: Int?
    var toolErrors: Int?
    var toolUsage: [ToolUsageStat] = []
    var usage = TokenUsage.unavailable
    var durationMs: Double?
    var firstTs: Double?
    var lastTs: Double?
    var eventsTotal: Int?
    var eventsShown: Int?
    var truncated: Bool = false
}

struct DetailSection: Sendable, Identifiable, Equatable {
    var id: Int { index }
    var index: Int
    var kind: String
    var title: String
    var startIndex: Int?
    var endIndex: Int?
    var ts: Double?
    var toolCalls: Int?
    var tokens: Int?
}

struct DetailToolInfo: Sendable, Equatable {
    var name: String?
    var callID: String?
    var isError: Bool
}

struct DetailEvent: Sendable, Identifiable, Equatable {
    var id: Int { index }
    var index: Int
    var ts: Double?
    var kind: String          // user | assistant | thinking | tool_call | tool_result | system | compaction
    var role: String?
    var text: String
    var tool: DetailToolInfo?
    var usage: TokenUsage?
    var section: Int?

    var kindLabel: String {
        switch kind {
        case "user": return "用户"
        case "assistant": return "助手"
        case "thinking": return "思考"
        case "tool_call": return "工具调用"
        case "tool_result": return "工具结果"
        case "system": return "系统"
        case "compaction": return "上下文压缩"
        default: return kind.isEmpty ? "事件" : kind
        }
    }

    var isError: Bool { tool?.isError == true }
}

struct SessionDetail: Sendable {
    var source: String
    var sessionID: String
    var title: String
    var cwd: String?
    var model: String?
    var provider: String?
    var createdAtMs: Double?
    var updatedAtMs: Double?
    var path: String?
    var sourceLabel: String?
    var evidenceLevel: String?
    var stats = DetailStats()
    var sections: [DetailSection] = []
    var timeline: [DetailEvent] = []
    var warnings: [String] = []
    var isFallback: Bool = false      // true = built from `asi preview` (backend without session-detail)
    var truncated: Bool = false

    var hasTimeline: Bool { !timeline.isEmpty }

    var durationText: String {
        guard let duration = stats.durationMs, duration > 0 else { return "—" }
        let seconds = duration / 1000.0
        if seconds < 60 { return String(format: "%.0f 秒", seconds) }
        if seconds < 3600 { return String(format: "%.1f 分钟", seconds / 60) }
        return String(format: "%.1f 小时", seconds / 3600)
    }

    var toolUsageTop: [ToolUsageStat] {
        stats.toolUsage.sorted { $0.count > $1.count }.prefix(8).map { $0 }
    }
}


// MARK: - One-click migrate-all (v1.4)
struct MigrateAllSource: Identifiable, Sendable {
    var id: String
    var name: String
    var sessionCount: Int
    var recentAtMs: Double?
    var selected: Bool = true
}

struct MigrateAllPlan: Sendable {
    var targetID: String
    var targetName: String
    var targetStorePath: String?
    var howToSee: String?
    var mode: MigrationMode
    var sessionMode: SessionMode
    var sources: [MigrateAllSource]
    var totalSessions: Int
    var limit: Int?
    var sinceDays: Int?
    var generatedAt: Date = Date()
    var sessionsBySource: [String: [SessionRow]] = [:]
    var skippedEstimate: Int? = nil
    var sourceRoots: [String: String] = [:]     // 测试/高级：按来源覆盖 --root
    var targetHome: String? = nil              // 测试/高级：目标 home 覆盖
    var environment: [String: String]? = nil   // 测试隔离：子进程环境覆盖
}

struct MigrateAllReport: Sendable {
    var plan: MigrateAllPlan
    var items: [MigrationItemResult]
    var journalPath: String?
    var elapsed: TimeInterval
    var cancelled: Bool

    var okCount: Int { items.filter { $0.ok && !$0.skipped }.count }
    var failCount: Int { items.filter { !$0.ok }.count }
    var skippedCount: Int { items.filter { $0.skipped }.count }
    var movedCount: Int { items.filter { $0.sourceMoved }.count }
}
