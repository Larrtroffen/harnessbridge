import Foundation
import SwiftUI
import AppKit

// MARK: - Wizard state (kept inside AppModel because SwiftUI @State macros are
// unavailable with the pure CommandLineTools toolchain)
struct WizardState {
    var step: Int = 1
    var sourceID: String?
    var sessions: [SessionRow] = []
    var selection = SelectionEngine()
    var selectedIDs: Set<String> {
        get { selection.ids }
        set { selection = SelectionEngine(selected: newValue) }
    }
    var searchText: String = ""
    var searchInput: String = ""
    var displayLimit: Int = 200
    var previewCache: [String: SessionPreview] = [:]
    var previewLoadingID: String?
    var previewFocusID: String?
    var targetID: String = "dsh"
    var options = MigrationOptions(outputDir: "")
    var running = false
    var progressText: String = ""
    var progressValue: Double = 0
    var results: [MigrationItemResult] = []
    var finished = false
    var errorText: String?
    var report: MigrationReport?

    var target: MigrationTarget { MigrationTarget.find(targetID) }

    var selectedSessions: [SessionRow] {
        sessions.filter { selectedIDs.contains($0.id) }
    }
}

struct MigrateAllState {
    var step = 1                 // 1 target 2 sources+filters 3 plan 4 executing 5 results
    var targetID = "dsh"
    var sources: [MigrateAllSource] = []
    var limitText = ""
    var sinceDays = 0            // 0 = 全部
    var sessionMode: SessionMode = .keep
    var plan: MigrateAllPlan?
    var buildingPlan = false
    var planError: String?
    var running = false
    var cancelled = false
    var progressText = ""
    var progressValue: Double = 0
    var report: MigrateAllReport?
    var journalPath: String?
    var restoring = false
}

@MainActor
final class AppModel: ObservableObject {
    // navigation
    @Published var page: AppPage = .home
    @Published var showWelcome = false
    @Published var dataMigrationNote: String?

    // backend
    @Published var backendReady = false
    @Published var backendError: String?
    @Published var workspacePath = ""
    @Published var backendPathText = ""
    @Published var workspacePathForDisplay = ""
    @Published var asiVersion = ""
    @Published var productModeText = ""
    private var bridge: BackendBridge?
    private var backend: ProductBackend?
    private var caps = Capabilities()

    // harness detection
    @Published var harnesses: [HarnessInfo] = []
    @Published var detecting = false
    @Published var detectionNote = ""
    @Published var detectCacheTime: Date?

    // output / history
    @Published var outputDir: String = Paths.outputRoot().path
    @Published var history: [MigrationRecord] = []
    private let historyStore = HistoryStore()
    @Published var historySelectedID: UUID?

    // session detail (product v1.2)
    @Published var detail: SessionDetail?
    @Published var detailLoading = false
    @Published var detailError: String?
    @Published var detailSource = ""
    @Published var detailSession: SessionRow?
    @Published var detailKindFilter = "all"      // all | user | assistant | thinking | tool | error
    @Published var detailSearch = ""
    @Published var detailExpanded: Set<Int> = []
    @Published var detailScrollTarget: Int?
    @Published var detailReturnPage: AppPage = .sessions
    @Published var detailUsingBackend = false

    // wizard
    @Published var wizard = WizardState()
    @Published var showInstallConfirm = false
    @Published var showMoveConfirm = false
    @Published var wizardJournalPath: String?
    @Published var wizardRestoring = false

    // one-click migrate-all (v1.4)
    @Published var migrateAll = MigrateAllState()
    @Published var showMigrateAllConfirm = false
    @Published var showRestoreConfirm = false
    @Published var pendingRestoreJournal: String?
    private let migrateAllCancel = CancellationFlag()

    // session browser
    @Published var browserHarness = "claude"
    @Published var browserSessions: [SessionRow] = []
    @Published var browserSearch = ""
    @Published var browserSelectedID: String?
    @Published var browserPreview: SessionPreview?
    @Published var browserLoading = false
    @Published var browserPreviewLoading = false
    @Published var browserError: String?
    @Published var browserSelection = SelectionEngine()
    @Published var browserFilteredSorted: [SessionRow] = []
    @Published var browserSort: BrowserSort = .recent
    @Published var browserDensity: ListDensity = .comfortable
    @Published var browserDisplayLimit = 200
    @Published var browserSearchInput = ""
    @Published var browserScrollAnchorID: String?
    @Published var toast: ToastData?
    @Published var searchFocusRequest = 0
    @Published var showBulkConfirm = false
    @Published var showMigrationConfirm = false
    @Published var showClearHistoryConfirm = false
    @Published var detailVisibleEvents = 200
    @Published var detailFilteredCache: [DetailEvent] = []
    @Published var detailFiltering = false
    @Published var detailGroupsCache: [DetailGroup] = []
    @Published var detailGrouping = false
    @Published var bulkExportRunning = false
    @Published var bulkExportProgress = ""

    // caches / cancellation tokens / debounce tasks
    private struct CachedRows { var rows: [SessionRow]; var date: Date }
    private struct CachedDetail { var detail: SessionDetail; var date: Date }
    private var listCache: [String: CachedRows] = [:]
    private var detailCache: [String: CachedDetail] = [:]
    private var detectCacheDate: Date?
    private let listCacheTTL: TimeInterval = 30
    private let detailCacheTTL: TimeInterval = 120
    private var detectToken = 0
    private var browserToken = 0
    private var wizardToken = 0
    private var detailToken = 0
    private var detailFilterToken = 0
    private var detailGroupToken = 0
    private var browserSearchTask: Task<Void, Never>?
    private var wizardSearchTask: Task<Void, Never>?
    private var toastTask: Task<Void, Never>?

    // settings
    @Published var settingsWorkspace = ""
    @Published var settingsOutput = ""

    // advanced tools
    @Published var advancedTab = "matrix"
    @Published var matrixKinds: [String] = []
    @Published var selectedMatrixKind = "matrix"
    @Published var matrixQuick = true
    @Published var matrixRunning = false
    @Published var matrixProgress = ""
    @Published var matrixResult: MatrixRunResult?
    @Published var coverage: JSONValue?
    @Published var coverageRunning = false
    @Published var coverageError: String?
    @Published var logs: [LogEntry] = []

    // status
    @Published var statusLine = "正在准备…"
    @Published var isBusy = false
    @Published var sidebarWidth: Double = 230
    @Published var sidebarDragStart: Double = 230
    @Published var sidebarDragging = false

    // MARK: init / bootstrap
    init() {
        let migrationNote = AppDataMigration.migrateIfNeeded()
        dataMigrationNote = migrationNote
        settingsWorkspace = Paths.workspaceOverride ?? ""
        settingsOutput = Paths.outputRootOverride ?? ""
        wizard.options.outputDir = outputDir
        restorePersistedState()
        if let snapshot = DetectCacheStore.load() {
            harnesses = snapshot.harnesses
            detectCacheTime = snapshot.detectedAt
            detectionNote = "上次检测：\(Fmt.date(snapshot.detectedAt))（正在后台刷新…）"
            detecting = true
        }
        Task { await bootstrap() }
    }

    private func restorePersistedState() {
        let defaults = UserDefaults.standard
        if let harness = defaults.string(forKey: "HB.LastBrowserHarness"), !harness.isEmpty {
            browserHarness = harness
        }
        if let sort = BrowserSort(rawValue: defaults.string(forKey: "HB.LastBrowserSort") ?? "") {
            browserSort = sort
        }
        if let density = ListDensity(rawValue: defaults.string(forKey: "HB.LastDensity") ?? "") {
            browserDensity = density
        }
        if let target = defaults.string(forKey: "HB.LastTarget"),
           MigrationTarget.all.contains(where: { $0.id == target }) {
            wizard.targetID = target
        }
        if let filter = defaults.string(forKey: "HB.LastDetailFilter") {
            detailKindFilter = filter
        }
        let width = defaults.double(forKey: "HB.SidebarWidth")
        if width >= 180 { sidebarWidth = min(max(width, 190), 320) }
        sidebarDragStart = sidebarWidth
    }

    func setSidebarWidth(_ width: Double, persist: Bool = true) {
        sidebarWidth = min(max(width, 190), 320)
        if persist { UserDefaults.standard.set(sidebarWidth, forKey: "HB.SidebarWidth") }
    }

    private func persist(_ key: String, _ value: String) {
        UserDefaults.standard.set(value, forKey: key)
    }

    var showWelcomeFirstLaunch: Bool {
        !(UserDefaults.standard.bool(forKey: "HBHasCompletedWelcome") ||
          UserDefaults.standard.bool(forKey: "SFHasCompletedWelcome") ||
          UserDefaults.standard.bool(forKey: "SCHasCompletedWelcome"))
    }

