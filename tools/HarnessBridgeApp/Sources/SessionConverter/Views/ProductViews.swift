import SwiftUI
import AppKit

// MARK: - Session browser (product v1.3: selection / sort / density / incremental)
struct SessionsBrowserView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            if model.bulkExportRunning {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(model.bulkExportProgress).font(.caption).foregroundStyle(.secondary)
                }
            }
            selectionToolbar
            if model.browserSelectedCount > 0 { bulkBar }
            listCard
            Text("提示：点击会话打开详情；勾选框选择后可批量迁移/导出；Shift+点击连续选择，⌘A 全选（输入框内为文本全选），Esc 清除；刷新后已选中但已不存在的会话会自动移除。")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 2)
        }
        .padding(20)
        .onAppear {
            if model.browserSessions.isEmpty && !model.browserLoading {
                Task { await model.loadBrowserSessions() }
            }
        }
        .onDisappear {
            model.browserScrollAnchorID = model.browserScrollAnchorID
        }
    }

    // MARK: header
    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("浏览会话").font(.title2.weight(.bold))
                Text("按工具筛选与搜索，支持多选批量迁移/导出。").font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            HarnessLogoView(harnessID: model.browserHarness, size: 22)
            Picker("工具", selection: Binding(
                get: { model.browserHarness },
                set: { model.setBrowserHarness($0) }
            )) {
                ForEach(model.harnesses.filter { $0.sessionCount > 0 }) { harness in
                    Text(harness.name).tag(harness.id)
                }
            }
            .frame(width: 190)
            Button {
                Task { await model.loadBrowserSessions(force: true) }
            } label: {
                Label("刷新", systemImage: "arrow.clockwise")
            }
            .help("⌘R")
            Menu {
                ForEach(BrowserSort.allCases) { sort in
                    Button {
                        model.setBrowserSort(sort)
                    } label: {
                        if model.browserSort == sort { Label(sort.label, systemImage: "checkmark") }
                        else { Text(sort.label) }
                    }
                }
                Divider()
                ForEach(ListDensity.allCases) { density in
                    Button {
                        model.setBrowserDensity(density)
                    } label: {
                        if model.browserDensity == density { Label("显示密度：\(density.label)", systemImage: "checkmark") }
                        else { Text("显示密度：\(density.label)") }
                    }
                }
            } label: {
                Label("排序与密度", systemImage: "arrow.up.arrow.down")
            }
            .frame(width: 130)
        }
    }

    // MARK: selection toolbar
    private var selectionToolbar: some View {
        HStack(spacing: 8) {
            HStack(spacing: 5) {
                Image(systemName: "checkmark.circle")
                    .foregroundStyle(model.browserSelectedCount > 0 ? Color.accentColor : .secondary)
                Text("已选 \(model.browserSelectedCount) / 共 \(model.browserFilteredCount)（筛选后）")
                    .font(.callout)
            }
            Divider().frame(height: 14)
            Button("全选当前筛选") { model.selectAllBrowserFiltered() }
                .controlSize(.small)
                .help("⌘A")
            Button("反选") { model.invertBrowserSelection() }
                .controlSize(.small)
            Button("取消选择") { model.clearBrowserSelection() }
                .controlSize(.small)
                .disabled(model.browserSelectedCount == 0)
            Spacer()
            if model.browserSessions.count > 0 {
                Text("共 \(model.browserSessions.count) 个会话 · 显示 \(model.browserFilteredSessions.count)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 2)
    }

    private var bulkBar: some View {
        HStack(spacing: 10) {
            Label("批量操作", systemImage: "square.stack.3d.up.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tint)
            Button {
                model.requestBulkMigrate()
            } label: {
                Label("迁移所选（\(model.browserSelectedCount)）", systemImage: "arrow.right.circle")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            Button {
                model.requestBulkExport()
            } label: {
                Label("导出所选", systemImage: "square.and.arrow.up")
            }
            .controlSize(.small)
            Button {
                model.copyBrowserSelectionSummary()
            } label: {
                Label("复制摘要", systemImage: "doc.on.doc")
            }
            .controlSize(.small)
            Spacer()
            Button("取消选择") { model.clearBrowserSelection() }
                .controlSize(.small)
        }
        .padding(10)
        .background(Color.accentColor.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.accentColor.opacity(0.25)))
        .transition(.move(edge: .top).combined(with: .opacity))
        .animation(Motion.spring, value: model.browserSelectedCount > 0)
    }

    // MARK: list
    private var listCard: some View {
        CardBox(title: "会话", systemImage: "list.bullet.rectangle") {
            VStack(alignment: .leading, spacing: 6) {
                SearchField(placeholder: "搜索标题 / 会话 ID / 项目路径 / 模型…",
                            text: Binding(get: { model.browserSearchInput },
                                          set: { model.setBrowserSearchInput($0) }),
                            focusRequest: model.searchFocusRequest)
                    .frame(height: 26)
                Text("搜索范围：标题、会话 ID、项目路径、模型（输入后 0.25 秒自动过滤）")
                    .font(.caption2).foregroundStyle(.secondary)
                if let error = model.browserError {
                    HStack {
                        Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                        Button("重试") { Task { await model.loadBrowserSessions(force: true) } }
                            .controlSize(.small)
                    }
                }
                if model.browserLoading {
                    SkeletonList(rows: 7)
                        .frame(minHeight: 200, alignment: .top)
                } else if model.browserFilteredSessions.isEmpty {
                    EmptyHint(icon: "bubble.left.and.bubble.right",
                              text: model.browserSessions.isEmpty
                              ? "该工具暂时没有可读取的会话" : "没有匹配的会话，试试清空搜索",
                              actionTitle: model.browserSessions.isEmpty ? "刷新" : nil) {
                        Task { await model.loadBrowserSessions(force: true) }
                    }
                } else {
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(spacing: 0) {
                                ForEach(model.browserFilteredSessions) { session in
                                    browserRow(session)
                                        .id(session.id)
                                        .onAppear {
                                            model.browserScrollAnchorID = session.id
                                            if session.id == model.browserFilteredSessions.last?.id {
                                                model.loadMoreBrowser()
                                            }
                                        }
                                    Divider()
                                }
                                if model.browserHasMore {
                                    Button {
                                        model.loadMoreBrowser()
                                    } label: {
                                        Label("加载更多（剩余 \(model.browserFilteredCount - model.browserFilteredSessions.count)）",
                                              systemImage: "arrow.down.circle")
                                    }
                                    .controlSize(.small)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 8)
                                }
                            }
                        }
                        .frame(maxHeight: 520)
                        .onAppear {
                            if let anchor = model.browserScrollAnchorID {
                                DispatchQueue.main.async { proxy.scrollTo(anchor, anchor: .center) }
                            }
                        }
                    }
                }
            }
        }
        .animation(Motion.list, value: model.browserFilteredSessions.count)
        .animation(Motion.list, value: model.browserDensity)
    }

    private func browserRow(_ session: SessionRow) -> some View {
        let selected = model.browserSelection.isSelected(session.id)
        let density = model.browserDensity
        return HStack(spacing: 8) {
            Button {
                model.toggleBrowserSelection(session, shift: NSEvent.modifierFlags.contains(.shift))
            } label: {
                Image(systemName: selected ? "checkmark.square.fill" : "square")
                    .font(.system(size: 16))
                    .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                    .scaleEffect(selected && !Motion.reduceMotion ? 1.08 : 1)
                    .animation(Motion.quick, value: selected)
            }
            .buttonStyle(.plain)
            .help("选择会话（Shift 点击连续选择）")
            Button {
                model.openSessionDetail(source: model.browserHarness, session: session)
            } label: {
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(session.displayTitle).font(.callout).lineLimit(1)
                        Text("\(Fmt.time(session.createdAtMs)) · \(Fmt.shortPath(session.cwd, limit: 46))")
                            .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer()
                    if let lines = session.lines {
                        Text("\(lines) 行").font(.caption2.monospaced()).foregroundStyle(.secondary)
                    }
                    Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.secondary.opacity(0.6))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.vertical, density.rowPadding)
        .padding(.horizontal, 4)
        .background(selected ? Color.accentColor.opacity(0.10) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .hoverLift(scale: 1.003, shadow: 0.05)
        .transition(.opacity.combined(with: .move(edge: .top)))
    }
}

// MARK: - Migration history
struct HistoryView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("迁移历史").font(.title2.weight(.bold))
                    Text("记录保存在本机，重启应用后仍然可查看。").font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                Button(role: .destructive) {
                    model.requestClearHistory()
                } label: {
                    Label("清除历史", systemImage: "trash")
                }
                .disabled(model.visibleHistory.isEmpty)
            }
            if model.visibleHistory.isEmpty {
                EmptyHint(icon: "clock.arrow.circlepath", text: "还没有迁移记录",
                          actionTitle: "开始迁移") { model.migrateFromHome() }
            } else {
                HStack(alignment: .top, spacing: 12) {
                    CardBox(title: "记录（\(model.visibleHistory.count)）", systemImage: "clock") {
                        ScrollView {
                            LazyVStack(spacing: 0) {
                                ForEach(model.visibleHistory) { record in
                                    recordRow(record)
                                    Divider()
                                }
                            }
                        }
                        .frame(maxHeight: 460)
                    }
                    .frame(minWidth: 380)
                    historyDetail
                        .frame(minWidth: 420)
                }
            }
        }
        .padding(20)
        .onAppear {
            model.reloadHistory()
            if model.historySelectedID == nil { model.historySelectedID = model.visibleHistory.first?.id }
        }
    }

    private func recordRow(_ record: MigrationRecord) -> some View {
        Button {
            model.historySelectedID = record.id
        } label: {
            HStack(spacing: 8) {
                Image(systemName: record.failCount == 0 ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                    .foregroundStyle(record.failCount == 0 ? .green : .orange)
                VStack(alignment: .leading, spacing: 1) {
                    Text("\(record.sourceName) → \(record.targetName)")
                        .font(.callout.weight(.medium)).lineLimit(1)
                    Text("\(Fmt.date(record.date)) · \(record.sessionCount) 个会话 · \(record.statusText)")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.vertical, 5)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(model.historySelectedID == record.id ? Color.accentColor.opacity(0.08) : Color.clear)
    }

    private var historyDetail: some View {
        CardBox(title: "记录详情", systemImage: "doc.text") {
            if let record = model.record(model.historySelectedID) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        StatusPill(text: record.statusText,
                                   color: record.failCount == 0 ? .green : (record.okCount > 0 ? .orange : .red))
                        Spacer()
                        Text(Fmt.date(record.date)).font(.caption).foregroundStyle(.secondary)
                    }
                    InfoRow(label: "来源", value: record.sourceName)
                    InfoRow(label: "目标", value: record.targetName)
                    if let store = record.targetStorePath, !store.isEmpty {
                        InfoRow(label: "会话库", value: store, mono: true)
                    }
                    InfoRow(label: "模式", value: record.mode == "install" ? "直接迁移" : "仅导出")
                    if let stop = record.sessionMode {
                        InfoRow(label: "原始会话", value: stop == "move" ? "已移出（可恢复）" : "保留")
                    }
                    if record.outputDir.isEmpty == false {
                        InfoRow(label: "输出目录", value: record.outputDir, mono: true)
                    }
                    InfoRow(label: "会话数", value: "\(record.sessionCount)（成功 \(record.okCount)，失败 \(record.failCount)，跳过 \(record.skippedCount ?? 0)）")
                    if let note = record.note { InfoRow(label: "备注", value: note) }
                    if let source = record.items.compactMap(\.sourcePath).first, !source.isEmpty {
                        HStack {
                            Text("源文件：\(Fmt.shortPath(source, limit: 60))")
                                .font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                            Button("定位") { model.revealInFinder(source) }.controlSize(.small)
                        }
                    }
                    if let journal = record.journalPath {
                        HStack {
                            Text("迁移日志：\(Fmt.shortPath(journal, limit: 60))")
                                .font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                            Button("打开") { model.revealInFinder(journal) }.controlSize(.small)
                        }
                    }
                    HStack {
                        Button {
                            model.revealInFinder(record.outputDir)
                        } label: {
                            Label("打开文件夹", systemImage: "folder")
                        }
                        Button {
                            model.copyHistorySummary(record)
                        } label: {
                            Label("复制摘要", systemImage: "doc.on.doc")
                        }
                        if let journal = record.journalPath {
                            Button {
                                model.restoreJournal(journal)
                            } label: {
                                Label("恢复被移出的会话", systemImage: "arrow.uturn.backward")
                            }
                        }
                        Button(role: .destructive) {
                            model.deleteHistory(record.id)
                        } label: {
                            Label("删除记录", systemImage: "trash")
                        }
                    }
                    Divider()
                    Text("逐会话结果").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    ScrollView {
                        VStack(alignment: .leading, spacing: 5) {
                            ForEach(record.items) { item in
                                HStack(alignment: .top, spacing: 6) {
                                    Image(systemName: item.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                                        .foregroundStyle(item.ok ? .green : .red).font(.caption)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(item.title).font(.caption).lineLimit(2)
                                        if let verify = item.verifyStatus {
                                            Text(verify).font(.caption2).foregroundStyle(.secondary)
                                        }
                                        if let error = item.error {
                                            Text(error).font(.caption2).foregroundStyle(.red).lineLimit(2)
                                        }
                                    }
                                    Spacer()
                                }
                            }
                        }
                    }
                    .frame(maxHeight: 220)
                }
            } else {
                EmptyHint(icon: "sidebar.left", text: "选择左侧记录查看详情")
            }
        }
    }
}

