import Foundation

// MARK: - Command result / errors
struct CommandResult: Sendable {
    var command: String
    var exitCode: Int32
    var stdout: String
    var stderr: String
    var duration: TimeInterval
    var timedOut: Bool
    var wasCancelled: Bool = false

    var ok: Bool { exitCode == 0 && !timedOut && !wasCancelled }
}

enum BackendError: LocalizedError {
    case workspaceNotFound
    case asiNotFound(String)
    case pythonNotFound
    case launchFailed(String)
    case timeout(String, TimeInterval)
    case nonZero(String, Int32, String)
    case decoding(String, String)
    case invalidResponse(String)

    var errorDescription: String? {
        switch self {
        case .workspaceNotFound:
            return "找不到 workspace（含 tools/agent-session-import/asi 的目录）。可在设置中手动指定。"
        case .asiNotFound(let p):
            return "找不到可执行的 asi CLI：\(p)"
        case .pythonNotFound:
            return "找不到 python3（coverage-report 需要）"
        case .launchFailed(let msg):
            return "进程启动失败：\(msg)"
        case .timeout(let cmd, let seconds):
            return "命令超时（\(Int(seconds))s）：\(cmd)"
        case .nonZero(let cmd, let code, let tail):
            return "命令失败（exit \(code)）：\(cmd)\n\(tail)"
        case .decoding(let what, let tail):
            return "解析 \(what) JSON 失败：\(tail)"
        case .invalidResponse(let msg):
            return "后端返回异常：\(msg)"
        }
    }
}

private final class PipeBuffer: @unchecked Sendable {
    var data = Data()
}

// MARK: - Backend bridge (Process + Pipe; no shell interpolation)
final class BackendBridge: @unchecked Sendable {
    let workspace: URL
    let timeoutDefault: TimeInterval
    private let fileManager = FileManager.default

    init(workspace: URL, timeoutDefault: TimeInterval = 120) {
        self.workspace = workspace
        self.timeoutDefault = timeoutDefault
    }

    var asiPath: URL { Paths.asiURL(in: workspace) }
    var coverageScript: URL { workspace.appendingPathComponent("tools/coverage-report.py") }

