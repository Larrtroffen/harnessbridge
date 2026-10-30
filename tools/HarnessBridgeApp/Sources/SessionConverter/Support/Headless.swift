import Foundation
import AppKit

/// Headless modes used for automated acceptance:
///   HarnessBridge --self-test   → locate backend, 5 native list checks,
///                                    convert→ATIF, convert→DSH + verify,
///                                    coverage-report; PASS/FAIL lines; exit 0/1
///   HarnessBridge --diagnose    → print environment & capability summary
enum Headless {
    static let nativeSources = ["claude", "codex", "omp", "qoder", "dsh"]

    // MARK: - session self-test
    static func selfTest() -> Int32 {
        var pass = 0
        var fail = 0

        func ok(_ label: String, _ detail: String = "") {
            pass += 1
            print("[PASS] \(label)\(detail.isEmpty ? "" : " — \(detail)")")
        }
        func bad(_ label: String, _ detail: String) {
            fail += 1
            print("[FAIL] \(label)\(detail.isEmpty ? "" : " — \(detail)")")
        }

        print("HarnessBridge self-test v\(AppInfo.version)")
        print("time: \(ISO8601DateFormatter().string(from: Date()))")
        print("output root: \(Paths.outputRoot().path)")

        guard let workspace = Paths.discoverWorkspace() else {
            bad("locate workspace", "未找到含 tools/agent-session-import/asi 的目录")
            return finish(pass: pass, fail: fail)
        }
        ok("locate workspace", workspace.path)

        let bridge = BackendBridge(workspace: workspace)
        guard FileManager.default.isExecutableFile(atPath: bridge.asiPath.path) else {
            bad("asi executable", bridge.asiPath.path)
            return finish(pass: pass, fail: fail)
        }
        ok("asi executable", bridge.asiPath.path)

        do {
            let version = try bridge.version()
            if version.contains("asi") { ok("asi --version", version) }
            else { bad("asi --version", version) }
        } catch {
            bad("asi --version", error.localizedDescription)
            return finish(pass: pass, fail: fail)
        }

        var caps: Capabilities?
        do {
            let c = try bridge.capabilities()
            caps = c
            let missing = nativeSources.filter { !c.sources.contains($0) }
            if missing.isEmpty {
                ok("capabilities", "sources=\(c.sources.count) targets=\(c.targetChoices.count) matrix=\(c.matrixKinds.count)")
            } else {
                bad("capabilities", "缺少原生 source: \(missing.joined(separator: ","))")
            }
        } catch {
            bad("capabilities", error.localizedDescription)
        }

        // 5 native sources: each must list at least 1 real session
        var candidate: SessionRow?
        var candidateSource: String?
        for source in nativeSources {
            do {
                let rows = try bridge.list(source: source, timeout: 120)
                if rows.isEmpty {
                    bad("asi list \(source)", "0 sessions")
                } else {
                    ok("asi list \(source)", "\(rows.count) sessions")
                    if candidate == nil, source == "codex" || candidateSource == nil {
                        candidate = rows.first
                        candidateSource = source
                    }
                }
            } catch {
                bad("asi list \(source)", error.localizedDescription)
            }
        }

        guard let session = candidate, let source = candidateSource else {
            bad("pick session", "没有可用于转换的会话")
            return finish(pass: pass, fail: fail)
        }
        ok("pick session", "\(source)/\(session.id)")

        // Unique per run (second-level timestamps collide on quick consecutive runs),
        // and clean up older self-test artifacts to avoid accumulation.
        let unique = Paths.stamp() + "-" + UUID().uuidString.prefix(8)
        let outputRoot = Paths.outputRoot()
        if let existing = try? FileManager.default.contentsOfDirectory(at: outputRoot,
                                                                      includingPropertiesForKeys: nil,
                                                                      options: [.skipsHiddenFiles]) {
            for dir in existing where dir.lastPathComponent.hasPrefix("selftest-") {
                try? FileManager.default.removeItem(at: dir)
            }
        }
        let baseOut = outputRoot.appendingPathComponent("selftest-\(unique)", isDirectory: true)
        try? Paths.ensureDirectory(baseOut)

        // convert → ATIF
        do {
            let atifOut = baseOut.appendingPathComponent("atif", isDirectory: true)
            let env = try bridge.convertParsed(from: source, to: "atif", session: session.id, outDir: atifOut)
            let result = env.results?.first
            let artifactExists = Paths.pathExists(result?.artifact)
            let steps = result?.steps ?? Self.atifStepCount(result?.artifact)
            let events = result?.events ?? steps
            if (env.ok ?? false), result?.isOK ?? false, artifactExists {
                ok("convert → atif", "events=\(Fmt.int(events)) steps=\(Fmt.int(steps)) artifact=\(Fmt.shortPath(result?.artifact, limit: 90))")
            } else {
                bad("convert → atif", result?.error ?? env.error ?? "artifact missing")
            }
        } catch {
            bad("convert → atif", error.localizedDescription)
        }

        // convert → DSH + verify
        do {
            let dshOut = baseOut.appendingPathComponent("dsh", isDirectory: true)
            let env = try bridge.convertParsed(from: source, to: "dsh", session: session.id, outDir: dshOut)
            let result = env.results?.first
            if (env.ok ?? false), result?.isOK ?? false {
                ok("convert → dsh", "events=\(Fmt.int(result?.events)) artifact=\(Fmt.shortPath(result?.artifact, limit: 90))")
                let verifyPath = result?.outputDir ?? dshOut.path
                do {
                    let report = try bridge.verify(path: verifyPath)
                    let checked = report.checked ?? 0
                    let failedCount = report.failed ?? 0
                    if (report.ok ?? false) && failedCount == 0 && checked > 0 {
                        ok("asi verify", "checked=\(checked) failed=0 path=\(Fmt.shortPath(verifyPath, limit: 80))")
                    } else {
                        bad("asi verify", "checked=\(checked) failed=\(failedCount) error=\(report.error ?? "")")
                    }
                } catch {
                    bad("asi verify", error.localizedDescription)
                }
            } else {
                bad("convert → dsh", result?.error ?? env.error ?? "no result")
            }
        } catch {
            bad("convert → dsh", error.localizedDescription)
        }

        // coverage ledger
        do {
            let value = try bridge.coverage()
            if case .object(let obj) = value {
                let distinctCount: String
                if case .array(let arr)? = obj["after5_distinct"] { distinctCount = "\(arr.count)" }
                else { distinctCount = obj["after5_distinct"]?.displayString ?? "?" }
                let real = obj["real_count"]?.displayString ?? "?"
                let layered = obj["layered_v3"]?.displayString ?? "?"
                ok("coverage-report --json", "distinct=\(distinctCount) real_count=\(real) layered_v3=\(layered)")
            } else {
                bad("coverage-report --json", "返回非 JSON 对象")
            }
        } catch {
            bad("coverage-report --json", error.localizedDescription)
        }

        _ = caps

        // MARK: - product flow checks (task-32): detect → preview → migrate(export) → verify → history
        guard let productCaps = caps, let ws = Paths.discoverWorkspace() else {
            bad("产品流程：能力探测", "缺少 capabilities/workspace")
            return finish(pass: pass, fail: fail)
        }
        let productBridge = BackendBridge(workspace: ws)
        let productBackend = ProductBackend(bridge: productBridge, caps: productCaps)

        // detect
        do {
            let harnesses = try productBackend.detect()
            let usable = harnesses.filter { $0.detected && $0.sessionCount > 0 }
            if !usable.isEmpty {
                ok("产品流程：检测本机工具", usable.map { "\($0.name)=\($0.sessionCount)" }.joined(separator: ", "))
            } else {
                bad("产品流程：检测本机工具", "没有检测到含会话的工具")
            }
        } catch {
            bad("产品流程：检测本机工具", ProductBackend.userMessage(for: error))
        }

        let productBase = baseOut.appendingPathComponent("product", isDirectory: true)
        var productItems: [MigrationItemResult] = []

        // preview
        do {
            let preview = try productBackend.preview(source: source, session: session)
            if !preview.title.isEmpty {
                ok("产品流程：会话预览", "title=\(String(preview.title.prefix(40))) msgs=\(Fmt.int(preview.messageCount)) tools=\(Fmt.int(preview.toolCallCount)) source=\(preview.sourceNote)")
            } else {
                bad("产品流程：会话预览", "预览标题为空")
            }
        } catch {
            bad("产品流程：会话预览", ProductBackend.userMessage(for: error))
        }

        // session detail (product v1.2)
        do {
            let detail = try productBackend.sessionDetail(source: source, session: session)
            let mode = detail.isFallback ? "降级 preview（后端未提供 session-detail）" : "session-detail"
            let tokenText = detail.stats.usage.available ? "有 Token 统计" : "该工具未提供 Token 统计"
            if !detail.title.isEmpty {
                ok("产品流程：会话详情", "mode=\(detail.isFallback ? "preview" : "session-detail") events=\(detail.timeline.count) sections=\(detail.sections.count) usage=\(detail.stats.usage.available ? "available" : "unavailable")")
            } else {
                bad("产品流程：会话详情", "标题为空（mode=\(mode)）")
            }
            _ = tokenText
        } catch {
            bad("产品流程：会话详情", ProductBackend.userMessage(for: error))
        }

        // migrate → export (ATIF)
        do {
            let out = productBase.appendingPathComponent("export", isDirectory: true)
            var exportOptions = MigrationOptions(outputDir: out.path, mode: .export)
            exportOptions.environment = nil
            let item = try productBackend.migrateOne(source: source, session: session, target: "atif",
                                                     outputDir: out, options: exportOptions)
            productItems.append(item)
            if item.ok, Paths.pathExists(item.artifact) {
                ok("产品流程：迁移导出", "artifact=\(Fmt.shortPath(item.artifact, limit: 90))")
            } else {
                bad("产品流程：迁移导出", item.error ?? "artifact missing")
            }
        } catch {
            bad("产品流程：迁移导出", ProductBackend.userMessage(for: error))
        }

        // migrate → DSH + verify
        do {
            let out = productBase.appendingPathComponent("dsh", isDirectory: true)
            var dshExportOptions = MigrationOptions(outputDir: out.path, mode: .export)
            dshExportOptions.environment = nil
            let item = try productBackend.migrateOne(source: source, session: session, target: "dsh",
                                                     outputDir: out, options: dshExportOptions)
            productItems.append(item)
            if item.ok, (item.verifyStatus ?? "").contains("通过") {
                ok("产品流程：迁移到目标工具并校验", "verify=\(item.verifyStatus ?? "") output=\(Fmt.shortPath(item.outputDir, limit: 80))")
            } else {
                bad("产品流程：迁移到目标工具并校验", item.error ?? "verify=\(item.verifyStatus ?? "无")")
            }
        } catch {
            bad("产品流程：迁移到目标工具并校验", ProductBackend.userMessage(for: error))
        }

        // history persistence
        let historyStore = HistoryStore()
        let record = MigrationRecord(id: UUID(), date: Date(),
                                     sourceID: source, sourceName: HarnessCatalog.name(for: source),
                                     targetID: "atif", targetName: MigrationTarget.find("atif").title,
                                     mode: "export", outputDir: productBase.path,
                                     sessionCount: productItems.count,
                                     okCount: productItems.filter(\.ok).count,
                                     failCount: productItems.filter { !$0.ok }.count,
                                     items: productItems, isSelfTest: true,
                                     note: "self-test record")
        let recordsAfterSave = historyStore.append(record)
        let persisted = HistoryStore.fileURL
        let reloaded = historyStore.load()
        if Paths.pathExists(persisted.path), reloaded.contains(where: { $0.id == record.id }) {
            ok("产品流程：迁移历史持久化", "file=\(persisted.path) records=\(recordsAfterSave.count)")
        } else {
            bad("产品流程：迁移历史持久化", "file missing or record not reloaded: \(persisted.path)")
        }

        // MARK: - v1.3.1 history file: valid JSON array, atomic tmp cleanup, capped at 200
        do {
            let tmpPath = persisted.appendingPathExtension("tmp")
            let noTmp = !FileManager.default.fileExists(atPath: tmpPath.path)
            if let data = try? Data(contentsOf: persisted),
               let array = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
                let capped = array.count <= HistoryStore.maxRecords
                let sample = array.last
                let keysOK = sample?["id"] != nil && sample?["date"] != nil
                    && sample?["sourceID"] != nil && sample?["targetID"] != nil
                    && sample?["items"] != nil
                if capped && keysOK && noTmp {
                    ok("产品流程：历史文件原子写与上限",
                       "records=\(array.count) (max=\(HistoryStore.maxRecords)) tmpClean=true keysOK=true")
                } else {
                    bad("产品流程：历史文件原子写与上限",
                        "count=\(array.count) capped=\(capped) keysOK=\(keysOK) tmpClean=\(noTmp)")
                }
            } else {
                bad("产品流程：历史文件原子写与上限", "history.json 不是合法 JSON 数组")
            }
        }