// MARK: - Settings
struct SettingsView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("设置").font(.title2.weight(.bold))
                CardBox(title: "保存位置", systemImage: "folder") {
                    HStack {
                        Text(model.outputDir).font(.callout.monospaced()).lineLimit(1).textSelection(.enabled)
                        Spacer()
                        Button("选择文件夹…") { model.chooseOutputDirectory() }
                        Button("打开") { model.revealOutput() }
                    }
                }
                CardBox(title: "会话工具位置", subtitle: "一般无需修改", systemImage: "gearshape.2") {
                    HStack {
                        TextField("自动检测的工具目录", text: $model.settingsWorkspace)
                            .textFieldStyle(.roundedBorder)
                        Button("自动检测") { model.detectWorkspacePath() }
                    }
                    HStack(spacing: 6) {
                        Circle()
                            .fill(model.backendReady ? Color.green : Color.orange)
                            .frame(width: 7, height: 7)
                        Text(model.backendReady ? "状态：已连接（自动检测）" : "状态：未连接")
                            .font(.caption2).foregroundStyle(.secondary)
                        Spacer()
                        Button("查看环境信息") { model.page = .advanced }
                            .controlSize(.small)
                    }
                    Text("如果应用找不到你已安装的会话工具，可以在这里手动指定其所在目录（不是单个文件）。")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                CardBox(title: "界面", systemImage: "textformat") {
                    HStack {
                        Text("界面语言")
                        Spacer()
                        Text("简体中文").foregroundStyle(.secondary)
                    }
                    HStack {
                        Text("重新查看欢迎页")
                        Spacer()
                        Button("查看") { model.resetWelcomeFlag() }
                    }
                }
                CardBox(title: "工具会话库", subtitle: "直接迁移会写入目标工具自己的会话库", systemImage: "internaldrive") {
                    ForEach(model.detectedHarnesses) { harness in
                        HStack(alignment: .top, spacing: 8) {
                            HarnessLogoView(harnessID: harness.id, size: 18)
                            VStack(alignment: .leading, spacing: 1) {
                                HStack(spacing: 6) {
                                    Text(harness.name).font(.callout)
                                    StatusPill(text: harness.installSupported
                                                ? (harness.installExperimental ? "实验性写入" : "支持直接迁移")
                                                : "仅导出",
                                                color: harness.installSupported
                                                ? (harness.installExperimental ? .orange : .green) : .secondary)
                                }
                                if !harness.storePath.isEmpty {
                                    Text(harness.storePath).font(.caption2.monospaced())
                                        .foregroundStyle(.secondary).lineLimit(1)
                                }
                                if let how = harness.howToSee, !how.isEmpty {
                                    Text(how).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                                }
                            }
                            Spacer()
                        }
                        .padding(.vertical, 2)
                    }
                }
                CardBox(title: "数据与隐私", systemImage: "lock.shield") {
                    Text("原始会话始终只读，不会被修改。迁移结果只写入你选择的输出文件夹；只有显式开启「直接写入真实 Harness」时才会写入目标工具的数据目录（写入前后端会自动备份）。")
                        .font(.caption).foregroundStyle(.secondary)
                    HStack {
                        Text("迁移历史（本机保存）")
                        Spacer()
                        Button("重新载入") { model.reloadHistory() }
                        Button(role: .destructive) { model.requestClearHistory() } label: { Text("清除历史") }
                            .disabled(model.visibleHistory.isEmpty)
                    }
                }
                CardBox(title: "关于", systemImage: "info.circle") {
                    InfoRow(label: "应用", value: "\(AppInfo.name) — \(AppInfo.tagline)")
                    InfoRow(label: "版本", value: AppInfo.version)
                    InfoRow(label: "后端", value: model.productModeText.isEmpty ? "—" : model.productModeText)
                    Text("HarnessBridge（Agent Session Converter）— 开源项目 github.com/Larrtroffen/harnessbridge。")
                        .font(.caption2).foregroundStyle(.secondary)
                    Text("证据等级说明：「已验证」表示该方向的迁移已通过格式级与加载校验；「实验性」表示可以生成文件但仍在完善。迁移结果中的「有损」表示目标工具没有完全对应的概念，部分信息会被省略。")
                        .font(.caption2).foregroundStyle(.secondary)
                    HStack {
                        Button("应用文档") {
                            model.openPath(model.workspacePath + "/docs/swift-app.md")
                        }
                        Button("高级工具") { model.page = .advanced }
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: 760, alignment: .leading)
        }
    }
}

