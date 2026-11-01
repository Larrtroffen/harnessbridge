import SwiftUI
import AppKit

// MARK: - Motion preferences (Reduce Motion aware; no SwiftUI macros needed)
enum Motion {
    static var reduceMotion: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }

    static var spring: Animation? {
        reduceMotion ? nil : .spring(response: 0.38, dampingFraction: 0.82)
    }

    static var quick: Animation? {
        reduceMotion ? nil : .spring(response: 0.24, dampingFraction: 0.78)
    }

    static var gentle: Animation? {
        reduceMotion ? nil : .easeInOut(duration: 0.22)
    }

    static var list: Animation? {
        reduceMotion ? nil : .easeOut(duration: 0.18)
    }

    /// Runs `body` inside an animation only when Reduce Motion is off.
    static func run(_ animation: Animation?, _ body: () -> Void) {
        if let animation {
            withAnimation(animation, body)
        } else {
            body()
        }
    }
}

// MARK: - Button styles
struct PressScaleButtonStyle: ButtonStyle {
    var pressedScale: CGFloat = 0.97

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !Motion.reduceMotion ? pressedScale : 1)
            .opacity(configuration.isPressed ? 0.9 : 1)
            .animation(Motion.quick, value: configuration.isPressed)
    }
}

// MARK: - Hover lift
final class HoverState: ObservableObject {
    @Published var hovering = false
}

struct HoverLiftModifier: ViewModifier {
    var scale: CGFloat = 1.015
    var shadow: CGFloat = 0.14
    @ObservedObject private var state = HoverState()

    func body(content: Content) -> some View {
        content
            .scaleEffect(state.hovering && !Motion.reduceMotion ? scale : 1)
            .shadow(color: .black.opacity(state.hovering ? shadow : 0),
                    radius: state.hovering ? 10 : 0, y: 4)
            .animation(Motion.quick, value: state.hovering)
            .onHover { state.hovering = $0 }
    }
}

extension View {
    func hoverLift(scale: CGFloat = 1.015, shadow: CGFloat = 0.14) -> some View {
        modifier(HoverLiftModifier(scale: scale, shadow: shadow))
    }
}

// MARK: - Toast
struct ToastData: Identifiable, Equatable {
    enum Kind { case info, success, warning, error }
    let id = UUID()
    var message: String
    var kind: Kind = .info
    var icon: String {
        switch kind {
        case .info: return "info.circle.fill"
        case .success: return "checkmark.circle.fill"
        case .warning: return "exclamationmark.triangle.fill"
        case .error: return "xmark.octagon.fill"
        }
    }
    var color: Color {
        switch kind {
        case .info: return .blue
        case .success: return .green
        case .warning: return .orange
        case .error: return .red
        }
    }
}

struct ToastView: View {
    let toast: ToastData
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: toast.icon).foregroundStyle(toast.color)
            Text(L(toast.message)).font(.callout).lineLimit(3)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(toast.color.opacity(0.35)))
        .shadow(color: .black.opacity(0.22), radius: 14, y: 6)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

// MARK: - Shimmer (progress)
struct ShimmerModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .overlay {
                if Motion.reduceMotion {
                    EmptyView()
                } else {
                    TimelineView(.animation) { context in
                        GeometryReader { geo in
                            let t = context.date.timeIntervalSinceReferenceDate
                            let phase = CGFloat(t.truncatingRemainder(dividingBy: 1.4) / 1.4) * 2.2 - 0.6
                            LinearGradient(colors: [.clear, .white.opacity(0.45), .clear],
                                           startPoint: .leading, endPoint: .trailing)
                                .frame(width: geo.size.width * 0.55)
                                .offset(x: phase * geo.size.width)
                        }
                        .clipped()
                        .allowsHitTesting(false)
                    }
                }
            }
    }
}

extension View {
    func shimmer() -> some View { modifier(ShimmerModifier()) }
}

// MARK: - Skeleton placeholder
struct SkeletonRow: View {
    var width: CGFloat = 260
    var body: some View {
        RoundedRectangle(cornerRadius: 5)
            .fill(Color.secondary.opacity(0.16))
            .frame(width: width, height: 12)
            .shimmer()
    }
}

struct SkeletonHarnessCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color.secondary.opacity(0.16))
                    .frame(width: 42, height: 42)
                    .shimmer()
                Spacer()
            }
            SkeletonRow(width: 110)
            SkeletonRow(width: 70)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.secondary.opacity(0.12)))
    }
}

