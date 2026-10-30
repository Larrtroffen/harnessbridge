import SwiftUI
import AppKit

// MARK: - Migration wizard (5 steps, v1.3 selection + animation polish)
struct WizardView: View {
    @EnvironmentObject var model: AppModel
    private let stepTitles = ["选来源", "选会话", "选目标", "选项", "执行"]

    private var shiftPressed: Bool { NSEvent.modifierFlags.contains(.shift) }

    var body: some View {
        VStack(spacing: 0) {
            StepIndicator(steps: stepTitles, current: model.wizard.step)
                .padding(.horizontal, 20)
                .padding(.vertical, 4)
                .animation(Motion.spring, value: model.wizard.step)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    stepContent
                        .id(model.wizard.step)
                        .transition(.asymmetric(
                            insertion: .move(edge: .trailing).combined(with: .opacity),
                            removal: .move(edge: .leading).combined(with: .opacity)))
                }
                .padding(20)
            }
            .animation(Motion.spring, value: model.wizard.step)
            Divider()
            footer
        }
        .alert("确认开始迁移？", isPresented: Binding(
            get: { model.showMigrationConfirm },
            set: { model.showMigrationConfirm = $0 }
        )) {
            Button("取消", role: .cancel) { model.showMigrationConfirm = false }
            Button("开始迁移") { model.confirmMigrationAndRun() }
        } message: {
            Text(model.migrationConfirmSummary)
        }
        .alert("确认写入真实 Harness？", isPresented: Binding(
            get: { model.showInstallConfirm },
            set: { model.showInstallConfirm = $0 }
        )) {
            Button("取消", role: .cancel) {
                model.wizard.options.mode = .export
                model.showInstallConfirm = false
            }
            Button("我了解风险，继续", role: .destructive) {
                model.wizard.options.mode = .install
                model.showInstallConfirm = false
            }
        } message: {
            Text("开启后，迁移结果会同时写入目标 Harness 的真实数据目录，以便直接在目标工具中打开。\n\n我们会在写入前自动备份，但仍建议先保留一份导出文件。此功能默认关闭。")
        }
        .alert("确认移出原始会话？", isPresented: Binding(
            get: { model.showMoveConfirm },
            set: { model.showMoveConfirm = $0 }
        )) {
            Button("取消", role: .cancel) {
                model.wizard.options.sessionMode = .keep
                model.showMoveConfirm = false
            }
            Button("移出（可恢复）", role: .destructive) {
                Motion.run(Motion.quick) { model.wizard.options.sessionMode = .move }
                model.showMoveConfirm = false
            }
        } message: {
            Text("迁移成功后会把这些来源会话重命名为同目录 `.migrated-<时间>.bak`（不删除），可在结果页或迁移历史中用「恢复被移出的会话」还原。")
        }
        .task(id: "\(model.wizard.step)-\(model.wizard.sessions.count)") {
            if model.wizard.step == 2, model.wizard.previewFocusID == nil,
               let first = model.wizardFilteredSessions.first {
                await model.focusWizardPreview(first)
            }
        }

    }

    @ViewBuilder
    private var stepContent: some View {
        switch model.wizard.step {
        case 1: sourceStep
        case 2: sessionStep
        case 3: targetStep
        case 4: optionsStep
        default: executionStep
        }
    }

    // MARK: footer
    private var footer: some View {
        HStack(spacing: 10) {
            if model.wizard.step == 1 {
                Button("取消") { model.finishWizard() }
            } else if !model.wizard.running {
                Button("上一步") { model.wizardBack() }
            }
            Text("⌘↩ 继续 / Esc 返回").font(.caption2).foregroundStyle(.secondary)
            Spacer()
            if model.wizard.step == 5 {
                if model.wizard.finished {
                    Button("返回首页") { model.finishWizard() }
                        .buttonStyle(.borderedProminent)
                        .buttonStyle(PressScaleButtonStyle())
                    Button("再迁移一次") { model.startWizard(sourceID: nil) }
                } else if model.wizard.running {
                    Text(model.wizard.progressText).font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text("步骤 \(model.wizard.step) / 5").font(.caption).foregroundStyle(.secondary)
                Button(model.wizard.step == 4 ? "开始迁移" : "继续") {
                    model.wizardNext()
                }
                .buttonStyle(GlassProminentButtonStyle())
                .disabled(!model.wizardCanContinue)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
    }

    // MARK: Step 1 — source
    private var sourceStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            stepHeader("选择来源", detail: "从哪个工具迁移会话？只显示本机检测到会话的工具。")
            let available = model.harnesses.filter { $0.sessionCount > 0 }
            if available.isEmpty {
                CardBox(title: "暂时没有可用会话", systemImage: "tray") {
                    Text("没有检测到任何会话。请确认已安装并使用过支持的 AI 编程工具，然后在「首页」刷新检测。")
                        .foregroundStyle(.secondary)
                }
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12)], spacing: 12) {
                    ForEach(available) { harness in sourceCard(harness) }
                }
            }
        }
    }

    private func sourceCard(_ harness: HarnessInfo) -> some View {
        let selected = model.wizard.sourceID == harness.id
        return Button {
            model.wizardSelectSource(harness.id)
        } label: {
            HStack(spacing: 12) {
                HarnessLogoView(harnessID: harness.id, size: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(harness.name).font(.headline)
                    Text("\(harness.sessionCount) 个会话 · \(harness.recentText)")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if selected { Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint) }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassSelectionCard(selected: selected, cornerRadius: 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .hoverLift()
        .animation(Motion.quick, value: selected)
    }

    // MARK: Step 2 — sessions (multi-select + preview)
    private var sessionStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            stepHeader("选择会话", detail: "支持多选与批量选择。切换筛选不会清除已选项；切换来源会清空选择。")
            if let error = model.wizard.errorText {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
            }
            sessionToolbar
            HStack(alignment: .top, spacing: 12) {
                sessionList.frame(minWidth: 440)
                sessionPreviewPane.frame(width: 330)
            }
        }
    }

    private var sessionToolbar: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.circle").foregroundStyle(model.wizardSelectedCount > 0 ? Color.accentColor : .secondary)
            Text("已选 \(model.wizardSelectedCount) / 共 \(model.wizardFilteredCount)（筛选后）").font(.callout)
            Divider().frame(height: 14)
            Button("全选当前筛选") { model.selectAllWizardFiltered() }
                .controlSize(.small)
                .help("⌘A")
            Button("反选") { model.invertWizardSelection() }
                .controlSize(.small)
            Button("取消") { model.clearWizardSelection() }
                .controlSize(.small)
                .disabled(model.wizardSelectedCount == 0)
            Menu("快速选择") {
                Button("最近 10 个") { model.selectRecentWizardSessions(10) }
                Button("最近 50 个") { model.selectRecentWizardSessions(50) }
                Button("全部当前筛选") { model.selectAllWizardCurrent() }
            }
            .frame(width: 110)
            Spacer()
            Text("Shift+点击连续选择 · 已选项跨步骤保留").font(.caption2).foregroundStyle(.secondary)
        }
        .padding(8)
        .background(Color.secondary.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var sessionList: some View {
        CardBox(title: "会话列表", systemImage: "list.bullet.rectangle") {
            VStack(alignment: .leading, spacing: 6) {
                SearchField(placeholder: "搜索标题 / 路径 / 模型…",
                            text: Binding(get: { model.wizard.searchInput },
                                          set: { model.setWizardSearchInput($0) }),
                            focusRequest: model.wizard.step == 2 ? model.searchFocusRequest : -1)
                    .frame(height: 26)
                if model.wizard.sessions.isEmpty {
                    EmptyHint(text: "这个工具暂时没有可读取的会话")
                } else {
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            ForEach(model.wizardFilteredSessions) { session in
                                wizardSessionRow(session)
                                    .id(session.id)
                                    .onAppear {
                                        if session.id == model.wizardFilteredSessions.last?.id {
                                            model.loadMoreWizard()
                                        }
                                    }
                                Divider()
                            }
                            if model.wizardHasMore {
                                Button {
                                    model.loadMoreWizard()
                                } label: {
                                    Label("加载更多（剩余 \(model.wizardFilteredCount - model.wizardFilteredSessions.count)）",
                                          systemImage: "arrow.down.circle")
                                }
                                .controlSize(.small)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 8)
                            }
                        }
                    }
                    .frame(maxHeight: 330)
                    .animation(Motion.list, value: model.wizardFilteredSessions.count)
                }
            }
        }
    }

    private func wizardSessionRow(_ session: SessionRow) -> some View {
        let selected = model.wizard.selectedIDs.contains(session.id)
        let focused = model.wizard.previewFocusID == session.id
        return HStack(spacing: 8) {
            Button {
                model.toggleWizardSelection(session, shift: shiftPressed)
            } label: {
                Image(systemName: selected ? "checkmark.square.fill" : "square")
                    .font(.system(size: 16))
                    .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                    .scaleEffect(selected && !Motion.reduceMotion ? 1.08 : 1)
                    .animation(Motion.quick, value: selected)
            }
            .buttonStyle(.plain)
            .help("选择会话（Shift+点击连续选择）")
            VStack(alignment: .leading, spacing: 1) {
                Text(session.displayTitle).font(.callout).lineLimit(1)
                Text("\(Fmt.time(session.createdAtMs)) · \(Fmt.shortPath(session.cwd, limit: 46))")
                    .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            if let lines = session.lines {
                Text("\(lines) 行").font(.caption2.monospaced()).foregroundStyle(.secondary)
            }
            Button {
                Task { await model.focusWizardPreview(session) }
            } label: {
                Image(systemName: "eye")
            }
            .buttonStyle(.borderless)
            .help("预览此会话")
        }
        .padding(.vertical, 4)
        .padding(.horizontal, 4)
        .background(focused ? Color.accentColor.opacity(0.08) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .onTapGesture { model.toggleWizardSelection(session, shift: shiftPressed) }
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    private var sessionPreviewPane: some View {
        CardBox(title: "会话预览", systemImage: "doc.text.magnifyingglass") {
            if let id = model.wizard.previewFocusID ?? model.wizard.selectedIDs.first,
               let preview = model.wizard.previewCache[id] {
                VStack(alignment: .leading, spacing: 6) {
                    if let source = model.wizard.sourceID,
                       let focused = model.wizard.sessions.first(where: { $0.id == id }) {
                        Button {
                            model.openSessionDetail(source: source, session: focused)
                        } label: {
                            Label("查看完整详情", systemImage: "doc.text.magnifyingglass")
                        }
                        .controlSize(.small)
                    }
                    Text(preview.title).font(.headline).lineLimit(2)
                    InfoRow(label: "项目路径", value: preview.cwd ?? "—", mono: true)
                    InfoRow(label: "模型", value: preview.model ?? "—")
                    InfoRow(label: "消息数", value: Fmt.int(preview.messageCount))
                    InfoRow(label: "工具调用", value: Fmt.int(preview.toolCallCount))
                    if let first = preview.firstUserMessage, !first.isEmpty {
                        Text("首条用户消息").font(.caption).foregroundStyle(.secondary)
                        Text(first).font(.caption).lineLimit(6)
                            .padding(8)
                            .background(Color(nsColor: .textBackgroundColor).opacity(0.5))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    if !preview.recentMessages.isEmpty {
                        Text("最近消息").font(.caption).foregroundStyle(.secondary)
                        ForEach(Array(preview.recentMessages.prefix(4).enumerated()), id: \.offset) { _, message in
                            Text(message).font(.caption2).lineLimit(2).foregroundStyle(.secondary)
                        }
                    }
                }
            } else if model.wizard.previewLoadingID != nil {
                VStack(spacing: 8) {
                    ProgressView()
                    Text("正在读取会话摘要…").font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 120)
            } else {
                EmptyHint(icon: "eye", text: "选中会话后可查看摘要")
            }
        }
    }

    // MARK: Step 3 — target
    private var targetStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            stepHeader("选择目标", detail: "默认直接写入目标工具自己的会话库；安装位置自动检测。")
            if model.installTargets.isEmpty {
                CardBox(title: "没有支持直接迁移的工具", systemImage: "exclamationmark.triangle") {
                    Text("当前检测到的工具都不支持写入会话库。你可以在下方选择「仅导出到文件夹」，或更新组件后重试。")
                        .foregroundStyle(.secondary)
                }
            }
            VStack(spacing: 8) {
                ForEach(model.installTargets) { harness in
                    installTargetCard(harness)
                }
                exportTargetCard
            }
        }
    }

    private func installTargetCard(_ harness: HarnessInfo) -> some View {
        let selected = model.wizard.targetID == harness.id && model.wizard.options.mode == .install
        return Button {
            model.setWizardTarget(harness.id)
            model.wizard.options.mode = .install
        } label: {
            HStack(spacing: 12) {
                HarnessLogoView(harnessID: harness.id, size: 34)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(harness.name).font(.headline)
                        StatusPill(text: harness.installExperimental ? "实验性" : "已验证",
                                   color: harness.installExperimental ? .orange : .green)
                        if !harness.detected { StatusPill(text: "未检测到", color: .secondary) }
                    }
                    if !harness.storePath.isEmpty {
                        Text("将写入：\(harness.storePath)")
                            .font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                    }
                    if let how = harness.howToSee, !how.isEmpty {
                        Text(how).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                Spacer()
                if selected { Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint) }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Color.accentColor.opacity(0.10) : Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12)
                .strokeBorder(selected ? Color.accentColor : Color.secondary.opacity(0.18), lineWidth: selected ? 2 : 1))
            .opacity(harness.detected ? 1 : 0.6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .hoverLift(scale: 1.006, shadow: 0.08)
        .animation(Motion.quick, value: selected)
    }

    private var exportTargetCard: some View {
        let selected = model.wizard.options.mode == .export
        return Button {
            model.setWizardTarget("atif")
            model.wizard.options.mode = .export
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "square.and.arrow.up")
                    .font(.title3)
                    .frame(width: 30)
                    .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text("仅导出到文件夹").font(.headline)
                        StatusPill(text: "高级", color: .blue)
                    }
                    Text("导出标准交换文件，不写入任何工具会话库；适合备份或跨工具使用。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if selected { Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint) }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Color.accentColor.opacity(0.10) : Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12)
                .strokeBorder(selected ? Color.accentColor : Color.secondary.opacity(0.18), lineWidth: selected ? 2 : 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .hoverLift(scale: 1.006, shadow: 0.08)
        .animation(Motion.quick, value: selected)
    }

    // MARK: Step 4 — options
    private var optionsStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            stepHeader("迁移选项", detail: "默认直接写入目标工具的会话库，无需先选择输出文件夹。")
            if model.wizard.options.mode == .install {
                let info = model.harnessInfo(model.wizard.targetID)
                CardBox(title: "写入位置", systemImage: "internaldrive") {
                    InfoRow(label: "目标", value: info?.name ?? model.harnessName(model.wizard.targetID))
                    if let store = info?.storePath, !store.isEmpty {
                        InfoRow(label: "会话库", value: store, mono: true)
                    }
                    if let how = info?.howToSee, !how.isEmpty { InfoRow(label: "查看方式", value: how) }
                    Text("迁移前会自动备份目标侧可能被覆盖的文件；重复会话默认跳过，不覆盖。")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                CardBox(title: "原始会话", systemImage: "arrow.uturn.backward.circle") {
                    Toggle("迁移成功后移出原始会话（可恢复）", isOn: Binding(
                        get: { model.wizard.options.sessionMode == .move },
                        set: { value in
                            if value { model.showMoveConfirm = true }
                            else { Motion.run(Motion.quick) { model.wizard.options.sessionMode = .keep } }
                        }
                    ))
                    Text(model.wizard.options.sessionMode == .move
                         ? "会重命名为同目录 .migrated-<时间>.bak（不删除），可在结果页/历史中恢复。"
                         : "默认保留原始会话，源文件不做任何改动。")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
            CardBox(title: "项目路径处理", systemImage: "folder.badge.gearshape") {
                Toggle("保留会话原本的项目路径（推荐）", isOn: Binding(
                    get: { model.wizard.options.keepOriginalCwd },
                    set: { model.wizard.options.keepOriginalCwd = $0 }
                ))
                if !model.wizard.options.keepOriginalCwd {
                    TextField("统一使用这个项目路径（例如 ~/Projects/demo）", text: Binding(
                        get: { model.wizard.options.customCwd },
                        set: { model.wizard.options.customCwd = $0 }
                    ))
                    .textFieldStyle(.roundedBorder)
                }
                Text("当原项目路径在本机不存在时，部分工具需要你指定一个兜底路径。")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            CardBox(title: "内容选项", systemImage: "slider.horizontal.3") {
                Toggle("包含系统提示词（会话最开头的环境说明）", isOn: Binding(
                    get: { model.wizard.options.keepSystem },
                    set: { model.setWizardKeepSystem($0) }
                ))
                if model.wizard.targetID == "dsh" && model.wizard.options.mode == .install {
                    Toggle("迁移后注册到对应项目（重启 DeepSeek Harness 后可见）", isOn: Binding(
                        get: { model.wizard.options.registerToProject },
                        set: { model.setWizardRegister($0) }
                    ))
                }
            }
            DisclosureGroup("高级选项") {
                VStack(alignment: .leading, spacing: 8) {
                    Toggle("仅导出到文件夹（不写入目标会话库）", isOn: Binding(
                        get: { model.wizard.options.mode == .export },
                        set: { value in
                            Motion.run(Motion.quick) {
                                model.wizard.options.mode = value ? .export : .install
                            }
                        }
                    ))
                    if model.wizard.options.mode == .export {
                        HStack {
                            Text(model.wizard.options.outputDir.isEmpty ? model.outputDir : model.wizard.options.outputDir)
                                .font(.callout.monospaced()).lineLimit(1)
                            Spacer()
                            Button("选择文件夹…") {
                                model.chooseOutputDirectory()
                                model.wizard.options.outputDir = model.outputDir
                            }
                        }
                    }
                    Toggle("目标已存在会话时覆盖（会自动备份，默认关闭）", isOn: Binding(
                        get: { model.wizard.options.overwrite },
                        set: { model.wizard.options.overwrite = $0 }
                    ))
                    Text("默认不覆盖：目标已有同 ID 会话时会跳过并在结果中标记。")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                .padding(.top, 6)
            }
            Text("开始迁移前会显示确认摘要，可随时取消。")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    // MARK: Step 5 — execute + results
    private var executionStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            stepHeader(model.wizard.finished ? "迁移完成" : "正在迁移",
                       detail: model.wizard.finished ? "以下是每个会话的结果。" : "请不要关闭窗口，迁移完成后会显示结果。")
            if model.wizard.finished, let report = model.wizard.report {
                resultContent(report)
            } else {
                CardBox(title: "迁移进度", systemImage: "arrow.triangle.2.circlepath") {
                    HStack(spacing: 10) {
                        ProgressView().controlSize(.small)
                        Text(model.wizard.progressText).font(.callout).foregroundStyle(.secondary)
                    }
                    ProgressBar(value: model.wizard.progressValue)
                        .shimmer()
                    Text("共 \(model.wizard.selectedIDs.count) 个会话").font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func resultContent(_ report: MigrationReport) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            CardBox(title: "迁移结果", systemImage: "checkmark.seal") {
                let skipped = report.items.filter(\.skipped).count
                let moved = report.items.filter(\.sourceMoved).count
                HStack(spacing: 12) {
                    StatusPill(text: "成功 \(report.okCount)", color: .green)
                    if skipped > 0 { StatusPill(text: "跳过 \(skipped)", color: .orange) }
                    if moved > 0 { StatusPill(text: "移出 \(moved)", color: .purple) }
                    if report.failCount > 0 { StatusPill(text: "失败 \(report.failCount)", color: .red) }
                    Spacer()
                    Text(Fmt.duration(report.elapsed)).font(.caption).foregroundStyle(.secondary)
                }
                InfoRow(label: "来源", value: model.harnessName(report.sourceID))
                InfoRow(label: "目标", value: MigrationTarget.find(report.targetID).title)
                if let info = model.harnessInfo(report.targetID), !info.storePath.isEmpty {
                    InfoRow(label: "会话库", value: info.storePath, mono: true)
                }
                if let info = model.harnessInfo(report.targetID), let how = info.howToSee, !how.isEmpty {
                    Label(how, systemImage: "info.circle").font(.caption2).foregroundStyle(.secondary)
                }
                if let journal = model.wizardJournalPath {
                    HStack {
                        Text("迁移日志：\(Fmt.shortPath(journal, limit: 60))")
                            .font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                        Button("打开日志") { model.revealInFinder(journal) }.controlSize(.small)
                    }
                }
                HStack(spacing: 10) {
                    Button { model.revealInFinder(report.outputDir) } label: {
                        Label("打开输出文件夹", systemImage: "folder")
                    }
                    .opacity(model.wizard.options.mode == .install ? 0 : 1)
                    if model.wizardJournalPath != nil {
                        Button { model.restoreWizardJournal() } label: {
                            Label("恢复被移出的会话", systemImage: "arrow.uturn.backward")
                        }
                    }
                    Button { model.copyWizardSummary() } label: {
                        Label("复制迁移结果", systemImage: "doc.on.doc")
                    }
                    if report.failCount > 0 {
                        Button { Task { await model.retryFailedMigration() } } label: {
                            Label("重试失败项", systemImage: "arrow.clockwise")
                        }
                    }
                }
            }
            CardBox(title: "逐会话结果", systemImage: "list.bullet") {
                VStack(spacing: 0) {
                    ForEach(report.items) { item in
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: item.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                                .foregroundStyle(item.ok ? .green : .red)
                                .font(.system(size: 15))
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.title).font(.callout).lineLimit(2)
                                HStack(spacing: 6) {
                                    if let verify = item.verifyStatus {
                                        StatusPill(text: verify,
                                                   color: verify.contains("通过") ? .green
                                                        : (verify.contains("未") ? .orange : .blue))
                                    }
                                    if !item.lossy.isEmpty { StatusPill(text: "有损 \(item.lossy.count)", color: .orange) }
                                    if !item.warnings.isEmpty { StatusPill(text: "提示 \(item.warnings.count)", color: .secondary) }
                                    if let status = item.installStatus {
                                        StatusPill(text: status, color: item.skipped ? .orange : .blue)
                                    }
                                    if let installed = item.installedPath {
                                        Text(Fmt.shortPath(installed, limit: 60))
                                            .font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                                    }
                                    if item.sourceMoved, let backup = item.sourceBackupPath {
                                        Text("源已移出：\(Fmt.shortPath(backup, limit: 50))")
                                            .font(.caption2).foregroundStyle(.purple).lineLimit(1)
                                    }
                                }
                                if item.skipped, let reason = item.skipReason {
                                    Text(reason).font(.caption2).foregroundStyle(.orange).lineLimit(3)
                                }
                                if let error = item.error {
                                    Text(error).font(.caption2)
                                        .foregroundStyle(item.ok ? .orange : .red)
                                        .lineLimit(3)
                                }
                                if let source = item.sourcePath {
                                    HStack(spacing: 4) {
                                        Text("源文件：\(Fmt.shortPath(source, limit: 60))")
                                            .font(.caption2.monospaced())
                                            .foregroundStyle(.secondary).lineLimit(1)
                                        Button("定位") { model.revealInFinder(source) }
                                            .controlSize(.mini).buttonStyle(.borderless)
                                    }
                                }
                                ForEach(item.lossy.prefix(3), id: \.self) { loss in
                                    Text("· 有损：\(loss)").font(.caption2).foregroundStyle(.orange)
                                }
                            }
                            Spacer()
                        }
                        .padding(.vertical, 5)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                        Divider()
                    }
                }
                .animation(Motion.spring, value: report.items.count)
                if report.hasLossy {
                    Text("「有损」表示目标工具没有完全对应的概念，部分信息被省略；原始会话不受影响。")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func stepHeader(_ title: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.title2.weight(.bold))
            Text(detail).font(.callout).foregroundStyle(.secondary)
        }
        .padding(.bottom, 4)
    }
}
