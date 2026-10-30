import Foundation

/// Thread-safe cancellation flag shared between AppModel and the backend bridge.
/// When set, a running CLI process is terminated (SIGTERM → SIGKILL) so a
/// cancelled one-click migration really stops writing/renaming — not just UI.
final class CancellationFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false

    func set(_ newValue: Bool) {
        lock.lock()
        value = newValue
        lock.unlock()
    }

    func isSet() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}