    static var enrichedEnvironment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        var prefixes: [String] = []
        if let res = Bundle.main.resourceURL {
            let pythonBin = res.appendingPathComponent("python/bin").path
            let binDir = res.appendingPathComponent("bin").path
            if FileManager.default.isExecutableFile(atPath: pythonBin + "/python3") {
                prefixes.append(pythonBin)
                env["PYTHONDONTWRITEBYTECODE"] = "1"
            }
            if FileManager.default.isExecutableFile(atPath: binDir + "/zstd") {
                prefixes.append(binDir)
            }
        }
        let extra = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin"
        let current = env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        var parts = current.split(separator: ":").map(String.init)
        for item in extra.split(separator: ":").map(String.init).reversed()
        where !parts.contains(item) {
            parts.insert(item, at: 0)
        }
        var seen = Set<String>()
        var finalParts: [String] = []
        for item in prefixes + parts where !seen.contains(item) {
            seen.insert(item)
            finalParts.append(item)
        }
        env["PATH"] = finalParts.joined(separator: ":")
        env["LC_ALL"] = "en_US.UTF-8"
        env["LANG"] = "en_US.UTF-8"
        return env
    }

    // MARK: low-level run
    /// Deterministic pipe handling: two background readers drain stdout/stderr
    /// concurrently from process start, so large JSON payloads (e.g.
    /// `session-detail --max-events 0`) never fill the pipe buffer or deadlock.
    func run(_ args: [String],
             executable: URL? = nil,
             timeout: TimeInterval? = nil,
             cwd: URL? = nil,
             extraEnvironment: [String: String]? = nil,
             cancellation: CancellationFlag? = nil) throws -> CommandResult {
        let exe = executable ?? asiPath
        guard fileManager.isExecutableFile(atPath: exe.path) else {
            throw BackendError.asiNotFound(exe.path)
        }
        let timeout = timeout ?? timeoutDefault
        let proc = Process()
        proc.executableURL = exe
        proc.arguments = args
        proc.currentDirectoryURL = cwd ?? workspace
        var environment = Self.enrichedEnvironment
        if let extraEnvironment {
            for (key, value) in extraEnvironment { environment[key] = value }
        }
        proc.environment = environment
        let outPipe = Pipe()
        let errPipe = Pipe()
        proc.standardOutput = outPipe
        proc.standardError = errPipe
        proc.standardInput = FileHandle.nullDevice

        let started = Date()
        do {
            try proc.run()
        } catch {
            throw BackendError.launchFailed(error.localizedDescription)
        }

        let outHandle = outPipe.fileHandleForReading
        let errHandle = errPipe.fileHandleForReading
        let outBox = PipeBuffer()
        let errBox = PipeBuffer()
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            outBox.data = outHandle.readDataToEndOfFile()
            group.leave()
        }
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            errBox.data = errHandle.readDataToEndOfFile()
            group.leave()
        }

        var timedOut = false
        var cancelled = false
        let deadline = started.addingTimeInterval(timeout)
        while proc.isRunning && Date() < deadline {
            if cancellation?.isSet() == true {
                cancelled = true
                break
            }
            usleep(20_000)
        }
        if cancelled, proc.isRunning {
            // Stop the real backend process: no further writes/renames happen.
            kill(proc.processIdentifier, SIGTERM)
            var waitSteps = 0
            while proc.isRunning && waitSteps < 20 {   // up to ~1s grace
                usleep(50_000)
                waitSteps += 1
            }
            if proc.isRunning { kill(proc.processIdentifier, SIGKILL) }
        }
        if !cancelled, proc.isRunning {
            timedOut = true
            proc.terminate()
            usleep(200_000)
            if proc.isRunning {
                kill(proc.processIdentifier, SIGKILL)
            }
        }
        proc.waitUntilExit()
        group.wait()
        try? outHandle.close()
        try? errHandle.close()

        let duration = Date().timeIntervalSince(started)
        let command = ([exe.path] + args).joined(separator: " ")
        let result = CommandResult(command: command,
                                   exitCode: proc.terminationStatus,
                                   stdout: String(data: outBox.data, encoding: .utf8) ?? "",
                                   stderr: String(data: errBox.data, encoding: .utf8) ?? "",
                                   duration: duration,
                                   timedOut: timedOut,
                                   wasCancelled: cancelled)
        if timedOut {
            throw BackendError.timeout(command, timeout)
        }
        return result
    }

    // MARK: high-level: version / capabilities
    func version() throws -> String {
        let r = try run(["--version"], timeout: 20)
        let text = (r.stdout + r.stderr).trimmingCharacters(in: .whitespacesAndNewlines)
        return text.split(separator: "\n").first.map(String.init) ?? text
    }

    func help(_ args: [String] = []) throws -> String {
        let r = try run(args + ["--help"], timeout: 30)
        return r.stdout.isEmpty ? r.stderr : r.stdout
    }

    func capabilities() throws -> Capabilities {
        var caps = Capabilities()
        caps.asiVersion = (try? version()) ?? "unknown"
        let top = (try? help()) ?? ""
        caps.commands = Self.parseChoices(top)
        let listHelp = (try? help(["list"])) ?? ""
        caps.sources = Self.parseChoices(listHelp)
        if caps.sources.isEmpty {
            caps.sources = ["claude", "codex", "omp", "qoder", "dsh"]
        }
        let convertHelp = (try? help(["convert"])) ?? ""
        caps.fromChoices = Self.parseChoices(convertHelp, token: "from")
        caps.targetChoices = Self.parseChoices(convertHelp, token: "to")
        caps.matrixKinds = caps.commands.filter { $0 == "matrix" || $0.hasPrefix("matrix-batch") }
        if caps.matrixKinds.isEmpty { caps.matrixKinds = ["matrix"] }
        return caps
    }

    static func parseChoices(_ helpText: String, token: String? = nil) -> [String] {
        var patterns: [String] = []
        if let token {
            patterns.append("--\(token)\\s+\\{([^}]*)\\}")
        }
        patterns.append("\\{([A-Za-z0-9_.,-]+)\\}")
        for pattern in patterns {
            guard let re = try? NSRegularExpression(pattern: pattern) else { continue }
            let ns = helpText as NSString
            let range = NSRange(location: 0, length: ns.length)
            if let match = re.firstMatch(in: helpText, range: range), match.numberOfRanges > 1 {
                let body = ns.substring(with: match.range(at: 1))
                let choices = body.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
                    .filter { !$0.isEmpty }
                if !choices.isEmpty { return choices }
            }
        }
        return []
    }

    // MARK: high-level: list
    func list(source: String, timeout: TimeInterval = 120) throws -> [SessionRow] {
        let r = try run(["list", source, "--json", "--limit", "2000"], timeout: timeout)
        guard r.ok else {
            throw BackendError.nonZero(r.command, r.exitCode, Self.tail(r.stderr.isEmpty ? r.stdout : r.stderr))
        }
        guard let data = r.stdout.data(using: .utf8) else {
            throw BackendError.decoding("list", "stdout 非 UTF-8")
        }
        let decoder = JSONDecoder()
        if let env = try? decoder.decode(ListEnvelope.self, from: data), let rows = env.sessions {
            return rows
        }
        if let rows = try? decoder.decode([SessionRow].self, from: data) {
            return rows
        }
        throw BackendError.decoding("list \(source)", Self.tail(r.stdout))
    }

    // MARK: high-level: convert
    func convert(from: String,
                 to: String,
                 session: String,
                 outDir: URL,
                 targetCwd: String? = nil,
                 keepSystem: Bool = false,
                 timeout: TimeInterval = 180,
                 extraEnvironment: [String: String]? = nil) throws -> CommandResult {
        try Paths.ensureDirectory(outDir)
        var args = ["convert", "--from", from, "--to", to, "--session", session,
                    "--out", outDir.path, "--json"]
        if keepSystem { args.append("--keep-system") }
        if let targetCwd, !targetCwd.isEmpty { args += ["--target-cwd", targetCwd] }
        return try run(args, timeout: timeout, extraEnvironment: extraEnvironment)
    }

    func convertParsed(from: String,
                       to: String,
                       session: String,
                       outDir: URL,
                       targetCwd: String? = nil,
                       keepSystem: Bool = false,
                       extraEnvironment: [String: String]? = nil) throws -> ConvertEnvelope {
        let r = try convert(from: from, to: to, session: session, outDir: outDir,
                            targetCwd: targetCwd, keepSystem: keepSystem,
                            extraEnvironment: extraEnvironment)
        guard let data = r.stdout.data(using: .utf8) else {
            throw BackendError.decoding("convert", "stdout 非 UTF-8")
        }
        let env = try JSONDecoder().decode(ConvertEnvelope.self, from: data)
        if env.ok == false, let err = env.error, env.results?.isEmpty ?? true {
            throw BackendError.invalidResponse(err)
        }
        return env
    }

    func verify(path: String, timeout: TimeInterval = 120) throws -> VerifyEnvelope {
        let r = try run(["verify", path, "--json"], timeout: timeout)
        guard let data = r.stdout.data(using: .utf8) else {
            throw BackendError.decoding("verify", "stdout 非 UTF-8")
        }
        if let env = try? JSONDecoder().decode(VerifyEnvelope.self, from: data) {
            return env
        }
        // Non-JSON response: surface as a synthetic failed verify.
        return VerifyEnvelope(ok: false, command: "verify", checked: nil, failed: nil,
                              error: Self.tail(r.stderr.isEmpty ? r.stdout : r.stderr),
                              results: nil)
    }

    // MARK: high-level: matrix / coverage
    func matrix(kind: String,
                limit: Int?,
                outDir: URL,
                timeout: TimeInterval = 600) throws -> MatrixRunResult {
        try Paths.ensureDirectory(outDir)
        let stage = outDir.appendingPathComponent("stage", isDirectory: true)
        let report = outDir.appendingPathComponent("report.json")
        var args = [kind, "--json", "--out", stage.path, "--report", report.path]
        if let limit, limit > 0 {
            args += ["--limit", "\(limit)"]
        }
        let r = try run(args, timeout: timeout)
        guard let data = r.stdout.data(using: .utf8) else {
            throw BackendError.decoding("matrix", "stdout 非 UTF-8")
        }
        let decoded = try JSONDecoder().decode(JSONValue.self, from: data)
        return Self.parseMatrix(kind: kind, json: decoded, reportPath: report.path,
                                outputDir: outDir.path, elapsed: r.duration, exitOK: r.ok)
    }

    func coverage() throws -> JSONValue {
        let python = Paths.findPython3()
        guard fileManager.isExecutableFile(atPath: python) else {
            throw BackendError.pythonNotFound
        }
        let r = try run([coverageScript.path, "--json"], executable: URL(fileURLWithPath: python),
                        timeout: 60)
        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw BackendError.decoding("coverage-report", Self.tail(r.stderr.isEmpty ? r.stdout : r.stderr))
        }
        return value
    }

    // MARK: parsing helpers
    static func parseMatrix(kind: String, json: JSONValue, reportPath: String,
                            outputDir: String, elapsed: TimeInterval, exitOK: Bool) -> MatrixRunResult {
        var summary = MatrixSummary()
        if case .object(let top) = json {
            if let s = top["summary"], case .object(let sd) = s {
                summary.pass = sd["pass"]?.intValue
                summary.partial = sd["partial"]?.intValue
                summary.fail = sd["fail"]?.intValue
                summary.harnesses = sd["harnesses"]?.intValue
                summary.directionsTotal = sd["directions_total"]?.intValue
                summary.realLocal = sd["real_local"]?.intValue
                summary.constructed = sd["constructed"]?.intValue
                summary.l3DSH = sd["l3_dsh"]?.intValue
                if let ev = sd["evidence_level"], case .string(let e) = ev { summary.evidence = e }
                if summary.pass == nil {
                    summary.pass = sd["pass"]?.intValue
                }
            }
            if summary.fail == nil { summary.fail = top["fail"]?.intValue }
        }
        let rows = extractMatrixRows(json)
        if summary.harnesses == nil { summary.harnesses = rows.isEmpty ? nil : rows.count }
        return MatrixRunResult(kind: kind, ok: exitOK, summary: summary, rows: rows,
                               reportPath: reportPath, outputDir: outputDir, elapsed: elapsed, raw: json)
    }

    static func extractMatrixRows(_ json: JSONValue) -> [MatrixRow] {
        guard case .object(let top) = json else { return [] }
        let candidateKeys = ["entries", "directions", "rows", "harnesses", "results", "fixtures"]
        var items: [JSONValue] = []
        for key in candidateKeys {
            if case .array(let arr)? = top[key], !arr.isEmpty {
                items = arr
                break
            }
        }
        var rows: [MatrixRow] = []
        for item in items {
            guard case .object(let obj) = item else { continue }
            var harness = obj["harness"]?.displayString
                ?? obj["source"]?.displayString
                ?? obj["source_harness"]?.displayString
                ?? obj["adapter"]?.displayString
            if harness == nil {
                let from = obj["from"]?.displayString ?? "?"
                let to = obj["to"]?.displayString ?? "?"
                harness = "\(from) → \(to)"
            }
            guard let harness else { continue }
            var levels: [(String, Bool?)] = []
            let levelKeys = ["b5f0", "b5f1", "b5f2", "b5f2b", "b4f0", "b4f1", "b4f2", "b4f2b",
                             "b3f0", "b3f1", "b3f2", "b3f2b", "f0", "f1", "f2", "f2b", "f3",
                             "l0", "l1", "l2", "l3"]
            for key in levelKeys {
                if let value = obj[key] {
                    let ok: Bool?
                    switch value {
                    case .object(let d): ok = d["ok"]?.boolValue
                    case .bool(let b): ok = b
                    default: ok = nil
                    }
                    levels.append((key, ok))
                }
            }
            if levels.isEmpty {
                if let status = obj["status"]?.displayString {
                    levels.append(("status", ["pass", "ok", "通过"].contains(status.lowercased())))
                }
            }
            let evidence = obj["evidence_level"]?.displayString ?? obj["evidence"]?.displayString
                ?? obj["kind"]?.displayString
            var status = obj["status"]?.displayString
            if status == nil, case .object(let d)? = obj["summary"] { status = d["status"]?.displayString }
            let fixture = obj["fixture"]?.displayString ?? obj["fixture_path"]?.displayString
                ?? obj["source_path"]?.displayString ?? obj["artifact"]?.displayString
            var messages = obj["messages"]?.displayString ?? obj["message_count"]?.displayString
                ?? obj["source_messages"]?.displayString
            var toolCalls = obj["tool_calls"]?.displayString ?? obj["tool_call_count"]?.displayString
            if messages == nil, case .object(let l0)? = obj["f0"] { messages = l0["events"]?.displayString }
            if toolCalls == nil, case .object(let l0)? = obj["l0"],
               case .object(let stats)? = l0["ir_stats"] {
                toolCalls = stats["tool_calls"]?.displayString
            }
            var detail = obj["detail"]?.displayString ?? ""
            if detail.isEmpty, case .array(let warnings)? = obj["warnings"] {
                detail = warnings.compactMap { $0.displayString }.joined(separator: " · ")
            }
            rows.append(MatrixRow(harness: harness, evidence: evidence, status: status,
                                  levels: levels, messages: messages, toolCalls: toolCalls,
                                  fixture: fixture, detail: detail.isEmpty ? nil : detail))
        }
        return rows
    }

    static func tail(_ text: String, limit: Int = 3000) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.count <= limit { return trimmed }
        return "…" + trimmed.suffix(limit)
    }
}

// MARK: - Thread-safe pipe collector
final class OutputCollector: @unchecked Sendable {
    private let lock = NSLock()
    private var stdoutData = Data()
    private var stderrData = Data()

    func appendStdout(_ data: Data) {
        lock.lock(); stdoutData.append(data); lock.unlock()
    }

    func appendStderr(_ data: Data) {
        lock.lock(); stderrData.append(data); lock.unlock()
    }

    var stdoutString: String {
        lock.lock(); defer { lock.unlock() }
        return String(data: stdoutData, encoding: .utf8) ?? ""
    }

    var stderrString: String {
        lock.lock(); defer { lock.unlock() }
        return String(data: stderrData, encoding: .utf8) ?? ""
    }
}
