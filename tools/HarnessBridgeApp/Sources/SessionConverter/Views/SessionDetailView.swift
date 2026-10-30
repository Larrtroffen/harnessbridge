import SwiftUI
import AppKit

// MARK: - Session detail page (product v1.2)
struct SessionDetailView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            topBar
            Divider()
            if model.detailLoading {
                loadingState
            } else if let error = model.detailError {
                errorState(error)
            } else if let detail = model.detail {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            header(detail)
                            statsSection(detail)
                            timelineToolbar(detail)
                            timelineSection(detail)
                        }
                        .padding(20)
                    }
                    .onChange(of: model.detailScrollTarget) { target in
                        guard let target else { return }
                        Motion.run(Motion.spring) { proxy.scrollTo("event-\(target)", anchor: .center) }
                        model.detailScrollTarget = nil
                    }
                }
            } else {
                EmptyHint(text: "暂无详情")
            }
        }
    }

    // MARK: top bar
    private var topBar: some View {
        HStack(spacing: 10) {
            Button {
                model.closeSessionDetail()
            } label: {
                Label("返回", systemImage: "chevron.left")
            }
            .buttonStyle(.borderless)
            Divider().frame(height: 16)
            HarnessLogoView(harnessID: model.detailSource, size: 22)
            Text(model.harnessName(model.detailSource))
                .font(.headline)
            Text("会话详情")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer()
            if let session = model.detailSession {
                Button {
                    model.migrateDetailSession()
                } label: {
                    Label("迁移此会话", systemImage: "arrow.right.circle")
                }
                Button {
                    Task { await model.exportDetailSession() }
                } label: {
                    Label("导出", systemImage: "square.and.arrow.up")
                }
                Button {
                    model.revealDetailSourceFile()
                } label: {
                    Label("源文件", systemImage: "folder")
                }
                Button {
                    model.copyDetailSummary()
                } label: {
                    Label("复制摘要", systemImage: "doc.on.doc")
                }
                .help("复制会话统计摘要")
                Button {
                    _ = session
                } label: { EmptyView() }
                .hidden()
            }
            Button {
                Task { await model.loadSessionDetail() }
            } label: {
                Label("刷新", systemImage: "arrow.clockwise")
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private var loadingState: some View {
        VStack(spacing: 10) {
            ProgressView()
            Text("正在读取会话详情…").foregroundStyle(.secondary)
            Text("大会话可能需要几秒，请稍候").font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func errorState(_ message: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 30))
                .foregroundStyle(.orange)
            Text("读取失败").font(.headline)
            Text(message).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button("重试") { Task { await model.loadSessionDetail() } }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }

    // MARK: header
    private func header(_ detail: SessionDetail) -> some View {
        CardBox {
            HStack(alignment: .top, spacing: 14) {
                HarnessLogoView(harnessID: detail.source, size: 52)
                VStack(alignment: .leading, spacing: 5) {
                    Text(detail.title).font(.title3.weight(.semibold)).lineLimit(3)
                    HStack(spacing: 10) {
                        Label(model.harnessName(detail.source), systemImage: "app.badge")
                        if let modelName = detail.model { Label(modelName, systemImage: "cpu") }
                        if let provider = detail.provider { Text(provider).foregroundStyle(.secondary) }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    HStack(spacing: 10) {
                        if let cwd = detail.cwd {
                            Label(Fmt.shortPath(cwd, limit: 70), systemImage: "folder")
                                .font(.caption2.monospaced())
                                .textSelection(.enabled)
                        }
                        if let created = detail.createdAtMs {
                            Label("创建 \(Fmt.time(created))", systemImage: "calendar")
                                .font(.caption2)
                        }
                        if let updated = detail.updatedAtMs {
                            Label("更新 \(Fmt.time(updated))", systemImage: "clock")
                                .font(.caption2)
                        }
                    }
                    .foregroundStyle(.secondary)
                    HStack(spacing: 6) {
                        if let source = detail.sourceLabel {
                            StatusPill(text: source, color: .blue)
                        }
                        if let evidence = detail.evidenceLevel {
                            EvidenceBadge(evidence: evidence)
                        }
                        if detail.isFallback {
                            StatusPill(text: "摘要模式", color: .orange)
                        }
                        if detail.truncated {
                            StatusPill(text: "内容已截断", color: .orange)
                        }
                    }
                }
                Spacer()
            }
        }
    }

    // MARK: stats
    private func statsSection(_ detail: SessionDetail) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                statCard("消息", value: "\(detail.stats.messages.total)",
                         detail: "用户 \(Fmt.int(detail.stats.messages.user)) · 助手 \(Fmt.int(detail.stats.messages.assistant)) · 工具 \(Fmt.int(detail.stats.messages.tool))")
                statCard("工具调用", value: Fmt.int(detail.stats.toolCalls),
                         detail: "结果 \(Fmt.int(detail.stats.toolResults)) · 失败 \(Fmt.int(detail.stats.toolErrors))",
                         accent: (detail.stats.toolErrors ?? 0) > 0 ? .red : nil)
                tokenCard(detail.stats.usage)
                statCard("会话时长", value: detail.durationText,
                         detail: timelineRangeText(detail))
            }
            if !detail.toolUsageTop.isEmpty {
                CardBox(title: "工具使用 Top", systemImage: "wrench.and.screwdriver") {
                    HStack(spacing: 8) {
                        ForEach(detail.toolUsageTop) { tool in
                            HStack(spacing: 4) {
                                Text(tool.name).font(.caption.monospaced())
                                Text("\(tool.count)").font(.caption2.monospaced())
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Color.accentColor.opacity(0.12))
                            .clipShape(Capsule())
                        }
                        Spacer()
                    }
                }
            }
        }
    }

    private func statCard(_ title: String, value: String, detail: String,
                          accent: Color? = nil) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(value)
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .foregroundStyle(accent ?? .primary)
            Text(title).font(.caption.weight(.semibold))
            Text(detail).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.secondary.opacity(0.16)))
    }

    private func tokenCard(_ usage: TokenUsage) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            if usage.available, usage.hasAnyValue {
                AnimatedNumber(value: usage.totalTokens ?? totalOf(usage),
                               font: .system(size: 24, weight: .bold, design: .rounded))
                
                Text("Token 用量").font(.caption.weight(.semibold))
                Text("in \(tokenCompact(usage.inputTokens)) · out \(tokenCompact(usage.outputTokens)) · cache \(tokenCompact(usage.cacheReadTokens))")
                    .font(.caption2).foregroundStyle(.secondary).lineLimit(2)
            } else {
                Text("未提供")
                    .font(.system(size: 20, weight: .bold, design: .rounded))
                    .foregroundStyle(.secondary)
                Text("Token 用量").font(.caption.weight(.semibold))
                Text("该工具未提供 Token 统计").font(.caption2).foregroundStyle(.orange).lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.secondary.opacity(0.16)))
    }

    private func totalOf(_ usage: TokenUsage) -> Int {
        (usage.inputTokens ?? 0) + (usage.outputTokens ?? 0)
    }

    private func tokenCompact(_ value: Int?) -> String {
        guard let value, value > 0 else { return "—" }
        if value < 1000 { return "\(value)" }
        if value < 1_000_000 { return String(format: "%.1fk", Double(value) / 1000) }
        return String(format: "%.2fM", Double(value) / 1_000_000)
    }

    private func timelineRangeText(_ detail: SessionDetail) -> String {
        guard let first = detail.stats.firstTs, let last = detail.stats.lastTs, last > first else {
            return "时间信息不完整"
        }
        return "首条 \(Fmt.time(first)) · 末条 \(Fmt.time(last))"
    }

    // MARK: timeline toolbar
    private func timelineToolbar(_ detail: SessionDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text("时间线").font(.headline)
                Text(truncationSummary(detail))
                    .font(.caption).foregroundStyle(.secondary)
                Text("· 显示 \(model.detailFilteredEvents.count) / 共 \(model.detailFilteredTotalCount) 条匹配")
                    .font(.caption2).foregroundStyle(.secondary)
                Text("· ⌘↑/⌘↓ 跳转首末工具 · Esc 返回")
                    .font(.caption2).foregroundStyle(.secondary)
                if detail.isFallback {
                    StatusPill(text: "时间线需更新后端", color: .orange)
                }
                Spacer()
                Button {
                    model.jumpToTool(first: true)
                } label: {
                    Label("第一个工具", systemImage: "arrow.up.to.line")
                }
                .controlSize(.small)
                Button {
                    model.jumpToTool(first: false)
                } label: {
                    Label("最后一个工具", systemImage: "arrow.down.to.line")
                }
                .controlSize(.small)
            }
            HStack(spacing: 8) {
                ForEach([("all", "全部"), ("user", "用户"), ("assistant", "助手"),
                         ("thinking", "思考"), ("tool", "工具"), ("error", "错误")], id: \.0) { item in
                    Button {
                        model.setDetailKindFilter(item.0)
                    } label: {
                        Text(item.1)
                            .font(.caption)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 4)
                            .background(model.detailKindFilter == item.0
                                        ? Color.accentColor.opacity(0.18) : Color.secondary.opacity(0.10))
                            .foregroundStyle(model.detailKindFilter == item.0 ? Color.accentColor : Color.primary)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
                SearchField(placeholder: "在会话内搜索…",
                            text: Binding(get: { model.detailSearch },
                                          set: { model.setDetailSearchInput($0) }),
                            focusRequest: model.searchFocusRequest)
                    .frame(width: 230, height: 24)
            }
            if let notes = detail.warnings.isEmpty ? nil : detail.warnings {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(notes.prefix(3), id: \.self) { warning in
                        Text("• \(warning)").font(.caption2).foregroundStyle(.orange)
                    }
                }
            }
        }
    }

    // MARK: timeline
    private func timelineSection(_ detail: SessionDetail) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            let groups = model.detailGroups
            if groups.isEmpty && (model.detailFiltering || model.detailGrouping) {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("正在整理时间线…").font(.caption).foregroundStyle(.secondary)
                }
                .padding(.vertical, 8)
            } else if groups.isEmpty {
                CardBox {
                    Text(model.detailSearch.isEmpty && model.detailKindFilter == "all"
                         ? "该会话没有可显示的时间线内容。"
                         : "没有匹配的事件，试试切换筛选或清空搜索。")
                        .foregroundStyle(.secondary)
                }
            } else {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(groups) { group in
                        sectionHeader(group)
                        ForEach(group.events) { event in
                            eventRow(event, detail: detail)
                                .id("event-\(event.index)")
                        }
                    }
                    if model.detailHasMore {
                        Button {
                            model.loadMoreDetailEvents()
                        } label: {
                            Label("加载更多事件（剩余 \(model.detailFilteredTotalCount - model.detailFilteredEvents.count)）",
                                  systemImage: "arrow.down.circle")
                        }
                        .controlSize(.small)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                    }
                }
                .animation(Motion.list, value: model.detailVisibleEvents)
                .animation(Motion.spring, value: model.detailKindFilter)
            }
        }
    }

    private func sectionHeader(_ group: DetailGroup) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "circle.grid.2x2")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(group.title).font(.callout.weight(.semibold))
            Text(group.subtitle).font(.caption2).foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(Color.secondary.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private func eventRow(_ event: DetailEvent, detail: SessionDetail) -> some View {
        let expanded = model.detailExpanded.contains(event.index)
        let color = eventColor(event)
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Circle().fill(color).frame(width: 7, height: 7)
                if event.kind == "tool_result" {
                    Text("↳").font(.caption).foregroundStyle(.secondary)
                }
                StatusPill(text: event.kindLabel, color: color)
                if let role = event.role, !role.isEmpty, role != event.kind {
                    Text(role).font(.caption2).foregroundStyle(.secondary)
                }
                if let tool = event.tool, let name = tool.name, !name.isEmpty {
                    Text(name).font(.caption.monospaced())
                        .padding(.horizontal, 6).padding(.vertical, 1)
                        .background(Color.secondary.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                }
                if let callID = event.tool?.callID, !callID.isEmpty {
                    Text("#\(callID.prefix(8))").font(.caption2.monospaced()).foregroundStyle(.secondary)
                }
                if event.isError {
                    StatusPill(text: "失败", color: .red)
                }
                Spacer()
                if let ts = event.ts {
                    Text(Fmt.time(ts)).font(.caption2).foregroundStyle(.secondary)
                }
                Text("#\(event.index + 1)").font(.caption2.monospaced()).foregroundStyle(.secondary.opacity(0.7))
            }
            let displayText = event.text.trimmingCharacters(in: .whitespacesAndNewlines)
            if displayText.isEmpty {
                Text("（无文本内容）").font(.caption).foregroundStyle(.secondary)
            } else {
                Text(displayText)
                    .font(.callout)
                    .lineLimit(expanded ? nil : 4)
                    .textSelection(.enabled)
                    .foregroundStyle(event.isError ? .red : .primary)
                if displayText.count > 160 {
                    Button(expanded ? "收起" : "展开全文") {
                        Motion.run(Motion.spring) { model.toggleDetailEvent(event.index) }
                    }
                    .controlSize(.mini)
                    .buttonStyle(.borderless)
                }
            }
        }
        .padding(10)
        .background(event.isError ? Color.red.opacity(0.06) : Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8)
            .strokeBorder(event.isError ? Color.red.opacity(0.35) : Color.secondary.opacity(0.12)))
        .animation(Motion.spring, value: expanded)
    }

    private func truncationSummary(_ detail: SessionDetail) -> String {
        if let total = detail.stats.eventsTotal, total > detail.timeline.count {
            return "显示 \(detail.timeline.count) / 共 \(total) 个事件（已截断）"
        }
        return "\(detail.timeline.count) 个事件"
    }

    private func eventColor(_ event: DetailEvent) -> Color {
        switch event.kind {
        case "user": return .blue
        case "assistant": return .green
        case "thinking": return .purple
        case "tool_call": return .orange
        case "tool_result": return event.isError ? .red : .teal
        case "system": return .gray
        case "compaction": return .brown
        default: return .secondary
        }
    }
}