    func bootstrap() async {
        backendError = nil
        backendReady = false
        statusLine = "正在连接本机会话工具…"
        guard let workspace = Paths.discoverWorkspace() else {
            backendError = "找不到本机的会话工具。请点击「设置」手动指定工作目录。"
            statusLine = "未找到本机会话工具"
            return
        }
        workspacePath = workspace.path
        workspacePathForDisplay = workspace.path
        let bridge = BackendBridge(workspace: workspace)
        self.bridge = bridge
        backendPathText = bridge.asiPath.path
        do {
            let version = try await offload { try bridge.version() }
            asiVersion = version
            let capabilities = try await offload { try bridge.capabilities() }
            caps = capabilities
            matrixKinds = capabilities.matrixKinds.isEmpty ? ["matrix"] : capabilities.matrixKinds
            if !matrixKinds.contains(selectedMatrixKind) { selectedMatrixKind = matrixKinds.first ?? "matrix" }
            backend = ProductBackend(bridge: bridge, caps: capabilities)
            backendReady = true
            productModeText = backend?.modeDescription ?? ""
            outputDir = Paths.outputRoot().path
            wizard.options.outputDir = outputDir
            history = historyStore.load()
            if let first = visibleHistory.first { historySelectedID = first.id }
            statusLine = "准备就绪"
            appendLog(command: "连接本机会话工具", ok: true, detail: version)
            showCachedDetectionIfAvailable()
            detecting = true
            detectionNote = harnesses.isEmpty
                ? "正在检测本机已安装的会话工具…"
                : "正在后台刷新检测结果（上次：\(detectCacheTime.map { Fmt.date($0) } ?? "未知")）…"
            Task { await self.detectHarnesses(force: true) }
            if showWelcomeFirstLaunch { showWelcome = true }
            if let note = dataMigrationNote {
                showToast(note, kind: .info)
                dataMigrationNote = nil
            }
        } catch {
            backendError = "连接本机会话工具失败：\(Self.userMessage(for: error))"
            statusLine = "连接失败"
            appendLog(command: "连接本机会话工具", ok: false, detail: error.localizedDescription)
        }
    }

    private func showCachedDetectionIfAvailable() {
        guard let snapshot = DetectCacheStore.load() else { return }
        harnesses = snapshot.harnesses
        detectCacheTime = snapshot.detectedAt
        detectionNote = "上次检测：\(Fmt.date(snapshot.detectedAt))（刷新中…）"
    }

    func detectHarnesses(force: Bool = false) async {
        guard let backend else { return }
        if !force, !harnesses.isEmpty, let date = detectCacheDate,
           Date().timeIntervalSince(date) < listCacheTTL {
            return
        }
        detectToken += 1
        let token = detectToken
        detecting = true
        detectionNote = "正在检测本机已安装的会话工具…"
        let result = await Task.detached(priority: .userInitiated) { () -> Result<[HarnessInfo], Error> in
            do { return .success(try backend.detect(fast: true)) } catch { return .failure(error) }
        }.value
        guard token == detectToken else { return }
        detecting = false
        switch result {
        case .success(let harnesses):
            self.harnesses = harnesses
            self.detectCacheDate = Date()
            let snapshot = DetectCacheStore.save(harnesses: harnesses)
            self.detectCacheTime = snapshot?.detectedAt ?? Date()
            let detected = harnesses.filter { $0.detected && $0.sessionCount > 0 }
            detectionNote = "发现 \(detected.count) 个可用工具，共 \(harnesses.reduce(0) { $0 + $1.sessionCount }) 个会话（刚刚检测）"
            appendLog(command: "检测本机工具（--fast）", ok: true, detail: detectionNote)
        case .failure(let error):
            if harnesses.isEmpty {
                detectionNote = "检测失败：\(Self.userMessage(for: error))"
            } else {
                detectionNote = "刷新失败，继续显示上次结果（\(detectCacheTime.map { Fmt.date($0) } ?? "未知")）：\(Self.userMessage(for: error))"
            }
            appendLog(command: "检测本机工具", ok: false, detail: error.localizedDescription)
            showToast("检测失败，已保留上次结果", kind: .warning)
        }
    }

    func refreshHarnesses() async {
        await detectHarnesses(force: true)
        showToast("已重新检测本机工具", kind: .success)
    }

    /// Refresh sidebar counts on app activation / returning to foreground.
    /// Detection is fast (~0.1s with --fast) but throttle bursts to 2s.
    private var lastCountRefresh = Date.distantPast
    func refreshHarnessCountsIfNeeded(force: Bool = false) {
        if !force, Date().timeIntervalSince(lastCountRefresh) < 2 { return }
        lastCountRefresh = Date()
        Task { await detectHarnesses(force: true) }
    }

    func invalidateListCache(source: String? = nil) {
        if let source { listCache.removeValue(forKey: source) } else { listCache.removeAll() }
    }

    func invalidateAllCaches() {
        listCache.removeAll()
        detectCacheDate = nil
        detailCache.removeAll()
    }

    // MARK: welcome
    func completeWelcome() {
        UserDefaults.standard.set(true, forKey: "HBHasCompletedWelcome")
        showWelcome = false
        page = .home
        statusLine = "准备就绪"
    }

    func replayWelcome() {
        showWelcome = true
    }