struct SkeletonList: View {
    var rows: Int = 6
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(0..<rows, id: \.self) { index in
                HStack(spacing: 10) {
                    Circle().fill(Color.secondary.opacity(0.14)).frame(width: 18, height: 18)
                    SkeletonRow(width: index % 2 == 0 ? 300 : 220)
                    Spacer()
                }
                .padding(.vertical, 3)
            }
        }
    }
}

// MARK: - Animated number (Token rolling)
final class NumberAnimator: ObservableObject {
    @Published var displayed: Double = 0
    private var timer: Timer?
    private var target: Double = 0

    func set(_ value: Int, animated: Bool) {
        target = Double(value)
        timer?.invalidate()
        if !animated || Motion.reduceMotion || abs(displayed - target) < 0.5 {
            displayed = target
            return
        }
        let start = displayed
        let startTime = Date()
        let duration: Double = 0.45
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60.0, repeats: true) { [weak self] timer in
            guard let self else { timer.invalidate(); return }
            let progress = min(1.0, Date().timeIntervalSince(startTime) / duration)
            let eased = 1 - pow(1 - progress, 3)
            self.displayed = start + (self.target - start) * eased
            if progress >= 1 {
                self.displayed = self.target
                timer.invalidate()
            }
        }
    }
}

struct AnimatedNumber: View {
    let value: Int
    var font: Font = .system(size: 24, weight: .bold, design: .rounded)
    var formatter: (Int) -> String = { $0 >= 1_000_000 ? String(format: "%.2fM", Double($0) / 1_000_000)
        : ($0 >= 1000 ? String(format: "%.1fk", Double($0) / 1000) : "\($0)") }
    @ObservedObject private var animator = NumberAnimator()

    var body: some View {
        Text(formatter(Int(animator.displayed.rounded())))
            .font(font)
            .onAppear { animator.set(value, animated: false) }
            .onChange(of: value) { newValue in animator.set(newValue, animated: true) }
    }
}

// MARK: - Focused search field (AppKit-backed so ⌘F can focus it without macros)
struct SearchField: NSViewRepresentable {
    let placeholder: String
    @Binding var text: String
    var focusRequest: Int
    var onSubmit: (() -> Void)? = nil

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSSearchField {
        let field = NSSearchField()
        field.placeholderString = placeholder
        field.delegate = context.coordinator
        field.sendsSearchStringImmediately = false
        field.sendsWholeSearchString = false
        field.controlSize = .regular
        return field
    }

    func updateNSView(_ nsView: NSSearchField, context: Context) {
        // Don't overwrite the field while an IME composition is in progress
        // (Chinese/Japanese input): hasMarkedText() is true until the user commits.
        let composing = (nsView.currentEditor() as? NSTextView)?.hasMarkedText() ?? false
        if !composing, nsView.stringValue != text { nsView.stringValue = text }
        if context.coordinator.lastFocusRequest != focusRequest {
            context.coordinator.lastFocusRequest = focusRequest
            DispatchQueue.main.async {
                nsView.window?.makeFirstResponder(nsView)
                nsView.currentEditor()?.selectAll(nil)
            }
        }
    }

    final class Coordinator: NSObject, NSSearchFieldDelegate {
        var parent: SearchField
        // Baseline = value at mount: the field must NOT auto-focus just because
        // the page exists. Only a later increment (⌘F / click) requests focus.
        var lastFocusRequest: Int
        init(_ parent: SearchField) {
            self.parent = parent
            self.lastFocusRequest = parent.focusRequest
        }
        func controlTextDidChange(_ obj: Notification) {
            guard let field = obj.object as? NSSearchField else { return }
            if let editor = field.currentEditor() as? NSTextView, editor.hasMarkedText() {
                return   // composing: wait for commit instead of pushing partial text
            }
            parent.text = field.stringValue
        }

        func controlTextDidEndEditing(_ obj: Notification) {
            guard let field = obj.object as? NSSearchField else { return }
            parent.text = field.stringValue
        }
        func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
            if selector == #selector(NSResponder.insertNewline(_:)) {
                parent.onSubmit?()
                return true
            }
            return false
        }
    }
}

// MARK: - Window frame autosave (restore window size/position)
struct WindowFrameAutosave: NSViewRepresentable {
    let name: String

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            view.window?.setFrameAutosaveName(name)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}

// MARK: - Unsafe check helper for destructive confirmations
struct DestructiveConfirm {
    var title: String
    var message: String
    var actionTitle: String
}
