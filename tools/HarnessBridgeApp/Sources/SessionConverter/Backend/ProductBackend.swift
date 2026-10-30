import Foundation

// MARK: - user-readable errors
enum ProductError: LocalizedError {
    case userFacing(String)
    case backend(String)

    var errorDescription: String? {
        switch self {
        case .userFacing(let message): return message
        case .backend(let message): return message
        }
    }
}

/// Product-level backend: prefers the new `detect` / `preview` / `migrate`
/// commands when the CLI exposes them, and gracefully falls back to the
/// existing `list` / `convert` / `verify` commands otherwise.
final class ProductBackend: @unchecked Sendable {
    let bridge: BackendBridge
    let caps: Capabilities
    private var cachedMigrateHelp: String?

    init(bridge: BackendBridge, caps: Capabilities) {
        self.bridge = bridge
        self.caps = caps
    }

    var hasDetect: Bool { caps.commands.contains("detect") }
    var hasPreview: Bool { caps.commands.contains("preview") }
    var hasMigrate: Bool { caps.commands.contains("migrate") }
    var hasSessionDetail: Bool { caps.commands.contains("session-detail") }

    var migrateHelpText: String {
        if let cached = cachedMigrateHelp { return cached }
        let help = (try? bridge.help(["migrate"])) ?? ""
        cachedMigrateHelp = help
        return help
    }
    var supportsSessionMode: Bool { migrateHelpText.contains("--session-mode") }
    var supportsOverwrite: Bool { migrateHelpText.contains("--overwrite") }
    var supportsMigrateAll: Bool { caps.commands.contains("migrate-all") }
    var supportsMigrateRestore: Bool { caps.commands.contains("migrate-restore") }

    var modeDescription: String {
        if hasDetect && hasPreview && hasMigrate {
            return "产品级后端接口已就绪"
        }
        return "兼容模式（检测/预览/迁移由现有命令组合实现）"
    }

    func targetAvailable(_ id: String) -> Bool {
        id == "atif" || caps.targetChoices.contains(id)
    }

    // MARK: - detect
    func detect(fast: Bool = true) throws -> [HarnessInfo] {
        if hasDetect {
            if let harnesses = try? detectViaCommand(fast: fast), !harnesses.isEmpty {
                return mergeWithCatalog(harnesses)
            }
        }
        return try detectViaList()
    }