// MARK: - Help
struct HelpView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("帮助").font(.title2.weight(.bold))
                faq("如何把会话迁移到 DeepSeek Harness？",
                    "在「迁移会话」里选择来源工具和会话，目标选「DeepSeek Harness」，然后按提示继续。迁移完成后重启 DeepSeek Harness，就能在对应项目中看到这些会话。")
                faq("迁移会修改我的原始会话吗？",
                    "不会。应用对所有原始会话只读；迁移结果会先写入你选择的文件夹。只有你显式开启「直接写入真实 Harness」时才会写入目标工具的数据目录，并且会先自动备份。")
                faq("为什么有些会话显示「有损」？",
                    "不同工具的会话格式不完全一样，有些信息（例如工具调用细节、系统提示词、时间戳）在目标工具里没有完全对应的概念。标出「有损」是为了让你知道哪些内容被省略了；原始会话不受影响。")
                faq("打开应用时提示无法验证开发者（Gatekeeper）",
                    "这是本地构建应用的常见提示。可以在「系统设置 → 隐私与安全性」中允许打开，或右键点击应用选择「打开」。")
                faq("找不到我安装的工具 / 会话数为 0",
                    "请确认该工具至少使用过一次并保存了会话。仍找不到时，在「设置 → 会话工具位置」里手动指定工具目录（包含会话数据的那个文件夹）。")
                faq("迁移完成后在目标工具里看不到会话",
                    "部分工具需要刷新或重启才能在界面中显示新会话；如果目标选了「注册到项目」，请重启目标工具后再查看。你也可以点击结果页的「打开输出文件夹」先确认文件已生成。")
                faq("我的数据会上传吗？",
                    "不会。所有处理和文件读写都在本机、在你选择的目录内完成，应用不包含任何网络上传逻辑。")
                CardBox(title: "诊断", systemImage: "stethoscope") {
                    Text("如果通过以上方法仍无法解决，可以把下面的信息提供给开发者。")
                        .font(.caption).foregroundStyle(.secondary)
                    InfoRow(label: "工具连接", value: model.backendReady ? "正常" : "异常")
                    InfoRow(label: "输出目录", value: model.outputDir, mono: true)
                    Text("更多环境信息可在「高级工具 → 环境信息」中查看。")
                        .font(.caption2).foregroundStyle(.secondary)
                    Button("打开高级工具 / 日志") { model.page = .advanced }
                }
            }
            .padding(20)
            .frame(maxWidth: 760, alignment: .leading)
        }
    }

    private func faq(_ question: String, _ answer: String) -> some View {
        CardBox(title: question, systemImage: "questionmark.circle") {
            Text(answer).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
