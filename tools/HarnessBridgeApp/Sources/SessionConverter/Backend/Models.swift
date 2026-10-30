import Foundation

// MARK: - Generic JSON value (keeps unknown / evolving CLI fields decodable)
indirect enum JSONValue: Codable, Sendable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let v = try? container.decode(Bool.self) {
            self = .bool(v)
        } else if let v = try? container.decode(Double.self) {
            self = .number(v)
        } else if let v = try? container.decode(String.self) {
            self = .string(v)
        } else if let v = try? container.decode([JSONValue].self) {
            self = .array(v)
        } else if let v = try? container.decode([String: JSONValue].self) {
            self = .object(v)
        } else {
            self = .null
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let v): try container.encode(v)
        case .number(let v): try container.encode(v)
        case .string(let v): try container.encode(v)
        case .array(let v): try container.encode(v)
        case .object(let v): try container.encode(v)
        }
    }

    var displayString: String {
        switch self {
        case .null: return "—"
        case .bool(let v): return v ? "true" : "false"
        case .number(let v):
            if v.rounded() == v { return String(Int(v)) }
            return String(format: "%.2f", v)
        case .string(let v): return v
        case .array(let v): return v.map { $0.displayString }.joined(separator: ", ")
        case .object(let v):
            return v.keys.sorted().map { "\($0)=\(v[$0]!.displayString)" }.joined(separator: ", ")
        }
    }

    subscript(key: String) -> JSONValue? {
        if case .object(let dict) = self { return dict[key] }
        return nil
    }

    var intValue: Int? {
        switch self {
        case .number(let v): return Int(v)
        case .string(let s): return Int(s)
        default: return nil
        }
    }

    var boolValue: Bool? {
        switch self {
        case .bool(let v): return v
        case .string(let s): return ["true", "yes", "1"].contains(s.lowercased())
        default: return nil
        }
    }

    static func prettyPrinted(_ value: JSONValue) -> String {
        guard let data = try? JSONEncoder().encode(value),
              let obj = try? JSONSerialization.jsonObject(with: data),
              let pretty = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: pretty, encoding: .utf8) else {
            return value.displayString
        }
        return text
    }
}

// MARK: - asi list --json
struct SessionRow: Codable, Identifiable, Sendable, Hashable {
    var source: String?
    var id: String
    var title: String?
    var cwd: String?
    var path: String?
    var model: String?
    var lines: Int?
    var createdAtMs: Double?
    var updatedAtMs: Double?

    enum CodingKeys: String, CodingKey {
        case source, id, title, cwd, path, model, lines
        case createdAtMs = "created_at_ms"
        case updatedAtMs = "updated_at_ms"
    }

    var displayTitle: String {
        let t = (title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? "(无标题)" : t
    }
}

struct ListEnvelope: Codable, Sendable {
    var ok: Bool?
    var command: String?
    var source: String?
    var count: Int?
    var sessions: [SessionRow]?
}

// MARK: - asi convert --json
struct IRStats: Codable, Sendable, Hashable {
    var events: Int?
    var userMessages: Int?
    var assistantMessages: Int?
    var reasoningBlocks: Int?
    var toolCalls: Int?
    var toolResults: Int?
    var unpairedToolCalls: Int?
    var compactions: Int?
    var systemMessages: Int?

    enum CodingKeys: String, CodingKey {
        case events
        case userMessages = "user_messages"
        case assistantMessages = "assistant_messages"
        case reasoningBlocks = "reasoning_blocks"
        case toolCalls = "tool_calls"
        case toolResults = "tool_results"
        case unpairedToolCalls = "unpaired_tool_calls"
        case compactions
        case systemMessages = "system_messages"
    }
}

struct ConvertResult: Codable, Sendable {
    var source: String?
    var sourceSessionID: String?
    var status: String?
    var outputDir: String?
    var ir: String?
    var artifact: String?
    var nativeRoot: String?
    var relpath: String?
    var events: Int?
    var steps: Int?
    var warnings: [String]?
    var lossy: [String]?
    var error: String?
    var stats: IRStats?
    var target: String?

    enum CodingKeys: String, CodingKey {
        case source, status, ir, artifact, relpath, events, steps, warnings, lossy, error, stats, target
        case sourceSessionID = "source_session_id"
        case outputDir = "output_dir"
        case nativeRoot = "native_root"
    }

    var isOK: Bool { status == "ok" }
}

struct ConvertSummary: Codable, Sendable {
    var converted: Int?
    var failed: Int?
    var total: Int?
}

struct ConvertEnvelope: Codable, Sendable {
    var ok: Bool?
    var command: String?
    var source: String?
    var to: String?
    var out: String?
    var summary: ConvertSummary?
    var results: [ConvertResult]?
    var error: String?
}

// MARK: - asi verify --json
struct VerifyEntry: Codable, Sendable {
    var path: String?
    var status: String?
    var errors: [String]?
    var warnings: [String]?
    var info: JSONValue?
    var header: JSONValue?
}

struct VerifyEnvelope: Codable, Sendable {
    var ok: Bool?
    var command: String?
    var checked: Int?
    var failed: Int?
    var error: String?
    var results: [VerifyEntry]?
}

// MARK: - matrices
struct MatrixSummary: Sendable {
    var pass: Int?
    var partial: Int?
    var fail: Int?
    var total: Int?
    var harnesses: Int?
    var directionsTotal: Int?
    var evidence: String?
    var realLocal: Int?
    var constructed: Int?
    var l3DSH: Int?

