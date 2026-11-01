import SwiftUI
import AppKit

/// One-click migrate-all page (v1.4): target → sources/filters → plan → execute → result.
struct MigrateAllView: View {
    @EnvironmentObject var model: AppModel

    private var state: MigrateAllState { model.migrateAll }

    var body: some View {
        VStack(spacing: 0) {
            StepIndicator(steps: ["选目标", "选来源", "预览计划", "执行结果"], current: stepIndex)
                .padding(.horizontal, 20).padding(.vertical, 4)
                .animation(Motion.spring, value: state.step)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    content
                        .id(state.step)
                        .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity),
                                                removal: .move(edge: .leading).combined(with: .opacity)))
                }
                .padding(20)
            }
            .animation(Motion.spring, value: state.step)
            Divider()
            footer
        }
        .alert("确认一键迁移？", isPresented: Binding(
            get: { model.showMigrateAllConfirm },
            set: { model.showMigrateAllConfirm = $0 }
        )) {
            Button("取消", role: .cancel) { model.showMigrateAllConfirm = false }
            Button("开始迁移") { model.runMigrateAll() }
        } message: {
            Text(migrateConfirmMessage)
        }
        .alert("确认移出原始会话？", isPresented: Binding(
            get: { model.showMoveConfirm },
            set: { model.showMoveConfirm = $0 }
        )) {
            Button("取消", role: .cancel) { model.showMoveConfirm = false }
            Button("移出（可恢复）", role: .destructive) { model.confirmMoveMode() }
        } message: {
            Text("迁移成功后会把这些来源会话重命名为 .migrated-<时间>.bak（同一目录，不删除），可在结果页或历史中用「恢复被移出的会话」还原。")
        }
    }

    private var stepIndex: Int {
        switch state.step {
        case 1: return 1
        case 2: return 2
        case 3: return 3
        case 4: return 4
        default: return 4
        }
    }

    @ViewBuilder
    private var content: some View {
        switch state.step {
        case 1: targetStep
        case 2: sourceStep
        case 3: planStep
        case 4: executingStep
        default: resultStep
        }
    }

    private var footer: some View {
        HStack(spacing: 10) {
            if state.step == 1 {
                Button("返回首页") { model.page = .home }
            } else if state.step == 2 {
                Button("上一步") { model.migrateAll.step = 1 }
            } else if state.step == 3 {
                Button("上一步") { migrateAllBackToSources() }
            }
            Spacer()
            Text("目标工具重启后可见迁移的会话").font(.caption2).foregroundStyle(.secondary)
            if state.step == 2 {
                if state.buildingPlan {
                    ProgressView().controlSize(.small)
                    Text("正在生成迁移计划…").font(.caption).foregroundStyle(.secondary)
                }
                Button("预览计划") { model.previewMigrateAllPlan() }
                    .buttonStyle(GlassProminentButtonStyle())
                    .disabled(!state.sources.contains(where: \.selected) || state.buildingPlan)
            } else if state.step == 3 {
                Button("开始迁移") { model.showMigrateAllConfirm = true }
                    .buttonStyle(GlassProminentButtonStyle())
            } else if state.step == 4 {
                Button("取消", role: .destructive) { model.cancelMigrateAll() }
                    .disabled(state.cancelled)
                Text(L(state.progressText)).font(.caption).foregroundStyle(.secondary)
            } else if state.step == 5 {
                if state.journalPath != nil {
                    Button { model.restoreMigrateAllJournal() } label: {
                        Label("恢复被移出的会话", systemImage: "arrow.uturn.backward")
                    }
                }
                Button("返回首页") { model.page = .home }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 10)
    }

    private func migrateAllBackToSources() {
        model.migrateAll.step = 2
        model.migrateAll.plan = nil
    }

    // MARK: step 1 target
    private var targetStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            header("选择目标工具", "一键把其他所有工具的会话迁移到这个工具。")
            if model.installTargets.isEmpty {
                CardBox(title: "没有支持直接迁移的工具", systemImage: "exclamationmark.triangle") {
                    Text("当前检测到的工具都不支持写入会话库，请先更新组件，或使用普通「迁移会话」的仅导出模式。")
                        .foregroundStyle(.secondary)
                }
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 12)], spacing: 12) {
                    ForEach(model.installTargets) { harness in
                        let selected = state.targetID == harness.id
                        Button {
                            model.selectMigrateAllTarget(harness.id)
                        } label: {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack(spacing: 10) {
                                    HarnessLogoView(harnessID: harness.id, size: 34)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(harness.name).font(.headline)
                                        Text("\(harness.sessionCount) 个会话")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if selected { Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint) }
                                }
                                if !harness.storePath.isEmpty {
                                    Text("写入：\(harness.storePath)")
                                        .font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                                }
                                if let how = harness.howToSee, !how.isEmpty {
                                    Text(L(how)).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                                }
                            }
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .glassSelectionCard(selected: selected, cornerRadius: 12)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .hoverLift(scale: 1.006, shadow: 0.08)
                    }
                }
                VStack(alignment: .leading, spacing: 4) {
                    Button("下一步：选择来源") {
                        model.refreshMigrateAllSources()
                        model.migrateAll.step = 2
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(state.targetID.isEmpty)
                    if state.targetID.isEmpty {
                        Text("请先选择上方目标工具").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    // MARK: step 2 sources + filters
    private var sourceStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            header("选择来源与筛选", "默认选择其他所有有会话的工具；可排除来源、限制最近天数或条数。")
            CardBox(title: "来源工具", systemImage: "square.stack.3d.up") {
                HStack {
                    Button("全选") { model.migrateAllSetAllSources(true) }.controlSize(.small)
                    Button("全不选") { model.migrateAllSetAllSources(false) }.controlSize(.small)
                    Spacer()
                    Text(L("目标：\(model.harnessName(state.targetID))")).font(.caption).foregroundStyle(.secondary)
                }
                if state.sources.isEmpty {
                    Text("没有其他工具包含会话。").foregroundStyle(.secondary)
                } else {
                    ForEach(state.sources) { source in
                        HStack(spacing: 10) {
                            Button {
                                model.toggleMigrateAllSource(source.id)
                            } label: {
                                Image(systemName: source.selected ? "checkmark.square.fill" : "square")
                                    .font(.system(size: 16))
                                    .foregroundStyle(source.selected ? Color.accentColor : .secondary)
                            }
                            .buttonStyle(.plain)
                            HarnessLogoView(harnessID: source.id, size: 20)
                            Text(source.name).font(.callout)
                            Spacer()
                            Text(L10n.sessions(source.sessionCount)).font(.caption).foregroundStyle(.secondary)
                            if let recent = source.recentAtMs {
                                Text("最近 \(Fmt.time(recent))").font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 3)
                        .contentShape(Rectangle())
                        .onTapGesture { model.toggleMigrateAllSource(source.id) }
                    }
                }
            }
            CardBox(title: "筛选", systemImage: "line.3.horizontal.decrease.circle") {
                HStack(spacing: 12) {
                    Text("时间范围")
                    Picker("", selection: Binding(get: { state.sinceDays }, set: { model.migrateAll.sinceDays = $0 })) {
                        Text("全部").tag(0)
                        Text("最近 1 天").tag(1)
                        Text("最近 7 天").tag(7)
                        Text("最近 30 天").tag(30)
                    }
                    .frame(width: 150)
                    Text("最多会话数")
                    TextField("不限制", text: Binding(get: { state.limitText },
                                                       set: { model.migrateAll.limitText = $0 }))
                        .textFieldStyle(.roundedBorder).frame(width: 110)
                }
                Text(L("会话总数：\(state.sources.filter(\.selected).reduce(0) { $0 + $1.sessionCount })（预览计划会按实际读取结果计算）"))
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if let error = state.planError {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
            }
            if state.buildingPlan {
                HStack(spacing: 8) { ProgressView().controlSize(.small); Text("正在生成计划…").foregroundStyle(.secondary) }
            }
        }
    }

    // MARK: step 3 plan
    private var planStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            header("预览迁移计划", "确认后才会写入目标工具的会话库。")
            if let plan = state.plan {
                CardBox(title: "计划摘要", systemImage: "doc.text.magnifyingglass") {
                    InfoRow(label: "目标", value: plan.targetName)
                    if let store = plan.targetStorePath { InfoRow(label: "写入位置", value: store, mono: true) }
                    InfoRow(label: "会话总数", value: "\(plan.totalSessions)")
                    InfoRow(label: "模式", value: state.sessionMode == .move ? "移出原始会话（可恢复）" : "保留原始会话")
                    if let since = plan.sinceDays { InfoRow(label: "时间范围", value: "最近 \(since) 天") }
                    if let limit = plan.limit { InfoRow(label: "上限", value: "\(limit) 个") }
                    if let skip = plan.skippedEstimate {
                        InfoRow(label: "预计跳过", value: "\(skip) 个（目标已存在同 ID，将跳过）")
                    }
                    if let how = plan.howToSee, !how.isEmpty { InfoRow(label: "查看方式", value: how) }
                }
                CardBox(title: "原始会话", systemImage: "arrow.uturn.backward.circle") {
                    Toggle("迁移成功后移出原始会话（可恢复）", isOn: Binding(
                        get: { state.sessionMode == .move },
                        set: { value in
                            if value { model.showMoveConfirm = true }
                            else { Motion.run(Motion.quick) { model.migrateAll.sessionMode = .keep } }
                        }
                    ))
                    Text("默认保留原始会话。移出会重命名为同目录 `.migrated-<时间>.bak`（不删除），可在结果页恢复。")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                Text("写入目标工具会话库前会二次确认；重复会话默认跳过，不覆盖。")
                    .font(.caption2).foregroundStyle(.secondary)
            } else {
                Text("请先预览计划").foregroundStyle(.secondary)
            }
        }
    }

    // MARK: step 4 executing
    private var executingStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            header("正在迁移", "请保持窗口打开；取消后已完成的会话会保留。")
            CardBox(title: "进度", systemImage: "arrow.triangle.2.circlepath") {
                ProgressBar(value: state.progressValue).shimmer()
                Text(L(state.progressText)).font(.callout).foregroundStyle(.secondary).lineLimit(2)
                if state.cancelled {
                    Text("正在停止后端进程；已完成项与迁移日志会保留…")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
        }
    }

    // MARK: step 5 result
    private var resultStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            header(state.cancelled ? "已停止（部分完成）" : "迁移完成",
                   state.cancelled
                   ? "后端进程已终止；下面只保留已完成项，迁移日志已保留，可恢复被移出的源会话。"
                   : "迁移结果如下。")
            if let report = state.report {
                CardBox(title: "汇总", systemImage: "checkmark.seal") {
                    HStack(spacing: 10) {
                        StatusPill(text: "成功 \(report.okCount)", color: .green)
                        if report.failCount > 0 { StatusPill(text: "失败 \(report.failCount)", color: .red) }
                        if report.skippedCount > 0 { StatusPill(text: "跳过 \(report.skippedCount)", color: .orange) }
                        if report.movedCount > 0 { StatusPill(text: "移出 \(report.movedCount)", color: .purple) }
                        Spacer()
                        Text(Fmt.duration(report.elapsed)).font(.caption).foregroundStyle(.secondary)
                    }
                    InfoRow(label: "目标", value: report.plan.targetName)
                    if let store = report.plan.targetStorePath { InfoRow(label: "写入位置", value: store, mono: true) }
                    if let how = report.plan.howToSee, !how.isEmpty {
                        Label(how, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary)
                    }
                    if let journal = state.journalPath {
                        HStack {
                            Text("迁移日志：\(Fmt.shortPath(journal, limit: 60))")
                                .font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                            Button("打开日志") { model.revealInFinder(journal) }.controlSize(.small)
                        }
                    } else if report.movedCount > 0 {
                        Text("未生成可恢复日志：请到原会话目录查找 .migrated-*.bak 手动恢复。")
                            .font(.caption2).foregroundStyle(.orange)
                    }
                }
                CardBox(title: "逐会话结果", systemImage: "list.bullet") {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(report.items) { item in
                                HStack(alignment: .top, spacing: 8) {
                                    Image(systemName: item.ok ? (item.skipped ? "arrow.right.circle" : "checkmark.circle.fill")
                                                              : "xmark.circle.fill")
                                        .foregroundStyle(item.ok ? (item.skipped ? .orange : .green) : .red)
                                        .font(.caption)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(item.title).font(.caption).lineLimit(2)
                                        HStack(spacing: 6) {
                                            if let status = item.installStatus { Text(L(status)).font(.caption2).foregroundStyle(.secondary) }
                                            if item.skipped, let reason = item.skipReason {
                                                Text(L(reason)).font(.caption2).foregroundStyle(.orange)
                                            }
                                            if let error = item.error {
                                                Text(L(error)).font(.caption2)
                                                    .foregroundStyle(item.ok ? .orange : .red)
                                                    .lineLimit(3)
                                            }
                                            if let source = item.sourcePath {
                                                HStack(spacing: 4) {
                                                    Text(L("源：\(Fmt.shortPath(source, limit: 60))"))
                                                        .font(.caption2.monospaced())
                                                        .foregroundStyle(.secondary).lineLimit(1)
                                                    Button("定位") { model.revealInFinder(source) }
                                                        .controlSize(.mini).buttonStyle(.borderless)
                                                }
                                            }
                                        }
                                    }
                                    Spacer()
                                }
                            }
                        }
                    }
                    .frame(maxHeight: 300)
                }
            }
        }
    }

    private var migrateConfirmMessage: String {
        guard let plan = state.plan else { return "" }
        var lines = [
            "来源：\(plan.sources.filter(\.selected).map(\.name).joined(separator: "、"))",
            "会话数：\(plan.totalSessions)",
            "目标：\(plan.targetName)",
            "写入位置：\(plan.targetStorePath ?? "目标工具会话库")",
            "原始会话：\(state.sessionMode == .move ? "移出（可恢复）" : "保留")",
        ]
        if let skip = plan.skippedEstimate, skip > 0 {
            lines.append("预计跳过：\(skip) 个（目标已存在同 ID）")
        }
        lines.append("开始后会写入目标工具的真实会话库；重复会话默认跳过。")
        return lines.joined(separator: "\n")
    }

    private func header(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(L(title)).font(.title2.weight(.bold))
            Text(L(detail)).font(.callout).foregroundStyle(.secondary)
        }
        .padding(.bottom, 4)
    }
}