        // MARK: - v1.5 brand + data directories (HarnessBridge)
        do {
            let historyDir = HistoryStore.directoryURL
            let outputRoot = Paths.outputRoot()
            let legacyConverter = AppDataMigration.legacyAppDataDirectories
                .first { FileManager.default.fileExists(atPath: $0.path) }
            let brandOK = AppInfo.name == "HarnessBridge"
                && historyDir.lastPathComponent == "HarnessBridge"
                && (outputRoot.lastPathComponent == "HarnessBridgeOut"
                    || Paths.outputRootOverride != nil)
                && FileManager.default.fileExists(atPath: HistoryStore.fileURL.path)
            let detail = "name=\(AppInfo.name) portable=\(Paths.isPortable) data=\(historyDir.path) output=\(outputRoot.path)"
                + (legacyConverter.map { " legacy=\($0.lastPathComponent)（存在旧目录，首次启动自动复制迁移）" } ?? "")
                + " backend=\(Paths.bundleBackendRoot?.path ?? "repo")"
                + " python=\(Paths.bundledPython ?? "system") zstd=\(Paths.bundledZstd ?? "system")"
            if brandOK {
                ok("品牌与数据目录", detail)
            } else {
                bad("品牌与数据目录", detail)
            }
        }

        // MARK: - v1.3 / v1.3.1 selection logic (pure engine, no backend required)
        do {
            let ids = ["a", "b", "c", "d", "e"]
            var engine = SelectionEngine()
            engine.selectAll(["a", "b"])
            let selectAllOK = engine.count == 2 && engine.isSelected("a") && engine.isSelected("b")
            engine.invert(ids)
            let invertOK = engine.count == 3 && engine.isSelected("c") && engine.isSelected("d") && engine.isSelected("e")
            engine.clear()
            engine.toggle("b", visibleIDs: ids)
            engine.toggle("d", visibleIDs: ids, rangeMode: true)
            let shiftOK = engine.count == 3 && engine.isSelected("b") && engine.isSelected("c") && engine.isSelected("d")

            // v1.3.1: stable anchor survives filter/sort reorder (same visible ids, new order)
            engine.clear()
            engine.toggle("b", visibleIDs: ["a", "b", "c", "d"])
            engine.toggle("d", visibleIDs: ["c", "d", "b"], rangeMode: true)
            let anchorReorderOK = engine.count == 2 && engine.isSelected("b") && engine.isSelected("d")

            // anchor hidden by a filter → next Shift-click behaves as a normal click
            engine.clear()
            engine.toggle("b", visibleIDs: ["a", "b", "c"])
            engine.toggle("d", visibleIDs: ["c", "d"], rangeMode: true)
            let anchorHiddenOK = engine.count == 2 && engine.isSelected("b") && engine.isSelected("d")

            // filter change keeps only still-visible selected ids
            engine.clear()
            engine.selectAll(["a", "b"])
            engine.retainOnly(["b", "c"])
            let retainOK = engine.count == 1 && engine.isSelected("b")

            if selectAllOK && invertOK && shiftOK && anchorReorderOK && anchorHiddenOK && retainOK {
                ok("产品流程：选择逻辑",
                   "全选/反选/Shift 范围/筛选后 anchor 稳定/过滤保留 全部通过")
            } else {
                bad("产品流程：选择逻辑",
                    "selectAll=\(selectAllOK) invert=\(invertOK) shift=\(shiftOK) anchorReorder=\(anchorReorderOK) anchorHidden=\(anchorHiddenOK) retain=\(retainOK)")
            }
        }


