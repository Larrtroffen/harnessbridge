import SwiftUI

/// Technical tools for advanced users / diagnostics. Product terminology such as
/// ATIF / IR / CLI is allowed here (and only here + logs/about).
struct AdvancedToolsView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("高级工具").font(.title2.weight(.bold))
                    Text("面向排查与验证的原始工具。普通迁移请使用「迁移会话」。")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                Picker("", selection: $model.advancedTab) {
                    Text("互转矩阵").tag("matrix")
                    Text("覆盖统计").tag("ledger")
                    Text("运行日志").tag("logs")
                }
                .pickerStyle(.segmented)
                .frame(width: 300)
            }
            CardBox(title: "环境信息", subtitle: "面向排查的技术信息", systemImage: "stethoscope") {
                HStack(spacing: 24) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("工作目录").font(.caption).foregroundStyle(.secondary)
                        Text(model.workspacePathForDisplay.isEmpty ? "—" : model.workspacePathForDisplay)
                            .font(.caption2.monospaced()).textSelection(.enabled).lineLimit(1)
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        Text("命令行后端").font(.caption).foregroundStyle(.secondary)
                        Text(model.backendPathText.isEmpty ? "—" : model.backendPathText)
                            .font(.caption2.monospaced()).textSelection(.enabled).lineLimit(1)
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        Text("版本 / 模式").font(.caption).foregroundStyle(.secondary)
                        Text("\(model.asiVersion) · \(model.productModeText)")
                            .font(.caption2.monospaced()).lineLimit(1)
                    }
                    Spacer()
                }
            }
            switch model.advancedTab {
            case "ledger": ledgerTab
            case "logs": logsTab
            default: matrixTab
            }
        }
        .padding(20)
    }

    // MARK: matrix
    private var matrixTab: some View {
        VStack(alignment: .leading, spacing: 10) {
            CardBox(title: "互转矩阵（asi matrix*）", systemImage: "tablecells") {
                HStack(spacing: 12) {
                    Picker("矩阵", selection: $model.selectedMatrixKind) {
                        ForEach(model.matrixKinds, id: \.self) { kind in
                            Text(matrixLabel(kind)).tag(kind)
                        }
                    }
                    .frame(width: 340)
                    Toggle("快速（--limit 1）", isOn: $model.matrixQuick)
                    Spacer()
                    Button {
                        Task { await model.runMatrix() }
                    } label: {
                        Label("运行矩阵", systemImage: "play.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.matrixRunning)
                    Button {
                        model.openPath(model.matrixDocPath())
                    } label: {
                        Label("打开矩阵文档", systemImage: "doc.text")
                    }
                    .disabled(model.matrixDocPath() == nil)
                }
                if model.matrixRunning || !model.matrixProgress.isEmpty {
                    HStack(spacing: 8) {
                        if model.matrixRunning { ProgressView().controlSize(.small) }
                        Text(L(model.matrixProgress)).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            if let result = model.matrixResult {
                CardBox(title: "运行结果", systemImage: "chart.bar") {
                    HStack(spacing: 12) {
                        StatusPill(text: result.ok ? "成功" : "失败",
                                   color: result.ok ? .green : .red)
                        Text(result.summary?.text ?? "—").font(.callout.monospaced())
                        Spacer()
                        Button("打开报告") { model.openPath(result.reportPath) }
                        Button("显示输出") { model.revealInFinder(result.outputDir) }
                    }
                    ScrollView {
                        VStack(spacing: 0) {
                            ForEach(result.rows) { row in
                                HStack(spacing: 8) {
                                    Text(row.harness).font(.caption.monospaced()).frame(width: 150, alignment: .leading)
                                    EvidenceBadge(evidence: row.evidence)
                                    Text(L(row.status ?? "—")).font(.caption)
                                    Text(row.levelText).font(.caption2.monospaced())
                                        .foregroundStyle(.secondary)
                                    Spacer()
                                }
                                .padding(.vertical, 2)
                                Divider()
                            }
                        }
                    }
                    .frame(maxHeight: 320)
                }
            }
        }
    }

    private func matrixLabel(_ kind: String) -> String {
        switch kind {
        case "matrix": return "批 1 · 5 原生互转"
        case "matrix-batch2": return "批 2 · OSS 采集"
        case "matrix-batch3": return "批 3 · 原生 fixtures"
        case "matrix-batch4": return "批 4 · fixtures/构造 DB"
        case "matrix-batch5": return "批 5 · REAL-LOCAL/CONSTRUCTED"
        default: return kind
        }
    }

    // MARK: ledger
    private var ledgerTab: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("覆盖统计（tools/coverage-report.py --json）")
                    .font(.headline)
                Spacer()
                Button {
                    Task { await model.loadCoverage() }
                } label: {
                    Label("刷新", systemImage: "arrow.clockwise")
                }
                .disabled(model.coverageRunning)
                if model.coverageRunning { ProgressView().controlSize(.small) }
            }
            if let error = model.coverageError {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
            }
            if let data = model.coverage {
                HStack(spacing: 10) {
                    metricCard("协议覆盖", data["after5_distinct"]?.countOrDisplay ?? "—")
                    metricCard("真实会话", data["real_count"]?.displayString ?? "—")
                    metricCard("分层覆盖", data["layered_v3"]?.displayString ?? "—")
                    metricCard("来源标签", data["after5_n"]?.displayString ?? "—")
                }
                DisclosureGroup("原始 JSON") {
                    ScrollView {
                        Text(JSONValue.prettyPrinted(data))
                            .font(.caption2.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 280)
                }
            } else if !model.coverageRunning {
                EmptyHint(text: "点击「刷新」读取覆盖统计")
            }
        }
        .onAppear {
            if model.coverage == nil && !model.coverageRunning {
                Task { await model.loadCoverage() }
            }
        }
    }

    private func metricCard(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(.system(size: 26, weight: .bold, design: .rounded))
            Text(L(title)).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.secondary.opacity(0.18)))
    }

    // MARK: logs
    private var logsTab: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(L("运行日志（\(model.logs.count) 条）")).font(.headline)
                Spacer()
                Button { model.clearLogs() } label: { Label("清空", systemImage: "trash") }
            }
            if model.logs.isEmpty {
                EmptyHint(text: "暂无日志")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(model.logs.reversed())) { entry in
                            LogRowView(entry: entry)
                            Divider()
                        }
                    }
                }
                .frame(maxHeight: 520)
            }
        }
    }
}

extension JSONValue {
    var countOrDisplay: String {
        if case .array(let arr) = self { return "\(arr.count)" }
        return displayString
    }
}