    var text: String {
        var parts: [String] = []
        if let harnesses { parts.append("harnesses=\(harnesses)") }
        if let directionsTotal { parts.append("directions=\(directionsTotal)") }
        if let pass { parts.append("pass=\(pass)") }
        if let partial { parts.append("partial=\(partial)") }
        if let fail { parts.append("fail=\(fail)") }
        if let realLocal, realLocal > 0 { parts.append("REAL-LOCAL=\(realLocal)") }
        if let constructed, constructed > 0 { parts.append("CONSTRUCTED=\(constructed)") }
        if let l3DSH { parts.append("L3=\(l3DSH)") }
        return parts.isEmpty ? "—" : parts.joined(separator: " · ")
    }
}

struct MatrixRow: Sendable, Identifiable {
    var id: String { harness + "|" + (fixture ?? "") }
    var harness: String
    var evidence: String?
    var status: String?
    var levels: [(String, Bool?)]
    var messages: String?
    var toolCalls: String?
    var fixture: String?
    var detail: String?

    var levelText: String {
        levels.map { "\($0.0.uppercased())=\($0.1 == nil ? "—" : ($0.1 == true ? "✓" : "✗"))" }
            .joined(separator: " ")
    }
}

struct MatrixRunResult: Sendable {
    var kind: String
    var ok: Bool
    var summary: MatrixSummary?
    var rows: [MatrixRow]
    var reportPath: String?
    var outputDir: String?
    var elapsed: TimeInterval
    var raw: JSONValue?
}

// MARK: - capabilities (parsed from asi --help)
struct Capabilities: Sendable {
    var commands: [String] = []
    var sources: [String] = []
    var fromChoices: [String] = []
    var targetChoices: [String] = []
    var matrixKinds: [String] = []
    var asiVersion: String = ""

    func hasMatrix() -> Bool { !matrixKinds.isEmpty }
}

// MARK: - UI helper wrappers
struct ConvertRunView: Identifiable, Sendable {
    let id = UUID()
    var from: String
    var to: String
    var startedAt = Date()
    var elapsed: TimeInterval
    var envelope: ConvertEnvelope
    var error: String?
    var outputDir: String

    var result: ConvertResult? { envelope.results?.first }
    var ok: Bool { (envelope.ok ?? false) && (result?.isOK ?? false) }
    var verify: VerifyEnvelope?
}

struct BatchRow: Sendable, Identifiable {
    let id = UUID()
    var source: String
    var sessionTitle: String
    var sessionID: String
    var target: String
    var ok: Bool
    var events: Int?
    var steps: Int?
    var verifyStatus: String?
    var error: String?
    var outputDir: String?
    var artifact: String?
}

struct SourceEntry: Sendable, Identifiable, Hashable {
    var id: String
    var name: String
    var group: String
    var count: Int?
}

enum SourceGroups {
    static let order = [
        "原生 Harness（批 1）",
        "OSS 采集轨迹（批 2）",
        "原生 fixtures（批 3）",
        "原生 fixtures / 构造 DB（批 4）",
        "新 Harness（批 5）",
        "其它 sources",
    ]

    static let names: [String: String] = [
        "claude": "Claude Code", "codex": "Codex", "omp": "OMP (oh-my-pi)",
        "qoder": "Qoder", "dsh": "DSH (DeepSeek Harness)",
        "oss": "OSS 采集轨迹（traj-session/1）",
        "copilot": "GitHub Copilot CLI", "gemini": "Gemini CLI", "aider": "Aider",
        "cursor": "Cursor CLI", "qwen": "Qwen Code", "pi": "Pi",
        "openclaw": "OpenClaw", "kimi": "Kimi Code", "grok": "Grok Build",
        "droid": "Factory Droid", "antigravity": "Google Antigravity",
        "hermes": "Hermes", "devin": "Devin CLI", "opencode": "OpenCode",
        "goose": "Goose", "continue": "Continue", "junie": "Junie",
        "kiro": "Kiro CLI", "crush": "Crush", "cline": "Cline", "roo": "Roo Code",
        "kilo-code": "Kilo Code", "codebuff": "Codebuff", "openhands": "OpenHands",
        "vibe": "Mistral Vibe", "codebuddy": "Tencent CodeBuddy", "fx": "FX",
        "mini-swe-agent": "Mini SWE Agent",
    ]

    static func group(for source: String) -> String {
        let b1: Set<String> = ["claude", "codex", "omp", "qoder", "dsh"]
        let b3: Set<String> = ["copilot", "gemini", "aider", "cursor", "qwen", "pi"]
        let b4: Set<String> = ["openclaw", "kimi", "grok", "droid", "antigravity", "hermes", "devin", "opencode"]
        if b1.contains(source) { return order[0] }
        if source == "oss" { return order[1] }
        if b3.contains(source) { return order[2] }
        if b4.contains(source) { return order[3] }
        return order[4]
    }

    static func displayName(for source: String) -> String {
        names[source] ?? source
    }
}