        // MARK: - v1.3.2 Esc decision (first Esc always reacts)
        do {
            let detailText = AppModel.escapeOutcome(page: .detail, detailHasText: true, textFocused: true,
                                                    wizardStep: 2, wizardRunning: false, hasSelection: false)
            let detailEmpty = AppModel.escapeOutcome(page: .detail, detailHasText: false, textFocused: false,
                                                     wizardStep: 2, wizardRunning: false, hasSelection: false)
            let listSelected = AppModel.escapeOutcome(page: .sessions, detailHasText: false, textFocused: false,
                                                      wizardStep: 2, wizardRunning: false, hasSelection: true)
            let listEmpty = AppModel.escapeOutcome(page: .sessions, detailHasText: false, textFocused: false,
                                                   wizardStep: 2, wizardRunning: false, hasSelection: false)
            let wizard = AppModel.escapeOutcome(page: .wizard, detailHasText: false, textFocused: false,
                                                wizardStep: 2, wizardRunning: false, hasSelection: false)
            let okEsc = detailText == .clearDetailSearch && detailEmpty == .closeDetail
                && listSelected == .clearSelection && listEmpty == .goHome && wizard == .wizardBack
            if okEsc {
                ok("产品流程：Esc 决策", "详情有文本→清空 / 详情空→返回 / 列表有选→清选 / 列表空→首页 / 向导→上一步 全部首次生效")
            } else {
                bad("产品流程：Esc 决策",
                    "detailText=\(detailText) detailEmpty=\(detailEmpty) listSel=\(listSelected) listEmpty=\(listEmpty) wizard=\(wizard)")
            }
        }