    private func detectViaCommand(fast: Bool = true) throws -> [HarnessInfo] {
        var args = ["detect", "--json"]
        if fast { args.append("--fast") }
        let r: CommandResult
        do {
            r = try bridge.run(args, timeout: 120)
        } catch {
            if fast {
                // `--fast` may be unsupported by an older backend; retry full scan.
                r = try bridge.run(["detect", "--json"], timeout: 180)
            } else {
                throw error
            }
        }
        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw ProductError.backend("检测结果格式无法识别")
        }
        var harnesses: [HarnessInfo] = []
        var items: [JSONValue] = []
        if case .array(let arr)? = value["harnesses"] { items = arr }
        if case .array(let arr)? = value["harnesses"] { items = arr }
        if case .array(let arr) = value { items = arr }
        for item in items {
            guard case .object(let obj) = item, let id = obj["id"]?.displayString else { continue }
            let count = obj["session_count"]?.intValue ?? 0
            var capsObj: JSONValue?
            if case .object(let c)? = obj["capabilities"] { capsObj = .object(c) }
            let installSupported = obj["install_supported"]?.boolValue
                ?? capsObj?["install"]?.boolValue
                ?? false
            let installExperimental = obj["install_experimental"]?.boolValue
                ?? capsObj?["install_experimental"]?.boolValue
                ?? false
            harnesses.append(HarnessInfo(
                id: id,
                name: obj["display_name"]?.displayString ?? obj["name"]?.displayString ?? HarnessCatalog.name(for: id),
                colorHex: HarnessCatalog.color(for: id),
                detected: obj["detected"]?.boolValue ?? (count > 0),
                sessionCount: count,
                recentAtMs: obj["recent_at"]?.intValue.map(Double.init),
                storePath: obj["store_path"]?.displayString ?? obj["path"]?.displayString ?? HarnessCatalog.storePath(for: id),
                family: obj["family"]?.displayString,
                sessionDirHint: obj["session_dir_hint"]?.displayString ?? obj["path"]?.displayString,
                installSupported: installSupported,
                installExperimental: installExperimental,
                howToSee: obj["how_to_see"]?.displayString ?? obj["notes"]?.displayString
            ))
        }
        return harnesses
    }

    private func detectViaList() throws -> [HarnessInfo] {
        var result: [HarnessInfo] = []
        for item in HarnessCatalog.primary {
            let present = HarnessCatalog.isStorePresent(item.id)
            var count = 0
            var recent: Double?
            if present {
                if let rows = try? bridge.list(source: item.id, timeout: 90) {
                    count = rows.count
                    recent = rows.compactMap(\.createdAtMs).max()
                }
            }
            result.append(HarnessInfo(id: item.id,
                                      name: item.name,
                                      colorHex: item.color,
                                      detected: present,
                                      sessionCount: count,
                                      recentAtMs: recent,
                                      storePath: HarnessCatalog.storePath(for: item.id),
                                      family: item.family))
        }
        return result
    }

    private func mergeWithCatalog(_ harnesses: [HarnessInfo]) -> [HarnessInfo] {
        var byID = Dictionary(uniqueKeysWithValues: harnesses.map { ($0.id, $0) })
        var merged: [HarnessInfo] = []
        for catalog in HarnessCatalog.primary {
            if var hit = byID.removeValue(forKey: catalog.id) {
                hit.name = catalog.name
                hit.colorHex = catalog.color
                merged.append(hit)
            } else {
                merged.append(HarnessInfo(id: catalog.id, name: catalog.name,
                                          colorHex: catalog.color,
                                          detected: false, sessionCount: 0,
                                          recentAtMs: nil,
                                          storePath: HarnessCatalog.storePath(for: catalog.id),
                                          family: catalog.family))
            }
        }
        // keep any extra harnesses the backend reported (non-primary)
        merged.append(contentsOf: byID.values.sorted { $0.id < $1.id })
        return merged
    }

    func listSessions(source: String) throws -> [SessionRow] {
        try bridge.list(source: source, timeout: 120)
    }

    func listSessions(source: String, root: String?, environment: [String: String]? = nil) throws -> [SessionRow] {
        guard let root, !root.isEmpty else {
            if let environment {
                let r = try bridge.run(["list", source, "--json", "--limit", "2000"], timeout: 120,
                                       extraEnvironment: environment)
                return try Self.decodeRows(r)
            }
            return try listSessions(source: source)
        }
        let r = try bridge.run(["list", source, "--json", "--limit", "2000", "--root", root], timeout: 120,
                               extraEnvironment: environment)
        guard r.ok else {
            throw BackendError.nonZero(r.command, r.exitCode, BackendBridge.tail(r.stderr.isEmpty ? r.stdout : r.stderr))
        }
        guard let data = r.stdout.data(using: .utf8) else {
            throw BackendError.decoding("list", "stdout 非 UTF-8")
        }
        let decoder = JSONDecoder()
        if let env = try? decoder.decode(ListEnvelope.self, from: data), let rows = env.sessions {
            return rows
        }
        return (try? decoder.decode([SessionRow].self, from: data)) ?? []
    }

    // MARK: - session detail (product v1.2)
    /// Prefers the product-level `session-detail` command; falls back to a
    /// preview-derived summary (meta + recent messages, no full timeline).
    func sessionDetail(source: String,
                       session: SessionRow,
                       maxEvents: Int = 2000,
                       textLimit: Int = 400) throws -> SessionDetail {
        if hasSessionDetail {
            do {
                return try detailViaCommand(source: source, session: session,
                                            maxEvents: maxEvents, textLimit: textLimit)
            } catch {
                // The command exists but failed (timeout / malformed JSON / non-zero):
                // surface a readable error so the detail page can offer retry instead
                // of silently showing a misleading "upgrade backend" fallback.
                throw ProductError.userFacing("读取会话详情失败：\(Self.userMessage(for: error))。请稍后重试。")
            }
        }
        // Command not implemented by this backend → preview-based summary mode.
        return fallbackDetail(source: source, session: session)
    }

    private func detailViaCommand(source: String,
                                  session: SessionRow,
                                  maxEvents: Int,
                                  textLimit: Int) throws -> SessionDetail {
        var args = ["session-detail", "--from", source, "--session", session.id,
                    "--json", "--text-limit", "\(textLimit)"]
        if maxEvents > 0 { args += ["--max-events", "\(maxEvents)"] }
        let r = try bridge.run(args, timeout: 180)
        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data),
              value["ok"]?.boolValue != false else {
            throw ProductError.backend("会话详情格式无法识别")
        }
        return Self.parseDetail(value, source: source, session: session)
    }

    static func parseDetail(_ value: JSONValue, source: String, session: SessionRow) -> SessionDetail {
        var detail = SessionDetail(source: value["source"]?.displayString ?? source,
                                   sessionID: value["session_id"]?.displayString ?? session.id,
                                   title: session.displayTitle)
        if case .object(let meta)? = value["meta"] {
            detail.title = meta["title"]?.displayString ?? detail.title
            detail.cwd = meta["cwd"]?.displayString ?? session.cwd
            detail.model = meta["model"]?.displayString ?? session.model
            detail.provider = meta["provider"]?.displayString
            detail.createdAtMs = meta["created_at_ms"]?.intValue.map(Double.init) ?? session.createdAtMs
            detail.updatedAtMs = meta["updated_at_ms"]?.intValue.map(Double.init) ?? session.updatedAtMs
            detail.path = meta["path"]?.displayString ?? session.path
            detail.sourceLabel = meta["source_label"]?.displayString
            detail.evidenceLevel = meta["evidence_level"]?.displayString
        } else {
            detail.cwd = session.cwd
            detail.model = session.model
            detail.createdAtMs = session.createdAtMs
            detail.updatedAtMs = session.updatedAtMs
            detail.path = session.path
        }

        if case .object(let stats)? = value["stats"] {
            var s = DetailStats()
            if case .object(let m)? = stats["messages"] {
                s.messages = DetailMessageCounts(user: m["user"]?.intValue,
                                                 assistant: m["assistant"]?.intValue,
                                                 tool: m["tool"]?.intValue,
                                                 reasoning: m["reasoning"]?.intValue,
                                                 system: m["system"]?.intValue,
                                                 compaction: m["compaction"]?.intValue)
            }
            s.toolCalls = stats["tool_calls"]?.intValue
            s.toolResults = stats["tool_results"]?.intValue
            s.toolErrors = stats["tool_errors"]?.intValue
            if case .array(let arr)? = stats["tool_usage"] {
                s.toolUsage = arr.compactMap { item in
                    guard case .object(let obj) = item, let name = obj["name"]?.displayString else { return nil }
                    return ToolUsageStat(name: name, count: obj["count"]?.intValue ?? 0)
                }
            }
            s.usage = Self.parseUsage(stats["usage"])
            s.durationMs = stats["duration_ms"]?.intValue.map(Double.init)
            s.firstTs = stats["first_ts"]?.intValue.map(Double.init)
            s.lastTs = stats["last_ts"]?.intValue.map(Double.init)
            s.eventsTotal = stats["events_total"]?.intValue
            s.eventsShown = stats["events_shown"]?.intValue
            s.truncated = stats["truncated"]?.boolValue ?? false
            detail.stats = s
            if s.truncated { detail.truncated = true }
        }

        if case .array(let arr)? = value["sections"] {
            detail.sections = arr.compactMap { item in
                guard case .object(let obj) = item else { return nil }
                let index = obj["index"]?.intValue ?? 0
                return DetailSection(index: index,
                                     kind: obj["kind"]?.displayString ?? "turn",
                                     title: obj["title"]?.displayString ?? "第 \(index) 轮",
                                     startIndex: obj["start_index"]?.intValue,
                                     endIndex: obj["end_index"]?.intValue,
                                     ts: obj["ts"]?.intValue.map(Double.init),
                                     toolCalls: obj["tool_calls"]?.intValue,
                                     tokens: obj["tokens"]?.intValue)
            }
        }

        if case .array(let arr)? = value["timeline"] {
            detail.timeline = arr.compactMap { item in
                guard case .object(let obj) = item else { return nil }
                let index = obj["index"]?.intValue ?? 0
                var tool: DetailToolInfo?
                if case .object(let t)? = obj["tool"] {
                    tool = DetailToolInfo(name: t["name"]?.displayString,
                                          callID: t["call_id"]?.displayString,
                                          isError: t["is_error"]?.boolValue ?? false)
                }
                return DetailEvent(index: index,
                                   ts: obj["ts"]?.intValue.map(Double.init),
                                   kind: obj["kind"]?.displayString ?? "",
                                   role: obj["role"]?.displayString,
                                   text: obj["text"]?.displayString ?? "",
                                   tool: tool,
                                   usage: Self.parseUsage(obj["usage"]),
                                   section: obj["section"]?.intValue)
            }
        }

        if case .array(let arr)? = value["warnings"] {
            detail.warnings = Self.sanitizeWarnings(arr.compactMap { $0.displayString })
        }
        if value["truncated"]?.boolValue == true { detail.truncated = true }
        if detail.stats.usage.available == false && detail.timeline.isEmpty {
            detail.warnings.append("该来源没有提供完整时间线。")
        }
        return detail
    }

    /// Translate backend developer warnings into short user-facing sentences.
    /// Token-availability notices are already explained by the Token card, so
    /// they are dropped here; raw `(usage.available=false)`-style suffixes are
    /// stripped from everything else.
    static func sanitizeWarnings(_ raw: [String]) -> [String] {
        var result: [String] = []
        for warning in raw {
            let lowered = warning.lowercased()
            if lowered.contains("usage.available") || (lowered.contains("token") && (warning.contains("未提供") || warning.contains("未记录"))) {
                continue   // Token card already says "该工具未提供 Token 统计"
            }
            if lowered.contains("truncat") || warning.contains("截断") || lowered.contains("max-events") {
                result.append("时间线较长，已截断显示")
                continue
            }
            if lowered.contains("injected environment") || lowered.contains("instruction user item") {
                result.append("已跳过系统注入的环境说明消息")
                continue
            }
            var cleaned = warning
            cleaned = cleaned.replacingOccurrences(of: #"\(usage\.available=[^)]*\)"#, with: "", options: .regularExpression)
            cleaned = cleaned.replacingOccurrences(of: #"\((?=[^)]*--[a-z-]+)[^)]*\)"#, with: "", options: .regularExpression)
            cleaned = cleaned.replacingOccurrences(of: "--keep-system", with: "「包含系统提示词」选项")
            cleaned = cleaned.replacingOccurrences(of: "--max-events", with: "事件数量上限")
            cleaned = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
            if cleaned.isEmpty { continue }
            if !result.contains(cleaned) { result.append(cleaned) }
        }
        return result
    }

    static func parseUsage(_ value: JSONValue?) -> TokenUsage {
        guard case .object(let obj)? = value else { return .unavailable }
        let usage = TokenUsage(inputTokens: obj["input_tokens"]?.intValue,
                               outputTokens: obj["output_tokens"]?.intValue,
                               cacheReadTokens: obj["cache_read_tokens"]?.intValue,
                               cacheWriteTokens: obj["cache_write_tokens"]?.intValue,
                               totalTokens: obj["total_tokens"]?.intValue,
                               available: obj["available"]?.boolValue ?? false)
        if !usage.available && usage.hasAnyValue {
            var fixed = usage
            fixed.available = true
            return fixed
        }
        return usage
    }

    private func fallbackDetail(source: String, session: SessionRow) -> SessionDetail {
        var detail = SessionDetail(source: source, sessionID: session.id,
                                   title: session.displayTitle)
        detail.cwd = session.cwd
        detail.model = session.model
        detail.createdAtMs = session.createdAtMs
        detail.updatedAtMs = session.updatedAtMs
        detail.path = session.path
        detail.isFallback = true
        detail.warnings = ["当前版本无法读取完整时间线，以下仅显示最近消息摘要。更新组件后即可查看完整时间线与 Token 统计。"]
        if let preview = try? preview(source: source, session: session) {
            detail.title = preview.title.isEmpty ? detail.title : preview.title
            detail.cwd = preview.cwd ?? detail.cwd
            detail.model = preview.model ?? detail.model
            var stats = DetailStats()
            if let count = preview.messageCount {
                stats.messages = DetailMessageCounts(user: count, assistant: nil, tool: nil,
                                                     reasoning: nil, system: nil, compaction: nil)
            }
            stats.toolCalls = preview.toolCallCount
            detail.stats = stats
            var index = 0
            if let first = preview.firstUserMessage, !first.isEmpty {
                detail.timeline.append(DetailEvent(index: index, ts: detail.createdAtMs,
                                                   kind: "user", role: "user", text: first,
                                                   tool: nil, usage: nil, section: nil))
                index += 1
            }
            for message in preview.recentMessages {
                let lowered = message.lowercased()
                let kind = lowered.hasPrefix("assistant") || lowered.hasPrefix("助手") ? "assistant"
                    : (lowered.hasPrefix("tool") ? "tool_result" : "user")
                let role = kind == "assistant" ? "assistant" : (kind == "tool_result" ? "tool" : "user")
                detail.timeline.append(DetailEvent(index: index, ts: nil, kind: kind, role: role,
                                                   text: message, tool: nil, usage: nil, section: nil))
                index += 1
            }
        }
        return detail
    }

    // MARK: - preview
    func preview(source: String, session: SessionRow) throws -> SessionPreview {
        if hasPreview {
            if let preview = try? previewViaCommand(source: source, session: session) {
                return preview
            }
        }
        return SessionPreview(title: session.displayTitle,
                              cwd: session.cwd,
                              model: session.model,
                              messageCount: nil,
                              toolCallCount: nil,
                              firstUserMessage: nil,
                              recentMessages: [],
                              warnings: ["当前版本使用会话列表信息生成预览；更新组件后可显示更详细摘要。"],
                              sourceNote: "列表信息")
    }

    private func previewViaCommand(source: String, session: SessionRow) throws -> SessionPreview {
        let r = try bridge.run(["preview", "--from", source, "--session", session.id,
                                "--json", "--limit", "6"], timeout: 120)
        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw ProductError.backend("预览结果格式无法识别")
        }
        var messageCount = value["message_count"]?.intValue
        var toolCount = value["tool_call_count"]?.intValue
        if case .object(let counts)? = value["counts"] {
            let users = counts["user_messages"]?.intValue ?? 0
            let assistants = counts["assistant_messages"]?.intValue ?? 0
            if users + assistants > 0 || counts["user_messages"] != nil {
                messageCount = messageCount ?? (users + assistants)
            } else {
                messageCount = messageCount ?? counts["messages"]?.intValue
            }
            toolCount = toolCount ?? counts["tool_calls"]?.intValue
        }
        var recent: [String] = []
        if case .array(let arr)? = value["last_messages"] {
            recent = arr.compactMap { item -> String? in
                if case .object(let obj) = item {
                    let role = obj["role"]?.displayString ?? ""
                    let text = obj["text"]?.displayString ?? obj["content"]?.displayString ?? ""
                    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty else { return nil }
                    return role.isEmpty ? trimmed : "\(role)：\(trimmed)"
                }
                return item.displayString
            }
        }
        var warnings: [String] = []
        if case .array(let arr)? = value["warnings"] {
            warnings = arr.compactMap { $0.displayString }
        }
        return SessionPreview(title: value["title"]?.displayString ?? session.displayTitle,
                              cwd: value["cwd"]?.displayString ?? session.cwd,
                              model: value["model"]?.displayString ?? session.model,
                              messageCount: messageCount,
                              toolCallCount: toolCount,
                              firstUserMessage: value["first_user_message"]?.displayString,
                              recentMessages: recent,
                              warnings: warnings,
                              sourceNote: "详细预览")
    }

    // MARK: - migrate (single session)
    func migrateOne(source: String,
                    session: SessionRow,
                    target: String,
                    outputDir: URL,
                    options: MigrationOptions) throws -> MigrationItemResult {
        let targetName = MigrationTarget.find(target).title
        if options.mode == .install {
            guard hasMigrate else {
                throw ProductError.userFacing("当前版本暂不支持直接写入 \(targetName)。请先导出，或更新应用后再试。")
            }
            return try migrateInstall(source: source, session: session, target: target, options: options)
        }
        if hasMigrate {
            return try migrateViaCommand(source: source, session: session, target: target,
                                         outputDir: outputDir, options: options, install: false)
        }
        return try migrateViaConvert(source: source, session: session, target: target,
                                     outputDir: outputDir, options: options)
    }

    private func migrateViaConvert(source: String,
                                   session: SessionRow,
                                   target: String,
                                   outputDir: URL,
                                   options: MigrationOptions) throws -> MigrationItemResult {
        try Paths.ensureDirectory(outputDir)
        do {
            let env = try bridge.convertParsed(from: source, to: target, session: session.id,
                                                outDir: outputDir,
                                                targetCwd: options.targetCwd,
                                                keepSystem: options.keepSystem,
                                                extraEnvironment: options.environment)
            guard let result = env.results?.first else {
                return MigrationItemResult(sessionID: session.id, title: session.displayTitle,
                                           ok: false, outputDir: nil, artifact: nil,
                                           verifyStatus: nil, lossy: [], warnings: [],
                                           error: env.error ?? "迁移未返回结果")
            }
            let ok = (env.ok ?? false) && result.isOK
            var verifyStatus: String?
            if ok {
                if target == "dsh" {
                    let verifyPath = result.outputDir ?? outputDir.path
                    if let report = try? bridge.verify(path: verifyPath) {
                        verifyStatus = (report.ok ?? false) && (report.failed ?? 0) == 0
                            ? "已校验通过" : "校验未通过"
                    } else {
                        verifyStatus = "校验未完成"
                    }
                } else if target == "atif" {
                    verifyStatus = "已导出通用文件"
                } else {
                    verifyStatus = "已导出（目标格式）"
                }
            }
            return MigrationItemResult(sessionID: session.id,
                                       title: session.displayTitle,
                                       ok: ok,
                                       outputDir: result.outputDir ?? outputDir.path,
                                       artifact: result.artifact,
                                       verifyStatus: verifyStatus,
                                       lossy: result.lossy ?? [],
                                       warnings: result.warnings ?? [],
                                       error: ok ? nil : (result.error ?? env.error ?? "转换失败"))
        } catch {
            return MigrationItemResult(sessionID: session.id, title: session.displayTitle,
                                       ok: false, outputDir: nil, artifact: nil,
                                       verifyStatus: nil, lossy: [], warnings: [],
                                       error: Self.userMessage(for: error))
        }
    }

    private func migrateViaCommand(source: String,
                                   session: SessionRow,
                                   target: String,
                                   outputDir: URL,
                                   options: MigrationOptions,
                                   install: Bool) throws -> MigrationItemResult {
        try Paths.ensureDirectory(outputDir)
        var args = ["migrate", "--from", source, "--session", session.id,
                    "--to", target, "--out", outputDir.path, "--json"]
        args += ["--mode", install ? "install" : "export"]
        if let cwd = options.targetCwd { args += ["--target-cwd", cwd] }
        if options.keepSystem { args += ["--keep-system"] }
        if options.registerToProject { args += ["--register"] }
        if install { args += ["--yes"] }
        let r = try bridge.run(args, timeout: 300)
        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw ProductError.backend("迁移结果格式无法识别：\(BackendBridge.tail(r.stderr.isEmpty ? r.stdout : r.stderr))")
        }
        // tolerant parsing of {ok, results:[...]} or {ok, plan, results} or single result object
        var entries: [JSONValue] = []
        if case .array(let arr)? = value["results"] { entries = arr }
        if case .array(let arr)? = value["items"] { entries = arr }
        if entries.isEmpty { entries = [value] }
        let item = entries.first ?? value
        var verifyStatus: String?
        if case .object(let v)? = item["verify"] {
            verifyStatus = (v["ok"]?.boolValue ?? false) ? "已校验通过" : "校验未通过"
        }
        if verifyStatus == nil {
            if case .string(let s)? = item["verify"] { verifyStatus = s }
        }
        var lossy: [String] = []
        if case .array(let arr)? = item["lossy"] { lossy = arr.compactMap { $0.displayString } }
        var warnings: [String] = []
        if case .array(let arr)? = item["warnings"] { warnings = arr.compactMap { $0.displayString } }
        let statusText = item["status"]?.displayString ?? ""
        let ok = (value["ok"]?.boolValue ?? true) && ["ok", "success", "done"].contains(statusText.lowercased())
        let returnedTitle = item["title"]?.displayString ?? ""
        return MigrationItemResult(sessionID: session.id,
                                   title: returnedTitle.isEmpty ? session.displayTitle : returnedTitle,
                                   ok: ok,
                                   outputDir: item["output_dir"]?.displayString ?? outputDir.path,
                                   artifact: item["artifact"]?.displayString,
                                   verifyStatus: verifyStatus,
                                   lossy: lossy,
                                   warnings: warnings,
                                   error: ok ? nil : (item["error"]?.displayString ?? "迁移失败"))
    }

    // MARK: - install migration (v1.4)
    private func migrateInstall(source: String,
                                session: SessionRow,
                                target: String,
                                options: MigrationOptions) throws -> MigrationItemResult {
        var args = ["migrate", "--from", source, "--session", session.id,
                    "--to", target, "--mode", "install", "--yes", "--json"]
        if let root = options.sourceRoot { args += ["--root", root] }
        if target == "dsh", let home = options.targetHome { args += ["--dsh-home", home] }
        if let cwd = options.targetCwd { args += ["--target-cwd", cwd] }
        if options.registerToProject { args += ["--register"] }
        if options.overwrite { args += ["--overwrite"] }
        if options.keepSystem { args += ["--keep-system"] }
        // Backend hotfix (task-46) now performs a verifiable source move and
        // writes the recovery journal itself. Prefer it; the app-side rename is
        // only a compatibility fallback for an older backend without the flag.
        if supportsSessionMode { args += ["--session-mode", options.sessionMode.rawValue] }
        let targetName = MigrationTarget.find(target).title

        let r: CommandResult
        do {
            r = try bridge.run(args, timeout: 300, extraEnvironment: options.environment)
        } catch {
            throw ProductError.userFacing("迁移到 \(targetName) 失败：\(Self.userMessage(for: error))。请稍后重试。")
        }
        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw ProductError.backend("迁移结果格式无法识别：\(BackendBridge.tail(r.stderr.isEmpty ? r.stdout : r.stderr))")
        }
        var entries: [JSONValue] = []
        if case .array(let arr)? = value["results"] { entries = arr }
        if case .array(let arr)? = value["items"] { entries = arr }
        let item = entries.first ?? value
        let status = (item["status"]?.displayString ?? "").lowercased()
        let installStatus = item["install_status"]?.displayString
        let sourceMoveStatus = item["source_move_status"]?.displayString
        let skipped = status.contains("skip") || (installStatus ?? "").lowercased().contains("skip")
            || status == "exists"
        let failed = status.contains("fail") || value["ok"]?.boolValue == false
        let ok = !failed && !skipped
        var verify: Bool?
        if case .object(let v)? = item["verify"] { verify = v["ok"]?.boolValue }
        if verify == nil { verify = item["verified"]?.boolValue }
        let installedPath = item["installed_path"]?.displayString
            ?? item["artifact"]?.displayString
            ?? item["output_dir"]?.displayString
        var sourceBackup = item["source_backup_path"]?.displayString
        var sourceMoved = item["source_moved"]?.boolValue ?? (sourceBackup != nil)
        let sourcePath = item["source_path"]?.displayString ?? session.path
        let journalPath = value["journal_path"]?.displayString ?? item["journal_path"]?.displayString
        var warnings: [String] = []
        if case .array(let arr)? = item["warnings"] { warnings = arr.compactMap { $0.displayString } }
        var lossy: [String] = []
        if case .array(let arr)? = item["lossy"] { lossy = arr.compactMap { $0.displayString } }

        // Compatibility fallback ONLY for an older backend without --session-mode.
        // With the fixed backend, source_moved=true must never be renamed again.
        if ok, options.sessionMode == .move, !supportsSessionMode, !sourceMoved {
            if let sourcePath = session.path, FileManager.default.fileExists(atPath: sourcePath) {
                do {
                    let backup = try SourceTransaction.moveSourceFile(sourcePath)
                    sourceBackup = backup
                    sourceMoved = true
                } catch {
                    warnings.append("安装成功，但移出原始会话失败：\(Self.userMessage(for: error))")
                }
            } else {
                warnings.append("安装成功，但未找到原始会话文件，未能移出（原始会话未变）。")
            }
        }
        var moveRequestedButNotMoved = false
        var moveErrorMessage: String?
        if options.sessionMode == .move, !sourceMoved {
            moveRequestedButNotMoved = true
            let detail = item["source_move_error"]?.displayString ?? sourceMoveStatus
            if (sourceMoveStatus ?? "").lowercased().contains("unsupported") {
                moveErrorMessage = "该来源暂不支持移出，源文件已保留（会话已安装到目标库）。"
            } else {
                moveErrorMessage = "移出原始会话失败，源文件已保留：\(detail ?? "未知原因")"
            }
            warnings.append(moveErrorMessage ?? "移出原始会话未完成，源文件已保留。")
        }
        // Move requested but unsupported/failed → do not report a plain success.
        let finalOK = ok && !moveRequestedButNotMoved
        let errorMessage: String? = failed ? (item["error"]?.displayString ?? "迁移失败") : moveErrorMessage
        return MigrationItemResult(sessionID: session.id,
                                   title: item["title"]?.displayString ?? session.displayTitle,
                                   ok: finalOK,
                                   outputDir: nil,
                                   artifact: installedPath,
                                   verifyStatus: verify == true ? "已校验通过" : (skipped ? "已存在，已跳过" : (ok ? "已写入（未校验）" : nil)),
                                   lossy: lossy,
                                   warnings: warnings,
                                   error: errorMessage,
                                   installedPath: installedPath,
                                   verified: verify,
                                   skipped: skipped,
                                   skipReason: skipped ? "目标会话库中已存在同 ID 会话（默认跳过，不覆盖）" : nil,
                                   installStatus: installStatus ?? status,
                                   sourceBackupPath: sourceBackup,
                                   sourceMoved: sourceMoved,
                                   targetStorePath: item["target"]?.displayString ?? item["target_home"]?.displayString,
                                   sourceMoveStatus: sourceMoveStatus,
                                   sourcePath: sourcePath,
                                   journalPath: journalPath)
    }

    static func decodeRows(_ r: CommandResult) throws -> [SessionRow] {
        guard r.ok else {
            throw BackendError.nonZero(r.command, r.exitCode, BackendBridge.tail(r.stderr.isEmpty ? r.stdout : r.stderr))
        }
        guard let data = r.stdout.data(using: .utf8) else {
            throw BackendError.decoding("list", "stdout 非 UTF-8")
        }
        let decoder = JSONDecoder()
        if let env = try? decoder.decode(ListEnvelope.self, from: data), let rows = env.sessions {
            return rows
        }
        return (try? decoder.decode([SessionRow].self, from: data)) ?? []
    }

    struct RestoreReport: Sendable {
        var restored: Int
        var missing: Int
        var failed: Int
        var message: String
    }

    /// Restores source sessions moved by a previous migration (backend command
    /// when available, app-side journal rename otherwise).
    func restore(journalPath: String, removeInstalled: Bool = false) throws -> RestoreReport {
        // App-side journals (created for the safe rename fallback) and backend
        // journals have different shapes; detect first, then use the matching
        // restore path without ever deleting installed target files.
        let isAppJournal: Bool = {
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: journalPath)),
                  let value = try? JSONDecoder().decode(JSONValue.self, from: data) else { return true }
            if value["journal_version"] != nil { return false }
            if case .array(let arr)? = value["entries"] {
                return !(arr.first.map { $0["source_session_id"] != nil || $0["backup_path"] != nil } ?? false)
            }
            return true
        }()
        if supportsMigrateRestore, !isAppJournal {
            var restoreArgs = ["migrate-restore", "--journal", journalPath, "--json"]
            if removeInstalled { restoreArgs.append("--remove-installed") }
            let r = try bridge.run(restoreArgs, timeout: 120)
            if r.ok, let data = r.stdout.data(using: .utf8),
               let value = try? JSONDecoder().decode(JSONValue.self, from: data) {
                var restored = value["restored"]?.intValue ?? value["restored_count"]?.intValue ?? 0
                var missing = value["missing"]?.intValue ?? 0
                var failed = value["failed"]?.intValue ?? 0
                if case .array(let arr)? = value["results"] {
                    restored = arr.filter {
                        (($0["status"]?.displayString ?? "").lowercased().contains("restor")
                         || $0["restored"]?.boolValue == true
                         || $0["ok"]?.boolValue == true)
                    }.count
                    missing = arr.filter { ($0["status"]?.displayString ?? "").lowercased().contains("missing") }.count
                    failed = arr.filter { ($0["status"]?.displayString ?? "").lowercased().contains("fail") }.count
                }
                let message = value["message"]?.displayString ?? "已恢复 \(restored) 个原始会话"
                return RestoreReport(restored: restored, missing: missing, failed: failed, message: message)
            }
        }
        guard let outcome = SourceTransaction.restore(journalPath: journalPath) else {
            throw ProductError.userFacing("找不到迁移日志或日志格式无效：\(journalPath)")
        }
        var message = "已恢复 \(outcome.restored) 个原始会话"
        if !outcome.missing.isEmpty { message += "，\(outcome.missing.count) 个备份文件已不存在" }
        if !outcome.failed.isEmpty { message += "，\(outcome.failed.count) 个恢复失败" }
        return RestoreReport(restored: outcome.restored,
                             missing: outcome.missing.count,
                             failed: outcome.failed.count,
                             message: message)
    }

    // MARK: - one-click migrate-all (v1.4; backend migrate-all when available)
    func buildMigrateAllPlan(target: String,
                             targetName: String,
                             targetStorePath: String?,
                             howToSee: String?,
                             sources: [MigrateAllSource],
                             limit: Int?,
                             sinceDays: Int?) throws -> MigrateAllPlan {
        var plan = MigrateAllPlan(targetID: target, targetName: targetName,
                                  targetStorePath: targetStorePath, howToSee: howToSee,
                                  mode: .install, sessionMode: .keep,
                                  sources: sources, totalSessions: 0,
                                  limit: limit, sinceDays: sinceDays)
        var remaining = limit ?? Int.max
        let cutoff: Double? = sinceDays.map { Date().timeIntervalSince1970 * 1000 - Double($0) * 86_400_000 }
        var sessionsBySource: [String: [SessionRow]] = [:]
        for source in sources where source.selected && source.sessionCount > 0 && source.id != target {
            guard remaining > 0 else { break }
            let rows = (try? listSessions(source: source.id, root: nil)) ?? []
            var filtered = rows
            if let cutoff {
                filtered = rows.filter { ($0.createdAtMs ?? 0) >= cutoff }
            }
            if filtered.count > remaining { filtered = Array(filtered.prefix(remaining)) }
            sessionsBySource[source.id] = filtered
            plan.totalSessions += filtered.count
            remaining -= filtered.count
        }
        plan.sessionsBySource = sessionsBySource
        return plan
    }

    func runMigrateAll(plan: MigrateAllPlan,
                       sessionMode: SessionMode,
                       dryRun: Bool = false,
                       progress: @escaping @Sendable (Int, Int, String) -> Void,
                       shouldCancel: @escaping @Sendable () -> Bool) -> MigrateAllReport {
        let started = Date()
        if dryRun {
            // Plan preview only: zero writes, zero CLI invocations.
            return MigrateAllReport(plan: plan, items: [], journalPath: nil,
                                    elapsed: Date().timeIntervalSince(started), cancelled: false)
        }
        var items: [MigrationItemResult] = []
        var cancelled = false
        let total = plan.totalSessions
        var done = 0
        for source in plan.sources where source.selected {
            let sessions = plan.sessionsBySource[source.id] ?? []
            for session in sessions {
                if shouldCancel() { cancelled = true; break }
                let options = MigrationOptions(outputDir: "",
                                               mode: plan.mode,
                                               sessionMode: sessionMode,
                                               sourceRoot: plan.sourceRoots[source.id],
                                               targetHome: plan.targetHome,
                                               environment: plan.environment)
                let result = (try? migrateOne(source: source.id, session: session,
                                              target: plan.targetID,
                                              outputDir: FileManager.default.temporaryDirectory,
                                              options: options))
                    ?? MigrationItemResult(sessionID: session.id, title: session.displayTitle,
                                           ok: false, outputDir: nil, artifact: nil,
                                           verifyStatus: nil, lossy: [], warnings: [],
                                           error: "迁移失败")
                items.append(result)
                done += 1
                progress(done, total, "\(source.name)：\(session.displayTitle)")
            }
            if cancelled { break }
        }
        return MigrateAllReport(plan: plan, items: items, journalPath: nil,
                                elapsed: Date().timeIntervalSince(started), cancelled: cancelled)
    }

    // MARK: - backend migrate-all (preferred when the CLI exposes it)
    private func parseBackendMigrateAll(_ value: JSONValue, plan: MigrateAllPlan) -> [MigrationItemResult] {
        var raw: [JSONValue] = []
        if case .array(let arr)? = value["results"] { raw = arr }
        else if case .array(let arr)? = value["plan"] { raw = arr }
        return raw.map { item in
            let sid = item["source_session_id"]?.displayString ?? item["session_id"]?.displayString ?? ""
            let status = (item["status"]?.displayString ?? "").lowercased()
            let skipped = status.contains("skip") || status == "exists"
            let failed = status.contains("fail") || item["error"]?.displayString != nil
            var verified: Bool?
            if case .object(let v)? = item["verify"] { verified = v["ok"]?.boolValue }
            let sourceBackup = item["source_backup_path"]?.displayString
            let sourceMoved = item["source_moved"]?.boolValue ?? (sourceBackup != nil)
            let sourceMoveStatus = item["source_move_status"]?.displayString
            let sourcePath = item["source_path"]?.displayString
            let journal = item["journal_path"]?.displayString ?? value["journal_path"]?.displayString
            return MigrationItemResult(sessionID: sid,
                                       title: item["title"]?.displayString ?? sid,
                                       ok: !failed,
                                       outputDir: nil,
                                       artifact: item["installed_path"]?.displayString,
                                       verifyStatus: verified == true ? "已校验通过" : (skipped ? "已存在，已跳过" : nil),
                                       lossy: [],
                                       warnings: [],
                                       error: failed ? item["error"]?.displayString : nil,
                                       installedPath: item["installed_path"]?.displayString,
                                       verified: verified,
                                       skipped: skipped,
                                       skipReason: skipped ? "目标会话库中已存在同 ID 会话" : nil,
                                       installStatus: item["install_status"]?.displayString ?? status,
                                       sourceBackupPath: sourceBackup,
                                       sourceMoved: sourceMoved,
                                       targetStorePath: item["target"]?.displayString,
                                       sourceMoveStatus: sourceMoveStatus,
                                       sourcePath: sourcePath,
                                       journalPath: journal)
        }
    }

    func buildPlanViaBackend(target: String, sources: [MigrateAllSource],
                             limit: Int?, sinceDays: Int?,
                             targetName: String, targetStorePath: String?,
                             howToSee: String?) throws -> MigrateAllPlan {
        var args = ["migrate-all", "--to", target, "--dry-run", "--json"]
        let ids = sources.filter(\.selected).map(\.id)
        if !ids.isEmpty { args += ["--from", ids.joined(separator: ",")] }
        if let limit { args += ["--limit", "\(limit)"] }
        if let sinceDays { args += ["--since-days", "\(sinceDays)"] }
        let r = try bridge.run(args, timeout: 180)
        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw ProductError.backend("迁移计划格式无法识别")
        }
        var plan = MigrateAllPlan(targetID: target, targetName: targetName,
                                  targetStorePath: targetStorePath, howToSee: howToSee,
                                  mode: .install, sessionMode: .keep, sources: sources,
                                  totalSessions: 0, limit: limit, sinceDays: sinceDays)
        if case .object(let summary)? = value["summary"] {
            plan.totalSessions = summary["total"]?.intValue ?? summary["planned"]?.intValue ?? 0
            plan.skippedEstimate = summary["will_skip"]?.intValue
                ?? summary["skip_count"]?.intValue
                ?? summary["skipped"]?.intValue
        }
        if plan.totalSessions == 0, case .array(let arr)? = value["plan"] {
            plan.totalSessions = arr.count
        }
        if let store = value["target_store"]?.displayString, plan.targetStorePath == nil {
            plan.targetStorePath = store
        }
        return plan
    }

    func runMigrateAllViaBackend(plan: MigrateAllPlan, sessionMode: SessionMode,
                                 overwrite: Bool = false,
                                 cancellation: CancellationFlag? = nil) throws -> MigrateAllReport {
        let started = Date()
        let journalDir = MigrationJournalStore.directoryURL
        let before = (try? FileManager.default.contentsOfDirectory(at: journalDir,
                                                                   includingPropertiesForKeys: nil,
                                                                   options: [.skipsHiddenFiles])) ?? []
        let beforeNames = Set(before.map(\.lastPathComponent))
        var args = ["migrate-all", "--to", plan.targetID, "--yes", "--json",
                    "--session-mode", sessionMode.rawValue]
        let ids = plan.sources.filter(\.selected).map(\.id)
        if !ids.isEmpty { args += ["--from", ids.joined(separator: ",")] }
        if let limit = plan.limit { args += ["--limit", "\(limit)"] }
        if let since = plan.sinceDays { args += ["--since-days", "\(since)"] }
        if overwrite { args += ["--overwrite"] }
        let r = try bridge.run(args, timeout: 900, cancellation: cancellation)

        func newestJournal() -> String? {
            let files = (try? FileManager.default.contentsOfDirectory(at: journalDir,
                                                                      includingPropertiesForKeys: [.contentModificationDateKey],
                                                                      options: [.skipsHiddenFiles])) ?? []
            let newFiles = files.filter { !beforeNames.contains($0.lastPathComponent) }
                .sorted { a, b in
                    let da = (try? a.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast
                    let db = (try? b.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast
                    return da > db
                }
            return newFiles.first?.path
        }

        if r.wasCancelled {
            // The CLI was terminated for real. Keep whatever the backend journal
            // recorded for already-completed items; do not fabricate results.
            let journal = newestJournal()
            var items: [MigrationItemResult] = []
            if let journal, let loaded = MigrationJournalStore.load(URL(fileURLWithPath: journal)) {
                items = loaded.entries.map { entry in
                    MigrationItemResult(sessionID: entry.sessionID, title: entry.sessionID, ok: true,
                                        outputDir: nil, artifact: entry.installedPath,
                                        verifyStatus: nil, lossy: [], warnings: [], error: nil,
                                        installedPath: entry.installedPath, verified: nil,
                                        skipped: false, skipReason: nil, installStatus: "completed",
                                        sourceBackupPath: entry.backupPath.isEmpty ? nil : entry.backupPath,
                                        sourceMoved: !entry.backupPath.isEmpty,
                                        targetStorePath: nil,
                                        sourceMoveStatus: nil,
                                        sourcePath: entry.sourcePath.isEmpty ? nil : entry.sourcePath,
                                        journalPath: journal)
                }
            }
            return MigrateAllReport(plan: plan, items: items, journalPath: journal,
                                    elapsed: Date().timeIntervalSince(started), cancelled: true)
        }

        guard let data = r.stdout.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw ProductError.backend("迁移结果格式无法识别：\(BackendBridge.tail(r.stderr.isEmpty ? r.stdout : r.stderr))")
        }
        let items = parseBackendMigrateAll(value, plan: plan)
        let journal = value["journal_path"]?.displayString ?? newestJournal()
        return MigrateAllReport(plan: plan, items: items, journalPath: journal,
                                elapsed: Date().timeIntervalSince(started), cancelled: false)
    }

    // MARK: - misc
    func verify(path: String) -> VerifyEnvelope? {
        try? bridge.verify(path: path)
    }

    func matrix(kind: String, limit: Int?, outDir: URL) throws -> MatrixRunResult {
        try bridge.matrix(kind: kind, limit: limit, outDir: outDir)
    }

    func coverage() throws -> JSONValue {
        try bridge.coverage()
    }

    static func userMessage(for error: Error) -> String {
        if let productError = error as? ProductError {
            return productError.localizedDescription
        }
        if let backendError = error as? BackendError {
            return backendError.localizedDescription
        }
        return error.localizedDescription
    }
}
