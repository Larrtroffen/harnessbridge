import Foundation

/// Pure selection logic shared by the session browser and the migration wizard.
/// Kept UI-free so the headless self-test can exercise it directly.
///
/// The range anchor is stored as a **stable session id** (not a filtered list
/// index), so changing search/filter/sort order cannot make Shift-select jump
/// to an unrelated range. If the anchor is no longer visible, the next
/// Shift-click behaves like a normal click (anchor resets to the clicked item).
struct SelectionEngine: Sendable, Equatable {
    private(set) var selected: Set<String> = []
    private(set) var anchorID: String?

    init(selected: Set<String> = []) {
        self.selected = selected
        self.anchorID = nil
    }

    var count: Int { selected.count }
    var isEmpty: Bool { selected.isEmpty }
    var ids: Set<String> { selected }

    func isSelected(_ id: String) -> Bool { selected.contains(id) }

    /// Toggles one item. When `rangeMode` (Shift) is active and the anchor id is
    /// still present in `visibleIDs`, selects/deselects the whole range between
    /// anchor and the clicked id; otherwise behaves like a normal toggle.
    mutating func toggle(_ id: String, visibleIDs: [String], rangeMode: Bool = false) {
        guard visibleIDs.contains(id) else { return }
        if rangeMode, let anchor = anchorID,
           let anchorIndex = visibleIDs.firstIndex(of: anchor),
           let clickedIndex = visibleIDs.firstIndex(of: id) {
            let lower = min(anchorIndex, clickedIndex)
            let upper = max(anchorIndex, clickedIndex)
            let range = visibleIDs[lower...upper]
            let shouldSelect = !selected.contains(id)
            for item in range {
                if shouldSelect { selected.insert(item) } else { selected.remove(item) }
            }
            anchorID = id
            return
        }
        if selected.contains(id) { selected.remove(id) } else { selected.insert(id) }
        anchorID = id
    }

    mutating func selectAll(_ ids: [String]) {
        selected.formUnion(ids)
        anchorID = ids.last
    }

    /// Replaces the selection entirely (e.g. "最近 N 个" quick-select).
    mutating func replace(with ids: Set<String>) {
        selected = ids
        anchorID = nil
    }

    mutating func clear() {
        selected.removeAll()
        anchorID = nil
    }

    mutating func resetAnchor() {
        anchorID = nil
    }

    /// Inverts the selection within the given visible id set.
    mutating func invert(_ ids: [String]) {
        selected = selected.symmetricDifference(Set(ids))
        anchorID = ids.last
    }

    mutating func remove(ids: [String]) {
        selected.subtract(ids)
        if let anchor = anchorID, !selected.contains(anchor) {
            // Keep the anchor id even if it is deselected: Shift-range semantics
            // only depend on visibility, not on selection state.
            if !ids.contains(anchor) { return }
            anchorID = nil
        }
    }

    mutating func retainOnly(_ ids: [String]) {
        selected.formIntersection(Set(ids))
        if let anchor = anchorID, !ids.contains(anchor) { anchorID = nil }
    }
}

/// Sort options for lists in the product UI.
enum BrowserSort: String, CaseIterable, Identifiable {
    case recent
    case title
    case messages

    var id: String { rawValue }
    var label: String {
        switch self {
        case .recent: return "按时间"
        case .title: return "按标题"
        case .messages: return "按消息数（行数）"
        }
    }
}

enum ListDensity: String, CaseIterable, Identifiable {
    case compact
    case comfortable
    var id: String { rawValue }
    var label: String { self == .compact ? "紧凑" : "舒适" }
    var rowPadding: CGFloat { self == .compact ? 4 : 8 }
}
