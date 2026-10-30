import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    @Namespace private var sidebarNamespace

    var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                if model.showWelcome {
                    WelcomeView()
                } else {
                    mainShell
                }
            }
            .frame(minWidth: 1080, minHeight: 720)
            .background {
                ZStack {
                    VisionBackground()
                    LinearGradient(colors: [Color.accentColor.opacity(0.06), .clear,
                                            Color.purple.opacity(0.05)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing)
                }
                .ignoresSafeArea()
            }
            .animation(Motion.gentle, value: model.page)
            .animation(Motion.gentle, value: model.showWelcome)

            if let toast = model.toast {
                ToastView(toast: toast)
                    .padding(.bottom, 46)
                    .allowsHitTesting(false)   // never blocks clicks or Esc
                    .animation(Motion.spring, value: toast.id)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            model.refreshHarnessCountsIfNeeded()
        }
        .background(WindowFrameAutosave(name: "HarnessBridgeMainWindow"))
        .background {
            VStack {
                Button("cancel") { model.handleEscape() }
                    .keyboardShortcut(.cancelAction)
                    .opacity(0)
                    .accessibilityHidden(true)
                Button("default") { model.handleReturn() }
                    .keyboardShortcut(.defaultAction)
                    .opacity(0)
                    .accessibilityHidden(true)
            }
            .frame(width: 0, height: 0)
        }
        .alert("导出所选会话？", isPresented: Binding(
            get: { model.showBulkConfirm },
            set: { model.showBulkConfirm = $0 }
        )) {
            Button("取消", role: .cancel) { model.showBulkConfirm = false }
            Button("导出") { Task { await model.performBulkExport() } }
        } message: {
            Text(model.bulkExportSummary)
        }
        .alert("恢复被移出的会话？", isPresented: Binding(
            get: { model.showRestoreConfirm },
            set: { model.showRestoreConfirm = $0 }
        )) {
            Button("取消", role: .cancel) {
                model.showRestoreConfirm = false
                model.pendingRestoreJournal = nil
            }
            Button("仅恢复源文件") { model.performRestore(removeInstalled: false) }
            Button("恢复并删除目标副本", role: .destructive) { model.performRestore(removeInstalled: true) }
        } message: {
            Text("默认只把源会话从 .migrated-*.bak 恢复回原位置，不删除目标工具中已安装的副本。\n选择「恢复并删除目标副本」会额外删除本次安装到目标会话库的副本（源备份文件仍会恢复，不会直接删除）。")
        }
        .alert("清除迁移历史？", isPresented: Binding(
            get: { model.showClearHistoryConfirm },
            set: { model.showClearHistoryConfirm = $0 }
        )) {
            Button("取消", role: .cancel) { model.showClearHistoryConfirm = false }
            Button("清除", role: .destructive) { model.confirmClearHistory() }
        } message: {
            Text("将删除本机保存的全部迁移历史记录（不会删除已生成的迁移文件）。此操作不可撤销。")
        }
    }

    private var mainShell: some View {
        VStack(spacing: 0) {
            topBar
            Divider()
            HStack(spacing: 0) {
                sidebar
                    .frame(width: model.sidebarWidth)
                sidebarResizer
                VStack(spacing: 0) {
                    pageContent
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    Divider()
                    statusBar
                }
            }
        }
    }

    // MARK: top bar
    private var topBar: some View {
        HStack(spacing: 12) {
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .font(.system(size: 22))
                .foregroundStyle(.tint)
            Text("HarnessBridge")
                .font(.headline)
            Text("Agent Session Converter")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(title(for: model.page))
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer()
            if !model.backendReady {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text("正在连接本机会话工具…").font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Label("本机工具已连接", systemImage: "checkmark.circle.fill")
                    .font(.caption)
                    .foregroundStyle(.green)
            }
            Button {
                model.openMigrateAll()
            } label: {
                Label("一键迁移", systemImage: "square.stack.3d.up.fill")
            }
            .help("把其他所有工具的会话迁移到指定目标")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private var sidebarResizer: some View {
        Rectangle()
            .fill(Color.secondary.opacity(0.10))
            .frame(width: 5)
            .contentShape(Rectangle())
            .onHover { hovering in
                if hovering { NSCursor.resizeLeftRight.push() } else { NSCursor.pop() }
            }
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { value in
                        if !model.sidebarDragging {
                            model.sidebarDragging = true
                            model.sidebarDragStart = model.sidebarWidth
                        }
                        model.setSidebarWidth(model.sidebarDragStart + value.translation.width, persist: false)
                    }
                    .onEnded { _ in
                        model.sidebarDragging = false
                        model.setSidebarWidth(model.sidebarWidth)
                    }
            )
    }

    private func title(for page: AppPage) -> String {
        page == .home ? "总览" : page.title
    }

    // MARK: sidebar
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(AppPage.allCases.filter { $0 != .advanced && $0 != .detail }) { page in
                    sidebarRow(page)
                }
            }
            .padding(.top, 8)
            Divider().padding(.vertical, 6)
            Text("高级")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 14)
                .padding(.bottom, 4)
            sidebarRow(.advanced)
            if !model.detectedHarnesses.isEmpty {
                Divider().padding(.vertical, 6)
                Text("本机工具")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 14)
                    .padding(.bottom, 2)
                ForEach(model.detectedHarnesses) { harness in
                    Button {
                        model.openSessionsBrowser(harness: harness.id)
                    } label: {
                        HStack(spacing: 7) {
                            HarnessLogoView(harnessID: harness.id, size: 16)
                            Text(harness.name).font(.caption).lineLimit(1)
                            Spacer()
                            Text("\(harness.sessionCount)")
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 3)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .help("浏览 \(harness.name) 的会话")
                }
            }
            Spacer()
            Divider()
            VStack(alignment: .leading, spacing: 4) {
                if let error = model.backendError {
                    Label("需要配置", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .help(error)
                } else {
                    Text("已检测 \(model.detectedHarnesses.count) 个工具 · \(model.totalSessionCount) 个会话")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Text("会话默认直接迁移到目标工具会话库")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .padding(12)
        }
        .glassBar()
    }

    private func sidebarRow(_ page: AppPage) -> some View {
        Button {
            model.page = page
        } label: {
            HStack(spacing: 9) {
                Image(systemName: page.systemImage)
                    .frame(width: 18)
                Text(page.title)
                Spacer()
                if page == .history && !model.visibleHistory.isEmpty {
                    Text("\(model.visibleHistory.count)")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
            .font(.callout)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                if model.page == page {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.accentColor.opacity(0.15))
                        .matchedGeometryEffect(id: "sidebarSelection", in: sidebarNamespace)
                }
            }
            .foregroundStyle(model.page == page ? Color.accentColor : Color.primary)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .animation(Motion.spring, value: model.page)
    }

    // MARK: page content
    @ViewBuilder
    private var pageContent: some View {
        Group {
            pageBody
        }
        .transition(.opacity.combined(with: .move(edge: .bottom)))
        .animation(Motion.gentle, value: model.page)
    }

    @ViewBuilder
    private var pageBody: some View {
        switch model.page {
        case .home: HomeView()
        case .wizard: WizardView()
        case .migrateAll: MigrateAllView()
        case .sessions: SessionsBrowserView()
        case .history: HistoryView()
        case .settings: SettingsView()
        case .help: HelpView()
        case .advanced: AdvancedToolsView()
        case .detail: SessionDetailView()
        }
    }

    // MARK: status bar
    private var statusBar: some View {
        HStack(spacing: 8) {
            if model.isBusy || model.detecting || model.matrixRunning || model.coverageRunning {
                ProgressView().controlSize(.small)
            }
            Text(model.statusLine)
                .font(.caption)
                .lineLimit(1)
            Spacer()
            if let note = Optional(model.detectionNote), !note.isEmpty, model.harnesses.isEmpty {
                Text(note).font(.caption2).foregroundStyle(.secondary)
            }
            Text("⌘R 刷新 · ⌘F 搜索 · ⌘A 全选 · Esc 返回")
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text("v\(AppInfo.version)")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 5)
        .glassBar()
    }
}