    func chooseOutputDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: outputDir)
        panel.prompt = "选择输出目录"
        panel.message = "迁移生成的文件将保存在这里（不会修改原始会话）"
        if panel.runModal() == .OK, let url = panel.url {
            outputDir = url.path
            wizard.options.outputDir = url.path
            Paths.outputRootOverride = url.path
            settingsOutput = url.path
            try? Paths.ensureDirectory(url)
            appendLog(command: "选择输出目录", ok: true, detail: url.path)
        }
    }

    // MARK: home
    var detectedHarnesses: [HarnessInfo] {
        harnesses.filter { $0.detected || $0.sessionCount > 0 }
    }

    var totalSessionCount: Int { harnesses.reduce(0) { $0 + $1.sessionCount } }

    /// Self-test records are kept in history.json for automated verification but
    /// hidden from the product UI.
    var visibleHistory: [MigrationRecord] { history.filter { !$0.isSelfTest } }

    var recentMigrations: [MigrationRecord] { Array(visibleHistory.prefix(5)) }

    func harnessName(_ id: String) -> String {
        harnesses.first { $0.id == id }?.name ?? HarnessCatalog.name(for: id)
    }

    func harnessColor(_ id: String) -> String {
        harnesses.first { $0.id == id }?.colorHex ?? HarnessCatalog.color(for: id)
    }

    func startExportFlow() {
        startWizard(sourceID: nil)
        wizard.targetID = "atif"
        wizard.step = 1
    }

    func migrateFromHome() {
        startWizard(sourceID: nil)
    }

    // MARK: sessions browser (v1.3: cache + debounce + incremental + selection)
    func openSessionsBrowser(harness: String? = nil) {
        page = .sessions
        if let harness { setBrowserHarness(harness) }
        else if browserSessions.isEmpty { Task { await loadBrowserSessions() } }
    }

    func setBrowserHarness(_ id: String) {
        guard browserHarness != id else { return }
        browserHarness = id
        persist("HB.LastBrowserHarness", id)
        browserSelection.clear()
        browserDisplayLimit = 200
        browserSessions = []
        browserFilteredSorted = []
        browserPreview = nil
        browserSelectedID = nil
        browserError = nil
        Task { await loadBrowserSessions() }
    }

    func loadBrowserSessions(force: Bool = false) async {
        guard let backend, !browserHarness.isEmpty else { return }
        browserToken += 1
        let token = browserToken
        let harness = browserHarness
        browserLoading = true
        browserError = nil
        if !force, let cached = listCache[harness],
           Date().timeIntervalSince(cached.date) < listCacheTTL {
            applyBrowserRows(cached.rows, token: token)
            browserLoading = false
            return
        }
        do {
            let rows = try await offload { try backend.listSessions(source: harness) }
            guard token == browserToken else { return }
            listCache[harness] = CachedRows(rows: rows, date: Date())
            applyBrowserRows(rows, token: token)
        } catch {
            guard token == browserToken else { return }
            browserError = Self.userMessage(for: error)
            browserSessions = []
            browserFilteredSorted = []
        }
        if token == browserToken { browserLoading = false }
    }

    private func applyBrowserRows(_ rows: [SessionRow], token: Int) {
        guard token == browserToken else { return }
        let previousSelection = browserSelection.count
        browserSessions = rows
        browserSelection.retainOnly(rows.map(\.id))
        let dropped = previousSelection - browserSelection.count
        if dropped > 0 {
            showToast("刷新后已移除 \(dropped) 个不存在的已选会话（保留 \(browserSelection.count) 个）", kind: .info)
        }
        browserDisplayLimit = 200
        browserSelectedID = nil
        browserPreview = nil
        Task { await recomputeBrowserList(token: token) }
    }

    /// Filtering + sorting happens off the main thread; results are applied in one batch.
    private func recomputeBrowserList(token: Int? = nil) async {
        let rows = browserSessions
        let query = browserSearch.lowercased()
        let sort = browserSort
        let expected = token ?? browserToken
        let sorted = await Task.detached(priority: .userInitiated) { () -> [SessionRow] in
            let filtered: [SessionRow]
            if query.isEmpty {
                filtered = rows
            } else {
                filtered = rows.filter {
                    $0.displayTitle.lowercased().contains(query) || $0.id.lowercased().contains(query)
                        || ($0.cwd ?? "").lowercased().contains(query) || ($0.model ?? "").lowercased().contains(query)
                }
            }
            switch sort {
            case .recent:
                return filtered.sorted { ($0.createdAtMs ?? 0) > ($1.createdAtMs ?? 0) }
            case .title:
                return filtered.sorted { $0.displayTitle.localizedCaseInsensitiveCompare($1.displayTitle) == .orderedAscending }
            case .messages:
                return filtered.sorted { ($0.lines ?? 0) > ($1.lines ?? 0) }
            }
        }.value
        guard expected == browserToken else { return }
        browserFilteredSorted = sorted
        browserDisplayLimit = min(max(browserDisplayLimit, 200), max(sorted.count, 200))
    }

    var browserFilteredSessions: [SessionRow] {
        Array(browserFilteredSorted.prefix(browserDisplayLimit))
    }

    var browserFilteredCount: Int { browserFilteredSorted.count }
    var browserSelectedCount: Int { browserSelection.count }
    var browserHasMore: Bool { browserDisplayLimit < browserFilteredSorted.count }

    func loadMoreBrowser() {
        guard browserHasMore else { return }
        Motion.run(Motion.list) { browserDisplayLimit += 200 }
    }

    func setBrowserSearchInput(_ text: String) {
        browserSearchInput = text
        browserSearchTask?.cancel()
        browserSearchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 250_000_000)
            guard let self, !Task.isCancelled else { return }
            await MainActor.run {
                self.browserSearch = text
                self.browserDisplayLimit = 200
            }
            await self.recomputeBrowserList()
        }
    }

    func setBrowserSort(_ sort: BrowserSort) {
        browserSort = sort
        persist("HB.LastBrowserSort", sort.rawValue)
        browserDisplayLimit = 200
        Task { await recomputeBrowserList() }
    }

    func setBrowserDensity(_ density: ListDensity) {
        browserDensity = density
        persist("HB.LastDensity", density.rawValue)
    }

    // MARK: browser selection
    func browserRowIndex(_ id: String) -> Int? {
        browserFilteredSorted.firstIndex { $0.id == id }
    }

    func toggleBrowserSelection(_ session: SessionRow, shift: Bool = false) {
        guard browserFilteredSorted.contains(where: { $0.id == session.id }) else { return }
        Motion.run(Motion.quick) {
            browserSelection.toggle(session.id,
                                    visibleIDs: browserFilteredSorted.map(\.id),
                                    rangeMode: shift)
        }
    }

    func selectAllBrowserFiltered() {
        Motion.run(Motion.quick) {
            browserSelection.selectAll(browserFilteredSorted.map(\.id))
        }
        showToast("已全选当前筛选的 \(browserFilteredSorted.count) 个会话", kind: .info)
    }

    func clearBrowserSelection() {
        Motion.run(Motion.quick) { browserSelection.clear() }
    }

    func invertBrowserSelection() {
        Motion.run(Motion.quick) {
            browserSelection.invert(browserFilteredSorted.map(\.id))
        }
    }

    func copyBrowserSelectionSummary() {
        let selected = browserSessions.filter { browserSelection.isSelected($0.id) }
        guard !selected.isEmpty else {
            showToast("请先选择会话", kind: .warning)
            return
        }
        let lines = ["已选 \(selected.count) 个会话（\(harnessName(browserHarness))）"] +
            selected.map { "· \($0.displayTitle)" }
        copyToPasteboard(lines.joined(separator: "\n"))
        showToast("已复制 \(selected.count) 个会话摘要", kind: .success)
    }

    func requestBulkMigrate() {
        guard !browserSelection.isEmpty else {
            showToast("请先选择要迁移的会话", kind: .warning)
            return
        }
        startWizard(sourceID: browserHarness, preselectIDs: Array(browserSelection.ids))
    }

    func requestBulkExport() {
        guard !browserSelection.isEmpty else {
            showToast("请先选择要导出的会话", kind: .warning)
            return
        }
        showBulkConfirm = true
    }

    func performBulkExport() async {
        showBulkConfirm = false
        guard let backend else { return }
        let harness = browserHarness
        let selected = browserSessions.filter { browserSelection.isSelected($0.id) }
        guard !selected.isEmpty else { return }
        bulkExportRunning = true
        defer { bulkExportRunning = false }
        let outDir = URL(fileURLWithPath: outputDir).appendingPathComponent("export-\(Paths.stamp())", isDirectory: true)
        var items: [MigrationItemResult] = []
        for (index, session) in selected.enumerated() {
            bulkExportProgress = "正在导出 \(index + 1) / \(selected.count)：\(session.displayTitle)"
            let result = await Task.detached(priority: .userInitiated) { () -> MigrationItemResult in
                (try? backend.migrateOne(source: harness, session: session, target: "atif",
                                         outputDir: outDir,
                                         options: MigrationOptions(outputDir: outDir.path)))
                    ?? MigrationItemResult(sessionID: session.id, title: session.displayTitle,
                                           ok: false, outputDir: nil, artifact: nil, verifyStatus: nil,
                                           lossy: [], warnings: [], error: "导出失败")
            }.value
            items.append(result)
        }
        let report = MigrationReport(sourceID: harness, targetID: "atif", items: items,
                                     outputDir: outDir.path, elapsed: 0)
        let record = MigrationRecord(id: UUID(), date: Date(),
                                     sourceID: harness, sourceName: harnessName(harness),
                                     targetID: "atif", targetName: MigrationTarget.find("atif").title,
                                     mode: "export", outputDir: report.outputDir,
                                     sessionCount: items.count, okCount: report.okCount,
                                     failCount: report.failCount, items: items,
                                     isSelfTest: false, note: "批量导出所选会话")
        history = historyStore.append(record)
        historySelectedID = record.id
        bulkExportProgress = ""
        browserSelection.clear()
        invalidateListCache(source: harness)
        showToast("已导出 \(report.okCount) / \(items.count) 个会话", kind: report.failCount == 0 ? .success : .warning)
        statusLine = "批量导出完成：\(report.okCount) 成功，\(report.failCount) 失败"
        appendLog(command: "批量导出 \(items.count) 个会话", ok: report.failCount == 0, detail: report.outputDir)
    }

    func loadBrowserPreview(_ session: SessionRow) async {
        guard let backend else { return }
        let harness = browserHarness
        browserSelectedID = session.id
        browserPreviewLoading = true
        let preview = await Task.detached(priority: .userInitiated) { () -> SessionPreview in
            (try? backend.preview(source: harness, session: session))
                ?? SessionPreview(title: session.displayTitle, cwd: session.cwd, model: session.model,
                                  messageCount: nil, toolCallCount: nil, firstUserMessage: nil,
                                  recentMessages: [], warnings: [], sourceNote: "列表信息")
        }.value
        if browserSelectedID == session.id { browserPreview = preview }
        browserPreviewLoading = false
    }

    // MARK: session detail (v1.3: cache + cancellation + pagination)
    func openSessionDetail(source: String, session: SessionRow) {
        if page != .detail { detailReturnPage = page }
        detailToken += 1
        detailSource = source
        detailSession = session
        detail = nil
        detailError = nil
        detailExpanded = []
        detailVisibleEvents = 200
        detailSearch = ""
        detailFilteredCache = []
        detailFiltering = false
        detailGroupsCache = []
        detailGrouping = false
        page = .detail
        Task { await loadSessionDetail() }
    }

    func closeSessionDetail() {
        detailToken += 1
        page = detailReturnPage
        // release potentially large timeline objects when leaving the page
        detail = nil
        detailSession = nil
        detailError = nil
        detailExpanded = []
        detailFilteredCache = []
        detailFiltering = false
        detailGroupsCache = []
        detailGrouping = false
        detailCache = detailCache.filter { Date().timeIntervalSince($0.value.date) < detailCacheTTL }
    }

    private var detailCacheKey: String {
        "\(detailSource)|\(detailSession?.id ?? "")"
    }

    func loadSessionDetail() async {
        guard let backend, let session = detailSession else { return }
        detailToken += 1
        let token = detailToken
        let source = detailSource
        let key = detailCacheKey
        if let cached = detailCache[key], Date().timeIntervalSince(cached.date) < detailCacheTTL {
            detail = cached.detail
            detailUsingBackend = backend.hasSessionDetail && !cached.detail.isFallback
            detailVisibleEvents = 200
            await recomputeDetailFiltered()
            return
        }
        detailLoading = true
        detailError = nil
        do {
            let loaded = try await Task.detached(priority: .userInitiated) { () -> SessionDetail in
                try backend.sessionDetail(source: source, session: session, textLimit: 2000)
            }.value
            guard token == detailToken else { return }
            detail = loaded
            detailUsingBackend = backend.hasSessionDetail && !loaded.isFallback
            detailVisibleEvents = 200
            detailCache[key] = CachedDetail(detail: loaded, date: Date())
            await recomputeDetailFiltered()
            // keep the cache bounded
            if detailCache.count > 5 {
                let sorted = detailCache.sorted { $0.value.date > $1.value.date }
                detailCache = Dictionary(uniqueKeysWithValues: sorted.prefix(5).map { ($0.key, $0.value) })
            }
            appendLog(command: "读取会话详情", ok: true,
                      detail: detailUsingBackend ? "包含完整时间线" : "降级为最近消息摘要")
        } catch {
            guard token == detailToken else { return }
            detailError = "读取会话详情失败：\(Self.userMessage(for: error))"
            appendLog(command: "读取会话详情", ok: false, detail: detailError ?? "")
        }
        if token == detailToken { detailLoading = false }
    }

    func toggleDetailEvent(_ id: Int) {
        if detailExpanded.contains(id) { detailExpanded.remove(id) }
        else { detailExpanded.insert(id) }
    }

    var detailFilteredEventsAll: [DetailEvent] { detailFilteredCache }

    nonisolated static func filterDetailEvents(_ events: [DetailEvent], kind: String, query: String) -> [DetailEvent] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return events.filter { event in
            switch kind {
            case "user": if event.kind != "user" { return false }
            case "assistant": if event.kind != "assistant" { return false }
            case "thinking": if event.kind != "thinking" { return false }
            case "tool":
                if event.kind != "tool_call" && event.kind != "tool_result" { return false }
            case "error": if !event.isError { return false }
            default: break
            }
            guard !trimmed.isEmpty else { return true }
            let haystack = [event.text, event.tool?.name ?? "", event.role ?? "", event.kindLabel]
                .joined(separator: " ").lowercased()
            return haystack.contains(trimmed)
        }
    }

    private func computeFilteredEventsSync() -> [DetailEvent] {
        guard let detail else { return [] }
        return Self.filterDetailEvents(detail.timeline, kind: detailKindFilter, query: detailSearch)
    }

    /// Filtering large timelines (>2000 events) runs off the main thread and the
    /// result is applied in one batch.
    func recomputeDetailFiltered() async {
        guard let detail else {
            detailFilteredCache = []
            detailFiltering = false
            return
        }
        detailFilterToken += 1
        let token = detailFilterToken
        let kind = detailKindFilter
        let query = detailSearch
        detailFiltering = true
        let events = detail.timeline
        let filtered = await Task.detached(priority: .userInitiated) {
            AppModel.filterDetailEvents(events, kind: kind, query: query)
        }.value
        guard token == detailFilterToken else { return }
        detailFilteredCache = filtered
        detailFiltering = false
        await recomputeDetailGroups()
    }

    /// Groups timeline events off the main thread; main thread only assigns the
    /// finished array in one batch.
    func recomputeDetailGroups() async {
        detailGroupToken += 1
        let token = detailGroupToken
        let detail = self.detail
        let events = Array(detailFilteredCache.prefix(detailVisibleEvents))
        detailGrouping = true
        let groups = await Task.detached(priority: .userInitiated) {
            AppModel.buildDetailGroups(detail: detail, events: events)
        }.value
        guard token == detailGroupToken else { return }
        detailGroupsCache = groups
        detailGrouping = false
    }

    var detailFilteredEvents: [DetailEvent] {
        Array(detailFilteredEventsAll.prefix(detailVisibleEvents))
    }

    var detailFilteredTotalCount: Int { detailFilteredEventsAll.count }
    var detailHasMore: Bool { detailVisibleEvents < detailFilteredEventsAll.count }

    func loadMoreDetailEvents() {
        guard detailHasMore else { return }
        Motion.run(Motion.list) { detailVisibleEvents += 200 }
        Task { await recomputeDetailGroups() }
    }

    func setDetailKindFilter(_ filter: String) {
        detailKindFilter = filter
        persist("HB.LastDetailFilter", filter)
        detailVisibleEvents = 200
        Task { await recomputeDetailFiltered() }
    }

    func setDetailSearchInput(_ text: String) {
        detailSearch = text
        detailVisibleEvents = 200
        Task { await recomputeDetailFiltered() }
    }

    /// Groups are computed off the main thread (see recomputeDetailGroups);
    /// the view reads the cached result.
    var detailGroups: [DetailGroup] { detailGroupsCache }

    nonisolated static func buildDetailGroups(detail: SessionDetail?, events: [DetailEvent]) -> [DetailGroup] {
        guard let detail, !events.isEmpty else { return [] }
        var groups: [DetailGroup] = []
        let visibleIDs = Set(events.map(\.index))
        if !detail.sections.isEmpty {
            let bySection = Dictionary(grouping: detail.timeline) { $0.section ?? -1 }
            for section in detail.sections {
                let full = bySection[section.index] ?? []
                let visible = full.filter { visibleIDs.contains($0.index) }
                if visible.isEmpty { continue }
                var subtitleParts = [sectionSubtitleText(visible)]
                if let toolCalls = section.toolCalls, toolCalls > 0 { subtitleParts.append("\(toolCalls) 个工具调用") }
                if let tokens = section.tokens, tokens > 0 { subtitleParts.append("\(tokens) tokens") }
                groups.append(DetailGroup(id: section.index,
                                          title: section.title,
                                          subtitle: subtitleParts.joined(separator: " · "),
                                          events: visible))
            }
            let processed = Set(groups.flatMap { $0.events.map(\.index) })
            let uncategorized = events.filter { !processed.contains($0.index) }
            if !uncategorized.isEmpty {
                groups.append(DetailGroup(id: -1, title: "其他",
                                          subtitle: sectionSubtitleText(uncategorized),
                                          events: uncategorized))
            }
        } else {
            var current: [DetailEvent] = []
            var groupIndex = 0
            for event in events.sorted(by: { $0.index < $1.index }) {
                if event.kind == "user" && !current.isEmpty {
                    groups.append(DetailGroup(id: groupIndex, title: "第 \(groupIndex + 1) 段",
                                              subtitle: sectionSubtitleText(current), events: current))
                    current = []
                    groupIndex += 1
                }
                current.append(event)
            }
            if !current.isEmpty {
                groups.append(DetailGroup(id: groupIndex, title: "第 \(groupIndex + 1) 段",
                                          subtitle: sectionSubtitleText(current), events: current))
            }
        }
        return groups
    }

    nonisolated static func sectionSubtitleText(_ events: [DetailEvent]) -> String {
        let tools = events.filter { $0.kind == "tool_call" || $0.kind == "tool_result" }.count
        let errors = events.filter(\.isError).count
        var parts = ["\(events.count) 个事件"]
        if tools > 0 { parts.append("\(tools) 个工具事件") }
        if errors > 0 { parts.append("\(errors) 个失败") }
        return parts.joined(separator: " · ")
    }

    func jumpToTool(first: Bool) {
        guard let detail else { return }
        let toolEvents = detail.timeline.filter { $0.kind == "tool_call" || $0.kind == "tool_result" }
        guard let target = first ? toolEvents.first : toolEvents.last else {
            showToast("该会话没有工具调用", kind: .info)
            return
        }
        var filtered = detailFilteredCache.isEmpty ? computeFilteredEventsSync() : detailFilteredCache
        if !filtered.contains(where: { $0.index == target.index }) {
            detailKindFilter = "all"
            detailSearch = ""
            detailVisibleEvents = 200
            filtered = computeFilteredEventsSync()
            detailFilteredCache = filtered
        }
        if let position = filtered.firstIndex(where: { $0.index == target.index }) {
            detailVisibleEvents = max(detailVisibleEvents, position + 1)
        }
        detailScrollTarget = target.index
        Task { await recomputeDetailGroups() }
    }

    func copyDetailSummary() {
        guard let session = detailSession, let detail else { return }
        var lines = [
            "会话：\(session.displayTitle)",
            "来源：\(harnessName(detailSource))",
        ]
        if let cwd = detail.cwd { lines.append("项目路径：\(cwd)") }
        if let model = detail.model { lines.append("模型：\(model)") }
        lines.append("消息：用户 \(Fmt.int(detail.stats.messages.user)) / 助手 \(Fmt.int(detail.stats.messages.assistant)) / 工具 \(Fmt.int(detail.stats.messages.tool))")
        lines.append("工具调用：\(Fmt.int(detail.stats.toolCalls))（失败 \(Fmt.int(detail.stats.toolErrors))）")
        let usage = detail.stats.usage
        if usage.available {
            lines.append("Token：input \(Fmt.int(usage.inputTokens)) / output \(Fmt.int(usage.outputTokens)) / total \(Fmt.int(usage.totalTokens))")
        } else {
            lines.append("Token：该工具未提供 Token 统计")
        }
        copyToPasteboard(lines.joined(separator: "\n"))
        showToast("已复制会话摘要", kind: .success)
        statusLine = "已复制会话摘要"
    }

    func migrateDetailSession() {
        guard let session = detailSession else { return }
        startWizard(sourceID: detailSource, preselectSession: session.id)
    }

    func exportDetailSession() async {
        guard let session = detailSession else { return }
        browserHarness = detailSource
        await exportSessionFromBrowser(session)
    }

    func revealDetailSourceFile() {
        guard let path = detail?.path ?? detailSession?.path else { return }
        revealInFinder(path)
    }

    // MARK: wizard
    func startWizard(sourceID: String? = nil, preselectSession: String? = nil,
                     preselectIDs: [String] = []) {
        wizard = WizardState()
        wizard.options.outputDir = outputDir
        wizard.options.mode = .install
        wizard.options.sessionMode = .keep
        wizard.options.keepSystem = UserDefaults.standard.bool(forKey: "HB.LastKeepSystem")
        wizard.options.registerToProject = UserDefaults.standard.bool(forKey: "HB.LastRegister")
        wizard.targetID = UserDefaults.standard.string(forKey: "HB.LastTarget") ?? "dsh"
        if !MigrationTarget.all.contains(where: { $0.id == wizard.targetID }) { wizard.targetID = "dsh" }
        if harnessInfo(wizard.targetID)?.installSupported != true {
            if let firstInstallable = installTargets.first?.id {
                wizard.targetID = firstInstallable
                wizard.options.mode = .install
            } else {
                wizard.targetID = "atif"
                wizard.options.mode = .export
            }
        }
        wizard.sourceID = sourceID
        page = .wizard
        if let sourceID {
            wizard.step = 2
            Task {
                await loadWizardSessions()
                var wanted = preselectIDs
                if let preselectSession { wanted.append(preselectSession) }
                if !wanted.isEmpty {
                    wizard.selectedIDs = Set(wanted).intersection(Set(wizard.sessions.map(\.id)))
                }
            }
        } else {
            wizard.step = 1
        }
    }

    func wizardSelectSource(_ id: String) {
        let changed = wizard.sourceID != nil && wizard.sourceID != id
        wizard.sourceID = id
        wizard.selectedIDs = []
        wizard.displayLimit = 200
        wizard.step = 2
        if changed { showToast("已切换来源，之前的会话选择已清空", kind: .info) }
        Task { await loadWizardSessions() }
    }

    func loadWizardSessions(force: Bool = false) async {
        guard let backend, let source = wizard.sourceID else { return }
        wizardToken += 1
        let token = wizardToken
        wizard.running = false
        wizard.errorText = nil
        wizard.displayLimit = 200
        if !force, let cached = listCache[source],
           Date().timeIntervalSince(cached.date) < listCacheTTL {
            wizard.sessions = cached.rows
            wizard.selection.retainOnly(cached.rows.map(\.id))
            return
        }
        do {
            let rows = try await offload { try backend.listSessions(source: source) }
            guard token == wizardToken else { return }
            listCache[source] = CachedRows(rows: rows, date: Date())
            wizard.sessions = rows
            wizard.selection.retainOnly(rows.map(\.id))
        } catch {
            guard token == wizardToken else { return }
            wizard.sessions = []
            wizard.errorText = "读取会话列表失败：\(Self.userMessage(for: error))"
        }
    }

    private func wizardFilteredAll() -> [SessionRow] {
        let q = wizard.searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return wizard.sessions }
        return wizard.sessions.filter {
            $0.displayTitle.lowercased().contains(q) || $0.id.lowercased().contains(q)
                || ($0.cwd ?? "").lowercased().contains(q) || ($0.model ?? "").lowercased().contains(q)
        }
    }

    var wizardFilteredSessions: [SessionRow] {
        Array(wizardFilteredAll().prefix(wizard.displayLimit))
    }
    var wizardFilteredCount: Int { wizardFilteredAll().count }
    var wizardHasMore: Bool { wizard.displayLimit < wizardFilteredAll().count }
    var wizardSelectedCount: Int { wizard.selectedIDs.count }

    func loadMoreWizard() {
        guard wizardHasMore else { return }
        Motion.run(Motion.list) { wizard.displayLimit += 200 }
    }

    func setWizardSearchInput(_ text: String) {
        wizard.searchInput = text
        wizardSearchTask?.cancel()
        wizardSearchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 250_000_000)
            guard let self, !Task.isCancelled else { return }
            await MainActor.run {
                self.wizard.searchText = text
                self.wizard.displayLimit = 200
            }
        }
    }

    func toggleWizardSelection(_ session: SessionRow, shift: Bool = false) {
        let ids = wizardFilteredAll().map(\.id)
        guard ids.contains(session.id) else { return }
        Motion.run(Motion.quick) {
            wizard.selection.toggle(session.id, visibleIDs: ids, rangeMode: shift)
        }
    }

    func selectAllWizardFiltered() {
        let ids = wizardFilteredAll().map(\.id)
        Motion.run(Motion.quick) { wizard.selection.selectAll(ids) }
        showToast("已全选当前筛选的 \(ids.count) 个会话", kind: .info)
    }

    func clearWizardSelection() {
        Motion.run(Motion.quick) { wizard.selection.clear() }
    }

    func invertWizardSelection() {
        let ids = wizardFilteredAll().map(\.id)
        Motion.run(Motion.quick) { wizard.selection.invert(ids) }
    }

    func selectRecentWizardSessions(_ n: Int) {
        let recent = wizard.sessions.sorted { ($0.createdAtMs ?? 0) > ($1.createdAtMs ?? 0) }.prefix(n)
        Motion.run(Motion.quick) { wizard.selection.replace(with: Set(recent.map(\.id))) }
        showToast("已选择最近 \(min(n, wizard.sessions.count)) 个会话", kind: .info)
    }

    func selectAllWizardCurrent() {
        if wizard.searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            Motion.run(Motion.quick) { wizard.selection.replace(with: Set(wizard.sessions.map(\.id))) }
            showToast("已选择全部 \(wizard.sessions.count) 个会话", kind: .info)
        } else {
            selectAllWizardFiltered()
        }
    }

    func focusWizardPreview(_ session: SessionRow) async {
        wizard.previewFocusID = session.id
        await loadWizardPreview(session)
    }

    func loadWizardPreview(_ session: SessionRow) async {
        if wizard.previewCache[session.id] != nil { return }
        guard let backend, let source = wizard.sourceID else { return }
        wizard.previewLoadingID = session.id
        let preview = await Task.detached(priority: .userInitiated) { () -> SessionPreview in
            (try? backend.preview(source: source, session: session))
                ?? SessionPreview(title: session.displayTitle, cwd: session.cwd, model: session.model,
                                  messageCount: nil, toolCallCount: nil, firstUserMessage: nil,
                                  recentMessages: [], warnings: [], sourceNote: "列表信息")
        }.value
        wizard.previewCache[session.id] = preview
        if wizard.previewLoadingID == session.id { wizard.previewLoadingID = nil }
    }

    func targetAvailable(_ target: MigrationTarget) -> Bool {
        backend?.targetAvailable(target.id) ?? (target.id == "atif")
    }

    func targetBadge(_ target: MigrationTarget) -> String {
        if target.id == "atif" { return "仅导出" }
        guard let backend else { return target.badge }
        return backend.targetAvailable(target.id) ? target.badge : "暂不可用"
    }

    func wizardNext() {
        switch wizard.step {
        case 1:
            guard wizard.sourceID != nil else { return }
            wizard.step = 2
        case 2:
            guard !wizard.selectedIDs.isEmpty else { return }
            wizard.step = 3
        case 3:
            guard let backend, backend.targetAvailable(wizard.targetID) else { return }
            wizard.step = 4
        case 4:
            showMigrationConfirm = true
        default:
            break
        }
    }

    func wizardBack() {
        if showMigrationConfirm { showMigrationConfirm = false; return }
        if wizard.step > 1 && !wizard.running { wizard.step -= 1 }
    }

    var wizardCanContinue: Bool {
        switch wizard.step {
        case 1: return wizard.sourceID != nil
        case 2: return !wizard.selectedIDs.isEmpty
        case 3: return backend?.targetAvailable(wizard.targetID) ?? false
        default: return true
        }
    }

    func runWizardMigration(retryFailedOnly: Bool = false) async {
        guard let backend, let source = wizard.sourceID else { return }
        let sessions = wizard.selectedSessions
        guard !sessions.isEmpty else { return }
        wizard.running = true
        wizard.finished = false
        wizard.errorText = nil
        wizard.progressText = "准备迁移…"
        wizard.progressValue = 0
        if !retryFailedOnly { wizard.results = [] }
        let target = wizard.targetID
        let options = wizard.options
        let baseOut = URL(fileURLWithPath: options.outputDir.isEmpty ? outputDir : options.outputDir)
        let stamp = Paths.stamp()
        let runDir = baseOut.appendingPathComponent("migration-\(stamp)", isDirectory: true)
        try? Paths.ensureDirectory(runDir)
        let started = Date()
        var completed = 0
        for session in sessions {
            wizard.progressText = "正在迁移：\(session.displayTitle)"
            let itemOut = runDir.appendingPathComponent(source, isDirectory: true)
            let result = await Task.detached(priority: .userInitiated) { () -> MigrationItemResult in
                (try? backend.migrateOne(source: source, session: session, target: target,
                                         outputDir: itemOut, options: options))
                    ?? MigrationItemResult(sessionID: session.id, title: session.displayTitle,
                                           ok: false, outputDir: nil, artifact: nil,
                                           verifyStatus: nil, lossy: [], warnings: [],
                                           error: "迁移失败，请稍后重试")
            }.value
            if let index = wizard.results.firstIndex(where: { $0.sessionID == result.sessionID }) {
                wizard.results[index] = result
            } else {
                wizard.results.append(result)
            }
            completed += 1
            wizard.progressValue = Double(completed) / Double(max(1, sessions.count))
        }
        let elapsed = Date().timeIntervalSince(started)
        let report = MigrationReport(sourceID: source, targetID: target,
                                     items: wizard.results, outputDir: runDir.path, elapsed: elapsed)
        let journal = writeJournal(for: wizard.results, sessions: sessions, targetID: target)
        wizardJournalPath = journal?.path
        recordInstallHistory(sourceID: source, targetID: target, items: wizard.results,
                             options: options, journalPath: journal?.path,
                             migrateAll: false, cancelled: false)
        wizard.report = report
        wizard.running = false
        wizard.finished = true
        wizard.progressText = "迁移完成：成功 \(report.okCount) / \(report.items.count)"
        wizard.progressValue = 1
        appendLog(command: "迁移会话（\(report.okCount)/\(report.items.count) 成功）",
                  ok: report.failCount == 0, detail: "输出：\(runDir.path)")
        statusLine = report.failCount == 0
            ? "迁移完成，共 \(report.okCount) 个会话"
            : "迁移完成，其中 \(report.failCount) 个失败"
        invalidateListCache(source: source)
        detectCacheDate = nil
        showToast(report.failCount == 0
                  ? "迁移完成：\(report.okCount) 个会话成功"
                  : "迁移完成：\(report.okCount) 成功，\(report.failCount) 失败",
                  kind: report.failCount == 0 ? .success : .warning)
    }

    func copyWizardSummary() {
        guard let report = wizard.report else { return }
        var lines = [
            "迁移结果：\(harnessName(report.sourceID)) → \(MigrationTarget.find(report.targetID).title)",
            "共 \(report.items.count) 个会话：成功 \(report.okCount)，失败 \(report.failCount)",
            "输出目录：\(report.outputDir)",
        ]
        for item in report.items {
            lines.append("\(item.ok ? "✓" : "✕") \(item.title)\(item.verifyStatus.map { "（\($0)）" } ?? "")")
            for warning in item.lossy.prefix(3) {
                lines.append("   · 有损：\(warning)")
            }
            if let error = item.error { lines.append("   · 错误：\(error)") }
        }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(lines.joined(separator: "\n"), forType: .string)
        statusLine = "已复制迁移结果"
    }

    func finishWizard() {
        let savedTarget = wizard.targetID
        wizard = WizardState()
        wizard.options.outputDir = outputDir
        wizard.targetID = savedTarget
        persist("HB.LastTarget", savedTarget)
        page = .home
    }

    func retryFailedMigration() async {
        guard wizard.finished else { return }
        let failedIDs = Set(wizard.results.filter { !$0.ok }.map(\.sessionID))
        guard !failedIDs.isEmpty else {
            showToast("没有失败的会话需要重试", kind: .info)
            return
        }
        wizard.selectedIDs = failedIDs
        await runWizardMigration(retryFailedOnly: true)
    }

    func resetWizard() {
        startWizard(sourceID: nil)
    }

    private func recordHistory(report: MigrationReport, options: MigrationOptions) {
        let record = MigrationRecord(
            id: UUID(),
            date: Date(),
            sourceID: report.sourceID,
            sourceName: harnessName(report.sourceID),
            targetID: report.targetID,
            targetName: MigrationTarget.find(report.targetID).title,
            mode: options.installIntoRealStore ? "install" : "export",
            outputDir: report.outputDir,
            sessionCount: report.items.count,
            okCount: report.okCount,
            failCount: report.failCount,
            items: report.items,
            isSelfTest: false,
            note: options.installIntoRealStore ? "已写入目标 Harness（由后端备份）" : nil)
        history = historyStore.append(record)
        historySelectedID = record.id
    }

    // MARK: history
    func reloadHistory() { history = historyStore.load() }

    func deleteHistory(_ id: UUID) {
        history = historyStore.delete(id: id)
        if historySelectedID == id { historySelectedID = visibleHistory.first?.id }
    }

    func requestClearHistory() {
        guard !visibleHistory.isEmpty else {
            showToast("没有可清除的历史记录", kind: .info)
            return
        }
        showClearHistoryConfirm = true
    }

    func confirmClearHistory() {
        showClearHistoryConfirm = false
        historyStore.clear()
        history = []
        historySelectedID = nil
        showToast("迁移历史已清除", kind: .success)
    }

    func copyHistorySummary(_ record: MigrationRecord) {
        let lines = [
            "迁移记录 \(Fmt.time(Int64(record.date.timeIntervalSince1970 * 1000)))",
            "\(record.sourceName) → \(record.targetName)",
            "会话 \(record.sessionCount) 个：成功 \(record.okCount)，失败 \(record.failCount)",
            "输出目录：\(record.outputDir)",
        ] + record.items.map { item in
            "\(item.ok ? "✓" : "✕") \(item.title)\(item.error.map { "（\($0)）" } ?? "")"
        }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(lines.joined(separator: "\n"), forType: .string)
        statusLine = "已复制迁移摘要"
        showToast("已复制迁移摘要", kind: .success)
    }

    func record(_ id: UUID?) -> MigrationRecord? {
        guard let id else { return nil }
        return history.first { $0.id == id }
    }

    // MARK: export from browser
    func exportSessionFromBrowser(_ session: SessionRow) async {
        guard let backend else { return }
        let harness = browserHarness
        isBusy = true
        defer { isBusy = false }
        let outDir = URL(fileURLWithPath: outputDir).appendingPathComponent("export-\(Paths.stamp())", isDirectory: true)
        let result = await Task.detached(priority: .userInitiated) { () -> MigrationItemResult in
            (try? backend.migrateOne(source: harness, session: session, target: "atif",
                                     outputDir: outDir,
                                     options: MigrationOptions(outputDir: outDir.path)))
                ?? MigrationItemResult(sessionID: session.id, title: session.displayTitle,
                                       ok: false, outputDir: nil, artifact: nil, verifyStatus: nil,
                                       lossy: [], warnings: [], error: "导出失败")
        }.value
        let report = MigrationReport(sourceID: browserHarness, targetID: "atif",
                                     items: [result], outputDir: outDir.path, elapsed: 0)
        let record = MigrationRecord(id: UUID(), date: Date(),
                                     sourceID: report.sourceID, sourceName: harnessName(browserHarness),
                                     targetID: "atif", targetName: MigrationTarget.find("atif").title,
                                     mode: "export", outputDir: report.outputDir,
                                     sessionCount: 1, okCount: report.okCount, failCount: report.failCount,
                                     items: [result], isSelfTest: false, note: "从会话浏览导出")
        history = historyStore.append(record)
        historySelectedID = record.id
        invalidateListCache(source: harness)
        statusLine = result.ok ? "已导出：\(result.artifact ?? report.outputDir)" : "导出失败：\(result.error ?? "")"
        showToast(result.ok ? "已导出会话" : "导出失败：\(result.error ?? "未知错误")",
                  kind: result.ok ? .success : .error)
        appendLog(command: "导出会话", ok: result.ok, detail: result.ok ? report.outputDir : (result.error ?? ""))
    }

    func openMigrationWizard(for session: SessionRow) {
        startWizard(sourceID: browserHarness, preselectSession: session.id)
    }

    // MARK: settings
    func applySettings() async {
        let ws = settingsWorkspace.trimmingCharacters(in: .whitespacesAndNewlines)
        Paths.workspaceOverride = ws.isEmpty ? nil : ws
        let out = settingsOutput.trimmingCharacters(in: .whitespacesAndNewlines)
        Paths.outputRootOverride = out.isEmpty ? nil : out
        outputDir = Paths.outputRoot().path
        wizard.options.outputDir = outputDir
        page = .home
        await bootstrap()
    }

    func detectWorkspacePath() {
        settingsWorkspace = Paths.discoverWorkspace()?.path ?? ""
    }

    func resetWelcomeFlag() {
        UserDefaults.standard.removeObject(forKey: "HBHasCompletedWelcome")
        UserDefaults.standard.removeObject(forKey: "SFHasCompletedWelcome")
        UserDefaults.standard.removeObject(forKey: "SCHasCompletedWelcome")
        replayWelcome()
    }

    // MARK: advanced tools
    func loadCoverage() async {
        guard let backend else { return }
        coverageRunning = true
        coverageError = nil
        do {
            coverage = try await offload { try backend.coverage() }
            appendLog(command: "读取覆盖统计", ok: true, detail: "完成")
        } catch {
            coverageError = Self.userMessage(for: error)
        }
        coverageRunning = false
    }

    func runMatrix() async {
        guard let backend else { return }
        matrixRunning = true
        matrixResult = nil
        let kind = selectedMatrixKind
        let quick = matrixQuick
        matrixProgress = "正在运行 \(kind)…"
        let outDir = URL(fileURLWithPath: outputDir)
            .appendingPathComponent("matrix-\(kind)-\(Paths.stamp())", isDirectory: true)
        do {
            let result = try await offload { try backend.matrix(kind: kind, limit: quick ? 1 : nil, outDir: outDir) }
            matrixResult = result
            matrixProgress = "完成：\(result.summary?.text ?? "—")"
            appendLog(command: "运行 \(kind)", ok: result.ok, detail: matrixProgress)
        } catch {
            matrixProgress = "运行失败：\(Self.userMessage(for: error))"
            appendLog(command: "运行 \(kind)", ok: false, detail: matrixProgress)
        }
        matrixRunning = false
    }

    func matrixDocPath() -> String? {
        let kind = selectedMatrixKind
        var name = "interop-matrix.md"
        if kind.hasPrefix("matrix-batch"), let n = kind.last {
            name = "interop-matrix-batch\(n).md"
        }
        let path = workspacePath.isEmpty ? "" : "\(workspacePath)/docs/\(name)"
        return FileManager.default.fileExists(atPath: path) ? path : nil
    }

    func openPath(_ path: String?) {
        guard let path, !path.isEmpty else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func revealInFinder(_ path: String?) {
        guard let path, !path.isEmpty else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func revealOutput() {
        let path = outputDir.isEmpty ? Paths.outputRoot().path : outputDir
        try? Paths.ensureDirectory(URL(fileURLWithPath: path))
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func clearLogs() { logs.removeAll() }

    // MARK: logging
    private func appendLog(command: String, ok: Bool, detail: String) {
        let entry = LogEntry(date: Date(), command: command, duration: 0,
                             exitCode: ok ? 0 : 1, timedOut: false,
                             stdoutTail: detail, stderrTail: ok ? "" : detail)
        logs.append(entry)
        if logs.count > 400 { logs.removeFirst(logs.count - 400) }
    }

    // MARK: helpers
    static func userMessage(for error: Error) -> String {
        ProductBackend.userMessage(for: error)
    }

    private func offload<T: Sendable>(_ work: @escaping @Sendable () throws -> T) async throws -> T {
        try await Task.detached(priority: .userInitiated) { try work() }.value
    }
}


struct DetailGroup: Identifiable, Sendable {
    var id: Int
    var title: String
    var subtitle: String
    var events: [DetailEvent]
}


// MARK: - v1.3 UX helpers: toast, shortcuts, confirmations
extension AppModel {
    func showToast(_ message: String, kind: ToastData.Kind = .info) {
        toastTask?.cancel()
        Motion.run(Motion.quick) { toast = ToastData(message: message, kind: kind) }
        toastTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_200_000_000)
            guard let self, !Task.isCancelled else { return }
            await MainActor.run {
                Motion.run(Motion.gentle) { self.toast = nil }
            }
        }
    }

    func dismissToast() {
        toastTask?.cancel()
        Motion.run(Motion.gentle) { toast = nil }
    }

    func copyToPasteboard(_ text: String) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
    }

    // MARK: keyboard shortcuts
    func focusSearch() {
        if page == .home { page = .sessions }
        searchFocusRequest += 1
    }

    func refreshCurrent() {
        switch page {
        case .home, .settings:
            Task { await refreshHarnesses() }
        case .sessions:
            Task { await loadBrowserSessions(force: true) }
        case .wizard:
            Task { await loadWizardSessions(force: true) }
        case .detail:
            detailCache.removeValue(forKey: detailCacheKey)
            Task { await loadSessionDetail() }
        case .history:
            reloadHistory()
            showToast("已刷新迁移历史", kind: .info)
        default:
            Task { await refreshHarnesses() }
        }
    }

    /// True when the key window's first responder is a text input (NSTextView
    /// field editor / NSTextField). Menu shortcuts must yield to the system then.
    var isTextInputFocused: Bool {
        guard let window = NSApp.keyWindow, let responder = window.firstResponder else { return false }
        if responder is NSTextView { return true }
        if responder is NSTextField { return true }
        return false
    }

    /// Ends editing so the next Esc/Return reaches the app-level shortcut.
    func endTextEditingIfNeeded() -> Bool {
        guard isTextInputFocused, let window = NSApp.keyWindow else { return false }
        window.makeFirstResponder(nil)
        return true
    }

    func handleSelectAll() {
        if let textView = NSApp.keyWindow?.firstResponder as? NSTextView {
            textView.selectAll(nil)     // let the search field select its text
            return
        }
        if let textField = NSApp.keyWindow?.firstResponder as? NSTextField {
            textField.currentEditor()?.selectAll(nil)
            return
        }
        switch page {
        case .wizard where wizard.step == 2:
            selectAllWizardFiltered()
        case .sessions:
            selectAllBrowserFiltered()
        default:
            break
        }
    }

    func handleEscape() {
        // Toast must never swallow the first Esc: dismiss it, then still perform
        // the page-level cancel/back action.
        if toast != nil { dismissToast() }
        let hasDetailText = !detailSearch.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let outcome = Self.escapeOutcome(page: page,
                                         detailHasText: hasDetailText,
                                         textFocused: isTextInputFocused,
                                         wizardStep: wizard.step,
                                         wizardRunning: wizard.running,
                                         hasSelection: !browserSelection.isEmpty)
        switch outcome {
        case .clearDetailSearch:
            setDetailSearchInput("")
            detailVisibleEvents = 200
        case .closeDetail:
            closeSessionDetail()
        case .endEditing:
            _ = endTextEditingIfNeeded()
        case .closeWizard:
            finishWizard()
        case .wizardBack:
            wizardBack()
        case .clearSelection:
            clearBrowserSelection()
        case .goHome:
            page = .home
        case .none:
            break
        }
    }

    func handleReturn() {
        guard !isTextInputFocused else { return }
        switch page {
        case .sessions:
            if browserSelection.count == 1,
               let id = browserSelection.ids.first,
               let session = browserFilteredSorted.first(where: { $0.id == id }) {
                openSessionDetail(source: browserHarness, session: session)
            } else if browserSelection.isEmpty,
                      let first = browserFilteredSessions.first {
                openSessionDetail(source: browserHarness, session: first)
            } else if browserSelection.count > 1 {
                showToast("已选多个会话，按 ⌘↩ 批量迁移，或只选一个后按 Return 查看详情", kind: .info)
            }
        case .wizard:
            if model_wizardCanContinueForReturn() { wizardNext() }
        default:
            break
        }
    }

    private func model_wizardCanContinueForReturn() -> Bool {
        !wizard.running && wizard.step < 4
    }

    func handlePrimaryAction() {
        switch page {
        case .wizard:
            if wizard.finished { finishWizard() }
            else if showMigrationConfirm { confirmMigrationAndRun() }
            else if wizard.step == 4 { showMigrationConfirm = true }
            else if wizard.step < 4 { wizardNext() }
        case .sessions:
            if !browserSelection.isEmpty { requestBulkMigrate() }
            else if let first = browserFilteredSessions.first {
                openSessionDetail(source: browserHarness, session: first)
            }
        case .detail:
            migrateDetailSession()
        default:
            break
        }
    }

    func jumpFirstTool() { page = .detail; jumpToTool(first: true) }
    func jumpLastTool() { page = .detail; jumpToTool(first: false) }

    func openSettingsShortcut() { page = .settings }
    func openOutputFolder() { revealOutput() }

    // MARK: confirmations
    var migrationConfirmSummary: String {
        let sessions = wizard.selectedSessions
        let target = MigrationTarget.find(wizard.targetID)
        let info = harnessInfo(wizard.targetID)
        let out = wizard.options.outputDir.isEmpty ? outputDir : wizard.options.outputDir
        var lines = [
            "共 \(sessions.count) 个会话",
            "目标：\(target.title)",
        ]
        if wizard.options.mode == .install {
            lines.append("写入位置：\(info?.storePath ?? target.title)（目标工具会话库）")
            if let how = info?.howToSee, !how.isEmpty { lines.append("查看方式：\(how)") }
            lines.append("原始会话：\(wizard.options.sessionMode == .move ? "移出（保留可恢复备份）" : "保留")")
        } else {
            lines.append("输出目录：\(out)")
            lines.append("写入方式：仅导出文件，不修改任何工具数据")
        }
        lines.append("源会话不会被删除；失败时不会移出原始会话。")
        return lines.joined(separator: "\n")
    }

    func harnessInfo(_ id: String) -> HarnessInfo? {
        harnesses.first { $0.id == id }
    }

    /// Targets offered by the wizard: install-capable detected harnesses first,
    /// then the export-only option.
    var installTargets: [HarnessInfo] {
        detectedHarnesses.filter { $0.installSupported }
    }

    func targetStoreDescription(_ id: String) -> String? {
        harnessInfo(id)?.storePath
    }

    func targetHowToSee(_ id: String) -> String? {
        harnessInfo(id)?.howToSee
    }

    func confirmMoveMode() {
        Motion.run(Motion.quick) { wizard.options.sessionMode = .move }
        showMoveConfirm = false
        showToast("已选择移出原始会话（会生成可恢复备份）", kind: .warning)
    }

    func restoreWizardJournal() {
        guard let journal = wizardJournalPath else {
            showToast("本次迁移没有需要恢复的会话", kind: .info)
            return
        }
        requestRestoreJournal(journal)
    }

    func confirmMigrationAndRun() {
        showMigrationConfirm = false
        guard !wizard.selectedIDs.isEmpty else {
            showToast("请先选择会话", kind: .warning)
            return
        }
        Motion.run(Motion.spring) { wizard.step = 5 }
        Task { await runWizardMigration() }
    }

    var bulkExportSummary: String {
        "\(browserSelection.count) 个会话（\(harnessName(browserHarness))）将导出为通用交换文件。\n输出目录：\(outputDir)"
    }
}