        // MARK: - v1.4 isolated install / keep / move+restore / migrate-all (never touches real stores)
        do {
            let fm = FileManager.default
            let iso = fm.temporaryDirectory.appendingPathComponent("sc-selftest-v14-\(Paths.stamp())-\(UUID().uuidString.prefix(8))")
            let home = iso.appendingPathComponent("home", isDirectory: true)
            let projects = home.appendingPathComponent(".claude/projects/-fixture", isDirectory: true)
            let dshHome = iso.appendingPathComponent("dsh", isDirectory: true)
            let testEnv: [String: String] = ["HOME": home.path, "CLAUDE_CONFIG_DIR": home.appendingPathComponent(".claude").path]
            do {
                try fm.createDirectory(at: projects, withIntermediateDirectories: true)
                guard let sourcePath = session.path, fm.fileExists(atPath: sourcePath) else {
                    throw ProductError.userFacing("测试准备失败：找不到 claude 源会话文件")
                }
                let fixture = projects.appendingPathComponent("\(session.id).jsonl")
                try fm.copyItem(atPath: sourcePath, toPath: fixture.path)
                let fixtureData = try Data(contentsOf: fixture)
                let listResult = try productBridge.run(["list", "claude", "--json", "--limit", "2000"],
                                                       timeout: 60, extraEnvironment: testEnv)
                let rows = try ProductBackend.decodeRows(listResult)
                guard let row = rows.first else {
                    throw ProductError.userFacing("隔离 HOME 中读不到会话")
                }
                try fm.createDirectory(at: dshHome, withIntermediateDirectories: true)
                var options = MigrationOptions(outputDir: "", mode: .install)
                options.targetHome = dshHome.path
                options.environment = testEnv
                let install = try productBackend.migrateOne(source: "claude", session: row,
                                                           target: "dsh",
                                                           outputDir: iso, options: options)
                let installedExists: Bool = {
                    guard let installed = install.installedPath else { return false }
                    return fm.fileExists(atPath: installed)
                }()
                let inTemp = (install.installedPath ?? "").hasPrefix(iso.path)
                if install.ok && install.verified == true && installedExists && inTemp {
                    ok("产品流程：install 隔离安装 + verify",
                       "verified=\(install.verified ?? false) installed=\(Fmt.shortPath(install.installedPath, limit: 70))")
                } else {
                    bad("产品流程：install 隔离安装 + verify",
                        "ok=\(install.ok) verified=\(String(describing: install.verified)) inTemp=\(inTemp) error=\(install.error ?? "")")
                }

                let keepData = try? Data(contentsOf: fixture)
                let keepOK = install.ok && fm.fileExists(atPath: fixture.path) && keepData == fixtureData
                if keepOK {
                    ok("产品流程：keep 保留源文件", "源文件存在且内容未变")
                } else {
                    bad("产品流程：keep 保留源文件", "源文件存在=\(fm.fileExists(atPath: fixture.path))")
                }

                // move + restore: prefer the fixed backend (real source_moved path)
                try? fm.removeItem(at: dshHome)
                try? fm.createDirectory(at: dshHome, withIntermediateDirectories: true)
                var moveOptions = options
                moveOptions.sessionMode = .move
                let moved = try productBackend.migrateOne(source: "claude", session: row,
                                                          target: "dsh",
                                                          outputDir: iso, options: moveOptions)
                let backendMove = productBackend.supportsSessionMode && productBackend.supportsMigrateRestore
                if backendMove {
                    let backup = moved.sourceBackupPath
                    let backupExists = backup.map { fm.fileExists(atPath: $0) } ?? false
                    let backupRenamed = (backup ?? "").contains(".migrated-")
                    let originalGone = !fm.fileExists(atPath: fixture.path)
                    let journal = moved.journalPath
                    let journalExists = journal.map { fm.fileExists(atPath: $0) } ?? false
                    var restoredCount = 0
                    if let journal {
                        restoredCount = (try? productBackend.restore(journalPath: journal))?.restored ?? 0
                    }
                    let restoreOK = moved.ok && moved.sourceMoved
                        && (moved.sourceMoveStatus == "moved")
                        && backupExists && backupRenamed && originalGone
                        && journalExists && restoredCount >= 1
                        && fm.fileExists(atPath: fixture.path)
                    if restoreOK {
                        ok("产品流程：move + restore 可恢复（后端真实 move）",
                           "source_moved=true status=moved backup=.migrated-*.bak journal=有 restore=已复原")
                    } else {
                        bad("产品流程：move + restore 可恢复（后端真实 move）",
                            "ok=\(moved.ok) moved=\(moved.sourceMoved) status=\(moved.sourceMoveStatus ?? "nil") backup=\(backupExists) renamed=\(backupRenamed) journal=\(journalExists) restored=\(restoredCount)")
                    }
                } else {
                    // Compatibility: older backend without --session-mode → app-side rename.
                    let backupPath = moved.sourceBackupPath
                    let backupExists: Bool = {
                        guard let backup = backupPath else { return false }
                        return fm.fileExists(atPath: backup) && backup.hasPrefix(iso.path)
                    }()
                    var journalFile: URL?
                    if moved.sourceMoved, let backup = backupPath {
                        journalFile = MigrationJournalStore.write(
                            entries: [SourceMoveEntry(sessionID: row.id, targetID: "dsh",
                                                      sourcePath: fixture.path, backupPath: backup,
                                                      installedPath: moved.installedPath, movedAt: Date())],
                            targetID: "dsh")
                    }
                    let restoreOutcome = journalFile.flatMap { SourceTransaction.restore(journalPath: $0.path) }
                    let restoreOK = moved.ok && moved.sourceMoved && backupExists
                        && (restoreOutcome?.restored ?? 0) == 1
                        && fm.fileExists(atPath: fixture.path)
                    if restoreOK {
                        ok("产品流程：move + restore 可恢复（旧后端兜底）", "App 改名 + journal 恢复")
                    } else {
                        bad("产品流程：move + restore 可恢复（旧后端兜底）",
                            "ok=\(moved.ok) moved=\(moved.sourceMoved) backup=\(backupExists) restored=\(String(describing: restoreOutcome?.restored))")
                    }
                }

                // migrate-all: dry-run must be zero-write; real isolated sample installs
                let sessionsDir = dshHome.appendingPathComponent("sessions", isDirectory: true)
                try? fm.removeItem(at: dshHome)
                try? fm.createDirectory(at: dshHome, withIntermediateDirectories: true)
                var plan = MigrateAllPlan(targetID: "dsh", targetName: "DeepSeek Harness",
                                          targetStorePath: sessionsDir.path,
                                          howToSee: "重启 DeepSeek Harness 后可见",
                                          mode: .install, sessionMode: .keep,
                                          sources: [MigrateAllSource(id: "claude", name: "Claude Code",
                                                                     sessionCount: rows.count,
                                                                     recentAtMs: nil, selected: true)],
                                          totalSessions: 1, limit: 1, sinceDays: nil)
                plan.sessionsBySource = ["claude": Array(rows.prefix(1))]
                plan.targetHome = dshHome.path
                plan.environment = testEnv
                let dry = productBackend.runMigrateAll(plan: plan, sessionMode: .keep, dryRun: true,
                                                       progress: { _, _, _ in }, shouldCancel: { false })
                let zeroWrites = dry.items.isEmpty && !fm.fileExists(atPath: sessionsDir.path)
                let real = productBackend.runMigrateAll(plan: plan, sessionMode: .keep, dryRun: false,
                                                        progress: { _, _, _ in }, shouldCancel: { false })
                let realInTemp = (real.items.first?.installedPath ?? "").hasPrefix(iso.path)
                let realOK = real.okCount >= 1 && fm.fileExists(atPath: sessionsDir.path) && realInTemp
                if zeroWrites && realOK {
                    ok("产品流程：migrate-all dry-run 零写入 + 隔离样本",
                       "dryItems=\(dry.items.count) realOK=\(real.okCount) installedInTemp=true")
                } else {
                    bad("产品流程：migrate-all dry-run 零写入 + 隔离样本",
                        "zeroWrites=\(zeroWrites) realOK=\(realOK) dryItems=\(dry.items.count)")
                }
                // Cancel must really terminate the backend process (not just UI).
                do {
                    let cancelFlag = CancellationFlag()
                    var killResult: CommandResult?
                    let group = DispatchGroup()
                    group.enter()
                    DispatchQueue.global(qos: .userInitiated).async {
                        killResult = try? productBridge.run(["matrix", "--json", "--limit", "1"],
                                                            timeout: 120,
                                                            cwd: iso,
                                                            cancellation: cancelFlag)
                        group.leave()
                    }
                    DispatchQueue.global().asyncAfter(deadline: .now() + 0.15) {
                        cancelFlag.set(true)
                    }
                    group.wait()
                    if killResult?.wasCancelled == true {
                        ok("产品流程：取消终止后端进程", "后端进程被 SIGTERM/SIGKILL 终止，未继续写盘")
                    } else {
                        bad("产品流程：取消终止后端进程",
                            "wasCancelled=\(String(describing: killResult?.wasCancelled))（命令可能已过快结束）")
                    }
                }

                // Cancel during app-side loop keeps completed items + journal.
                do {
                    let second = projects.appendingPathComponent("\(UUID().uuidString).jsonl")
                    try? fm.copyItem(atPath: fixture.path, toPath: second.path)
                    let listResult = try productBridge.run(["list", "claude", "--json", "--limit", "50"],
                                                           timeout: 60, extraEnvironment: testEnv)
                    let manyRows = try ProductBackend.decodeRows(listResult)
                    try? fm.removeItem(at: dshHome)
                    try? fm.createDirectory(at: dshHome, withIntermediateDirectories: true)
                    var cancelPlan = MigrateAllPlan(targetID: "dsh", targetName: "DeepSeek Harness",
                                                    targetStorePath: dshHome.appendingPathComponent("sessions").path,
                                                    howToSee: "重启后可见", mode: .install, sessionMode: .move,
                                                    sources: [MigrateAllSource(id: "claude", name: "Claude Code",
                                                                               sessionCount: manyRows.count,
                                                                               recentAtMs: nil, selected: true)],
                                                    totalSessions: min(2, manyRows.count), limit: 2, sinceDays: nil)
                    cancelPlan.sessionsBySource = ["claude": Array(manyRows.prefix(2))]
                    cancelPlan.targetHome = dshHome.path
                    cancelPlan.environment = testEnv
                    let processed = CancellationFlag()
                    let cancelReport = productBackend.runMigrateAll(
                        plan: cancelPlan, sessionMode: .move,
                        progress: { done, _, _ in if done >= 1 { processed.set(true) } },
                        shouldCancel: { processed.isSet() })
                    let journal = MigrationJournalStore.write(
                        entries: cancelReport.items.compactMap { item -> SourceMoveEntry? in
                            guard item.sourceMoved, let backup = item.sourceBackupPath else { return nil }
                            return SourceMoveEntry(sessionID: item.sessionID, targetID: "dsh",
                                                   sourcePath: item.sourcePath ?? "", backupPath: backup,
                                                   installedPath: item.installedPath, movedAt: Date())
                        },
                        targetID: "dsh")
                    let journalOK = journal.map { fm.fileExists(atPath: $0.path) } ?? false
                    let partialOK = cancelReport.cancelled
                        && cancelReport.items.count >= 1
                        && cancelReport.items.contains(where: { $0.sourceMoved })
                        && journalOK
                    if partialOK {
                        ok("产品流程：取消保留已完成项与 journal",
                           "cancelled=true completed=\(cancelReport.items.count) journal=保留")
                    } else {
                        bad("产品流程：取消保留已完成项与 journal",
                            "cancelled=\(cancelReport.cancelled) items=\(cancelReport.items.count) journal=\(journalOK)")
                    }
                }

                try? fm.removeItem(at: iso)
            } catch {
                bad("产品流程：隔离安装测试", ProductBackend.userMessage(for: error))
                try? fm.removeItem(at: iso)
            }
        }