// MARK: - v1.4 install journal + history
extension AppModel {
    /// Writes the recovery journal for app-side move fallback. Entries are only
    /// created for sessions whose source file was renamed.
    func writeJournal(for items: [MigrationItemResult],
                      sessions: [SessionRow],
                      targetID: String) -> URL? {
        // The fixed backend writes its own journal; prefer it (restore uses
        // migrate-restore). App journal is only a fallback for legacy backends.
        if let backendJournal = items.compactMap({ $0.journalPath }).first,
           !backendJournal.isEmpty {
            return URL(fileURLWithPath: backendJournal)
        }
        var byID: [String: SessionRow] = [:]
        for session in sessions { byID[session.id] = session }
        let entries: [SourceMoveEntry] = items.compactMap { item -> SourceMoveEntry? in
            guard item.sourceMoved, let backup = item.sourceBackupPath else { return nil }
            let sourcePath = byID[item.sessionID]?.path ?? ""
            return SourceMoveEntry(sessionID: item.sessionID, targetID: targetID,
                                   sourcePath: sourcePath, backupPath: backup,
                                   installedPath: item.installedPath, movedAt: Date())
        }
        guard !entries.isEmpty else { return nil }
        return MigrationJournalStore.write(entries: entries, targetID: targetID)
    }

    func recordInstallHistory(sourceID: String,
                              targetID: String,
                              items: [MigrationItemResult],
                              options: MigrationOptions,
                              journalPath: String?,
                              migrateAll: Bool,
                              cancelled: Bool) {
        let ok = items.filter { $0.ok && !$0.skipped }.count
        let skipped = items.filter(\.skipped).count
        let record = MigrationRecord(
            id: UUID(),
            date: Date(),
            sourceID: sourceID,
            sourceName: migrateAll ? "多个工具" : harnessName(sourceID),
            targetID: targetID,
            targetName: MigrationTarget.find(targetID).title,
            mode: options.mode.rawValue,
            outputDir: options.outputDir,
            sessionCount: items.count,
            okCount: ok,
            failCount: items.filter { !$0.ok }.count,
            items: items,
            isSelfTest: false,
            note: migrateAll ? "一键迁移（可恢复）" : (options.sessionMode == .move ? "已移出原始会话（可恢复）" : nil),
            targetStorePath: harnessInfo(targetID)?.storePath,
            sessionMode: options.sessionMode.rawValue,
            skippedCount: skipped,
            journalPath: journalPath,
            migrateAll: migrateAll,
            cancelled: cancelled)
        history = historyStore.append(record)
        historySelectedID = record.id
        invalidateListCache()
        detectCacheDate = nil
        Task { await detectHarnesses(force: true) }
        showToast(migrateAll ? "一键迁移完成：成功 \(ok) / 跳过 \(skipped) / 失败 \(items.count - ok - skipped)"
                            : "迁移完成：成功 \(ok) 个会话",
                  kind: items.contains(where: { !$0.ok }) ? .warning : .success)
    }