        // MARK: - v1.3 performance baseline (detect / list / preview / session-detail)
        do {
            let thresholds: (detect: TimeInterval, list: TimeInterval, preview: TimeInterval, detail: TimeInterval) = (5, 8, 8, 8)
            let detectStart = Date()
            let harnesses = (try? productBackend.detect()) ?? []
            let detectTime = Date().timeIntervalSince(detectStart)

            let listStart = Date()
            let codexRows = (try? productBridge.list(source: "codex")) ?? []
            let listTime = Date().timeIntervalSince(listStart)

            let previewStart = Date()
            let previewProbe = (try? productBackend.preview(source: source, session: session)) ?? nil
            let previewTime = Date().timeIntervalSince(previewStart)

            // stress: full event timeline of the largest known session (qoder ~16k lines)
            let detailStart = Date()
            let qoderRows = (try? productBridge.list(source: "qoder")) ?? []
            let largest = qoderRows.max { ($0.lines ?? 0) < ($1.lines ?? 0) } ?? session
            let detailProbe = try? productBackend.sessionDetail(source: "qoder", session: largest, maxEvents: 0)
            let detailTime = Date().timeIntervalSince(detailStart)

            let okAll = detectTime < thresholds.detect && listTime < thresholds.list
                && previewTime < thresholds.preview && detailTime < thresholds.detail
                && !harnesses.isEmpty && !codexRows.isEmpty && previewProbe != nil
                && (detailProbe?.timeline.count ?? 0) > 0
            let message = String(format: "detect=%.2fs list=%.2fs preview=%.2fs detail(0)=%.2fs events=%d",
                                 detectTime, listTime, previewTime, detailTime, detailProbe?.timeline.count ?? 0)
            if okAll {
                ok("产品流程：性能基线", message + "（阈值 detect<5s / list,preview,detail<8s）")
            } else {
                bad("产品流程：性能基线", message + "（阈值 detect<5s / list,preview,detail<8s）")
            }
        }