    func requestRestoreJournal(_ path: String) {
        pendingRestoreJournal = path
        showRestoreConfirm = true
    }

    func performRestore(removeInstalled: Bool) {
        showRestoreConfirm = false
        guard let path = pendingRestoreJournal, let backend else { return }
        pendingRestoreJournal = nil
        Task {
            let result: Result<ProductBackend.RestoreReport, Error> = await Task.detached {
                do { return .success(try backend.restore(journalPath: path, removeInstalled: removeInstalled)) }
                catch { return .failure(error) }
            }.value
            switch result {
            case .success(let report):
                Task { await detectHarnesses(force: true) }
                showToast(report.message, kind: report.failed > 0 ? .warning : .success)
            case .failure(let error):
                showToast("恢复失败：\(Self.userMessage(for: error))", kind: .error)
            }
        }
    }

    func restoreJournal(_ path: String) {
        requestRestoreJournal(path)
    }

    // MARK: one-click migrate-all
    private var migrateAllTargets: [HarnessInfo] { installTargets }

    func openMigrateAll() {
        page = .migrateAll
        migrateAll = MigrateAllState()
        let target = installTargets.first(where: { $0.id == "dsh" }) ?? installTargets.first ?? HarnessInfo(id: "dsh", name: "DeepSeek Harness",
                                                          colorHex: HarnessCatalog.color(for: "dsh"),
                                                          detected: true, sessionCount: 0,
                                                          recentAtMs: nil,
                                                          storePath: HarnessCatalog.storePath(for: "dsh"))
        migrateAll.targetID = target.id
        refreshMigrateAllSources()
        showWelcome = false
    }

    func refreshMigrateAllSources() {
        // Auto-correct an invalid target (e.g. detect data refreshed and target no longer installable).
        if !installTargets.contains(where: { $0.id == migrateAll.targetID }) {
            migrateAll.targetID = installTargets.first(where: { $0.id == "dsh" })?.id
                ?? installTargets.first?.id ?? migrateAll.targetID
        }
        let target = migrateAll.targetID
        migrateAll.sources = detectedHarnesses
            .filter { $0.id != target && $0.sessionCount > 0 }
            .map { MigrateAllSource(id: $0.id, name: $0.name,
                                    sessionCount: $0.sessionCount,
                                    recentAtMs: $0.recentAtMs, selected: true) }
        migrateAll.plan = nil
        migrateAll.planError = nil
        migrateAll.report = nil
        migrateAll.journalPath = nil
        // NOTE: never reset step here — callers decide navigation. (v1.4.3 click fix)
    }

    func selectMigrateAllTarget(_ id: String) {
        migrateAll.targetID = id
        refreshMigrateAllSources()
        migrateAll.step = 1
    }

    func toggleMigrateAllSource(_ id: String) {
        if let index = migrateAll.sources.firstIndex(where: { $0.id == id }) {
            migrateAll.sources[index].selected.toggle()
        }
        migrateAll.plan = nil
    }