        return finish(pass: pass, fail: fail)
    }

    private static func atifStepCount(_ path: String?) -> Int? {
        guard let path, Paths.pathExists(path),
              let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let steps = obj["steps"] as? [Any] else { return nil }
        return steps.count
    }

    private static func finish(pass: Int, fail: Int) -> Int32 {
        print("SUMMARY: \(pass) PASS / \(fail) FAIL")
        if fail == 0 {
            print("RESULT: PASS (exit 0)")
            return 0
        }
        print("RESULT: FAIL (exit 1)")
        return 1
    }

    // MARK: - diagnose
    static func diagnose() -> Int32 {
        print("HarnessBridge diagnose v\(AppInfo.version)")
        print("time: \(ISO8601DateFormatter().string(from: Date()))")
        let os = ProcessInfo.processInfo.operatingSystemVersion
        print("macOS: \(os.majorVersion).\(os.minorVersion).\(os.patchVersion)")
        print("architecture: \(machineArchitecture())")
        print("executable: \(Bundle.main.executablePath ?? CommandLine.arguments[0])")
        print("bundle: \(Bundle.main.bundlePath)")
        print("PATH: \(BackendBridge.enrichedEnvironment["PATH"] ?? "")")
        print("output root: \(Paths.outputRoot().path)")
        print("workspace override: \(Paths.workspaceOverride ?? "(none)")")
        if let ws = Paths.discoverWorkspace() {
            print("workspace: \(ws.path)")
            let bridge = BackendBridge(workspace: ws)
            print("asi: \(bridge.asiPath.path)")
            print("asi executable: \(FileManager.default.isExecutableFile(atPath: bridge.asiPath.path))")
            print("asi version: \((try? bridge.version()) ?? "unavailable")")
            if let caps = try? bridge.capabilities() {
                print("capabilities.sources(\(caps.sources.count)): \(caps.sources.joined(separator: ","))")
                print("capabilities.targets(\(caps.targetChoices.count)): \(caps.targetChoices.joined(separator: ","))")
                print("capabilities.matrix: \(caps.matrixKinds.joined(separator: ","))")
            } else {
                print("capabilities: unavailable")
            }
            print("coverage script: \(bridge.coverageScript.path)")
            let historyPath = HistoryStore.fileURL.path
            print("brand: \(AppInfo.name) — \(AppInfo.tagline) v\(AppInfo.version)")
            print("portable: \(Paths.isPortable)")
            print("backend root: \(Paths.bundleBackendRoot?.path ?? "(repo/workspace mode)")")
            print("bundled python: \(Paths.bundledPython ?? "none (system python)")")
            print("bundled zstd: \(Paths.bundledZstd ?? "none (system zstd)")")
            print("data dir: \(HistoryStore.directoryURL.path)")
            for legacy in AppDataMigration.legacyAppDataDirectories {
                print("legacy data dir: \(legacy.path) (exists: \(FileManager.default.fileExists(atPath: legacy.path)))")
            }
            print("default output root: \(Paths.outputRoot().path)")
            if #available(macOS 26.0, *) {
                print("liquid glass: available (macOS 26+) reduceTransparency=\(NSWorkspace.shared.accessibilityDisplayShouldReduceTransparency)")
            } else {
                print("liquid glass: fallback material (macOS < 26)")
            }
            print("history file: \(historyPath) (exists: \(FileManager.default.fileExists(atPath: historyPath)))")
        } else {
            print("workspace: NOT FOUND (set SESSION_CONVERTER_WORKSPACE or use the app Settings)")
        }
        print("product history: \(HistoryStore.fileURL.path)")
        print("RESULT: diagnose complete (exit 0)")
        return 0
    }

    private static func machineArchitecture() -> String {
        var info = utsname()
        uname(&info)
        let mirror = Mirror(reflecting: info.machine)
        let bytes = mirror.children.compactMap { $0.value as? Int8 }.map { UInt8(bitPattern: $0) }
        return String(decoding: bytes.filter { $0 != 0 }, as: UTF8.self)
    }
}