    func migrateAllSetAllSources(_ selected: Bool) {
        for index in migrateAll.sources.indices { migrateAll.sources[index].selected = selected }
        migrateAll.plan = nil
    }

    func previewMigrateAllPlan() {
        guard let backend else { return }
        let target = migrateAll.targetID
        let selected = migrateAll.sources.filter(\.selected)
        let limit = Int(migrateAll.limitText.trimmingCharacters(in: .whitespaces))
        let sinceDays = migrateAll.sinceDays > 0 ? migrateAll.sinceDays : nil
        let targetInfo = harnessInfo(target)
        migrateAll.buildingPlan = true
        migrateAll.planError = nil
        Task {
            let result: Result<MigrateAllPlan, Error> = await Task.detached {
                do {
                    if backend.supportsMigrateAll {
                        return .success(try backend.buildPlanViaBackend(
                            target: target, sources: selected, limit: limit, sinceDays: sinceDays,
                            targetName: targetInfo?.name ?? target,
                            targetStorePath: targetInfo?.storePath,
                            howToSee: targetInfo?.howToSee))
                    }
                    return .success(try backend.buildMigrateAllPlan(
                        target: target,
                        targetName: targetInfo?.name ?? target,
                        targetStorePath: targetInfo?.storePath,
                        howToSee: targetInfo?.howToSee,
                        sources: selected, limit: limit, sinceDays: sinceDays))
                } catch { return .failure(error) }
            }.value
            migrateAll.buildingPlan = false
            switch result {
            case .success(var plan):
                plan.sessionMode = migrateAll.sessionMode
                migrateAll.plan = plan
                migrateAll.step = 3
            case .failure(let error):
                migrateAll.planError = "无法生成迁移计划：\(Self.userMessage(for: error))"
            }
        }
    }

    func runMigrateAll() {
        guard let backend, let basePlan = migrateAll.plan else { return }
        showMigrateAllConfirm = false
        var plan = basePlan
        plan.sessionMode = migrateAll.sessionMode
        let cancelFlag = migrateAllCancel
        cancelFlag.set(false)
        migrateAll.running = true
        migrateAll.cancelled = false
        migrateAll.progressValue = 0
        migrateAll.progressText = "准备执行…"
        migrateAll.step = 4
        let sessionMode = migrateAll.sessionMode
        let progress: @Sendable (Int, Int, String) -> Void = { done, total, text in
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                if self.migrateAll.running {
                    self.migrateAll.progressValue = total > 0 ? Double(done) / Double(total) : 0
                    self.migrateAll.progressText = text
                }
            }
        }
        Task {
            let report = await Task.detached { () -> MigrateAllReport in
                if backend.supportsMigrateAll {
                    do {
                        return try backend.runMigrateAllViaBackend(plan: plan, sessionMode: sessionMode,
                                                                   cancellation: cancelFlag)
                    } catch {
                        return backend.runMigrateAll(plan: plan, sessionMode: sessionMode,
                                                     progress: progress,
                                                     shouldCancel: { cancelFlag.isSet() })
                    }
                }
                return backend.runMigrateAll(plan: plan, sessionMode: sessionMode,
                                             progress: progress,
                                             shouldCancel: { cancelFlag.isSet() })
            }.value
            let journalPath: String? = {
                if let backendJournal = report.journalPath, !backendJournal.isEmpty { return backendJournal }
                return writeJournal(for: report.items,
                                    sessions: Array(plan.sessionsBySource.values.flatMap { $0 }),
                                    targetID: plan.targetID)?.path
            }()
            migrateAll.report = report
            migrateAll.journalPath = journalPath
            migrateAll.running = false
            migrateAll.cancelled = report.cancelled
            migrateAll.progressValue = 1
            migrateAll.step = 5
            let options = MigrationOptions(outputDir: "", mode: plan.mode, sessionMode: sessionMode)
            recordInstallHistory(sourceID: "all", targetID: plan.targetID, items: report.items,
                                 options: options, journalPath: journalPath,
                                 migrateAll: true, cancelled: report.cancelled)
        }
    }

    func cancelMigrateAll() {
        migrateAllCancel.set(true)
        migrateAll.cancelled = true
        migrateAll.progressText = "正在停止后端进程…已完成项与日志会保留"
        showToast("正在停止（后端进程会被终止），已完成项与日志保留", kind: .warning)
    }

    func restoreMigrateAllJournal() {
        guard let path = migrateAll.journalPath else {
            showToast("本次迁移没有需要恢复的会话", kind: .info)
            return
        }
        requestRestoreJournal(path)
    }
}

// MARK: - wizard option persistence
extension AppModel {
    func setWizardTarget(_ id: String) {
        guard MigrationTarget.all.contains(where: { $0.id == id }) else { return }
        Motion.run(Motion.quick) { wizard.targetID = id }
        persist("HB.LastTarget", id)
    }

    func setWizardKeepSystem(_ value: Bool) {
        wizard.options.keepSystem = value
        UserDefaults.standard.set(value, forKey: "HB.LastKeepSystem")
    }

    func setWizardRegister(_ value: Bool) {
        wizard.options.registerToProject = value
        UserDefaults.standard.set(value, forKey: "HB.LastRegister")
    }

    func restoreWizardOptions() {
        wizard.options.keepSystem = UserDefaults.standard.bool(forKey: "HB.LastKeepSystem")
        wizard.options.registerToProject = UserDefaults.standard.bool(forKey: "HB.LastRegister")
    }
}


// MARK: - v1.3.2 Escape decision (pure, unit-testable in --self-test)
enum EscapeOutcome: Equatable, Sendable {
    case endEditing
    case clearDetailSearch
    case closeDetail
    case closeWizard
    case wizardBack
    case clearSelection
    case goHome
    case none
}

extension AppModel {
    /// Toast is intentionally NOT part of the decision: it never swallows Esc.
    nonisolated static func escapeOutcome(page: AppPage,
                                          detailHasText: Bool,
                                          textFocused: Bool,
                                          wizardStep: Int,
                                          wizardRunning: Bool,
                                          hasSelection: Bool) -> EscapeOutcome {
        if page == .detail {
            return detailHasText ? .clearDetailSearch : .closeDetail
        }
        if textFocused { return .endEditing }
        switch page {
        case .wizard:
            if wizardRunning { return .none }
            return wizardStep > 1 ? .wizardBack : .closeWizard
        case .sessions:
            return hasSelection ? .clearSelection : .goHome
        default:
            return .goHome
        }
    }
}
