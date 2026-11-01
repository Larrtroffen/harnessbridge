import SwiftUI

// MARK: - shared small views (product UI)

struct StatusPill: View {
    let text: String
    var color: Color = .secondary
    var body: some View {
        Text(L(text))
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(color.opacity(0.16))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}

struct EvidenceBadge: View {
    let evidence: String?
    var body: some View {
        let raw = (evidence ?? "—").uppercased()
        let color: Color
        if raw.contains("CONSTRUCTED") { color = .purple }
        else if raw.contains("LOW") { color = .orange }
        else if raw.contains("REAL") { color = .blue }
        else if raw.contains("NATIVE") { color = .green }
        else { color = .secondary }
        return StatusPill(text: raw, color: color)
    }
}

struct CardBox<Content: View>: View {
    var title: String? = nil
    var subtitle: String? = nil
    var systemImage: String = "square.grid.2x2"
    let content: Content

    init(title: String? = nil, subtitle: String? = nil,
         systemImage: String = "square.grid.2x2",
         @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Label(L(title), systemImage: systemImage)
                        .font(.headline)
                    if let subtitle {
                        Text(L(subtitle)).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 12)
    }
}

struct InfoRow: View {
    let label: String
    let value: String
    var mono = false
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(L(label))
                .foregroundStyle(.secondary)
                .frame(width: 92, alignment: .leading)
            Text(L(value))
                .font(mono ? .caption.monospaced() : .callout)
                .textSelection(.enabled)
                .lineLimit(3)
            Spacer(minLength: 0)
        }
        .font(.callout)
    }
}

struct EmptyHint: View {
    var icon: String = "tray"
    let text: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 30))
                .foregroundStyle(.secondary)
            Text(L(text))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                Button(L(actionTitle), action: action).controlSize(.regular)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(30)
    }
}

struct HarnessCardView: View {
    let harness: HarnessInfo
    var action: (() -> Void)? = nil

    private var color: Color { Color(hex: harness.colorHex) }

    var body: some View {
        Button {
            action?()
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    HarnessLogoView(harnessID: harness.id, size: 42)
                    Spacer()
                    Circle()
                        .fill(harness.sessionCount > 0 ? Color.green : Color.secondary.opacity(0.35))
                        .frame(width: 8, height: 8)
                }
                Text(harness.name)
                    .font(.headline)
                    .lineLimit(1)
                Text(harness.summaryText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Text(harness.recentText)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                if !harness.storePath.isEmpty {
                    Text(L("会话库：") + Fmt.shortPath(harness.storePath, limit: 34))
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if harness.installSupported {
                    HStack(spacing: 4) {
                        StatusPill(text: harness.installExperimental ? "实验性写入" : "支持直接迁移",
                                   color: harness.installExperimental ? .orange : .green)
                        if let how = harness.howToSee, !how.isEmpty {
                            Text(L(how)).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassSelectionCard(selected: false, cornerRadius: 12)
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(color.opacity(0.28)))
            .contentShape(Rectangle())
        }
        .buttonStyle(PressScaleButtonStyle())
        .hoverLift()
        .help("点击使用 \(harness.name) 开始迁移")
    }
}

struct StepIndicator: View {
    let steps: [String]
    let current: Int

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, title in
                let number = index + 1
                HStack(spacing: 6) {
                    ZStack {
                        Circle()
                            .fill(number <= current ? Color.accentColor : Color.secondary.opacity(0.2))
                            .frame(width: 24, height: 24)
                        if number < current {
                            Image(systemName: "checkmark")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.white)
                        } else {
                            Text("\(number)")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(number == current ? .white : .secondary)
                        }
                    }
                    Text(L(title))
                        .font(.caption)
                        .foregroundStyle(number == current ? .primary : .secondary)
                        .lineLimit(1)
                }
                if index < steps.count - 1 {
                    Rectangle()
                        .fill(number < current ? Color.accentColor.opacity(0.6) : Color.secondary.opacity(0.2))
                        .frame(height: 2)
                        .padding(.horizontal, 6)
                }
            }
        }
        .padding(.vertical, 6)
    }
}

struct ProgressBar: View {
    let value: Double
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 4)
                    .fill(Color.secondary.opacity(0.18))
                RoundedRectangle(cornerRadius: 4)
                    .fill(Color.accentColor)
                    .frame(width: max(4, geo.size.width * min(max(value, 0), 1)))
            }
        }
        .frame(height: 8)
    }
}

struct LogRowView: View {
    let entry: LogEntry
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                Circle().fill(entry.isOK ? Color.green : Color.red).frame(width: 7, height: 7)
                Text(entry.command).font(.caption.monospaced()).lineLimit(1)
                Spacer()
                Text(entry.isOK ? "成功" : "失败")
                    .font(.caption2)
                    .foregroundStyle(entry.isOK ? .green : .red)
                if entry.duration > 0 {
                    Text(Fmt.duration(entry.duration)).font(.caption2).foregroundStyle(.secondary)
                }
            }
            let detail = entry.stderrTail.isEmpty ? entry.stdoutTail : entry.stderrTail
            if !detail.isEmpty {
                Text(detail)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }
        }
        .padding(.vertical, 3)
    }
}

struct MigrationRowView: View {
    let record: MigrationRecord
    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                Circle().fill(Color.accentColor.opacity(0.14)).frame(width: 32, height: 32)
                Image(systemName: record.failCount == 0 ? "checkmark" : "exclamationmark")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(record.failCount == 0 ? .green : .orange)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text("\(record.sourceName) → \(record.targetName)")
                    .font(.callout.weight(.medium))
                Text("\(Fmt.date(record.date)) · \(record.sessionCount) 个会话 · \(record.statusText)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(record.isSelfTest ? "自检" : "")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 3)
    }
}

// MARK: - Color hex helper
extension Color {
    init(hex: String) {
        let cleaned = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var value: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&value)
        let r, g, b: UInt64
        if cleaned.count == 6 {
            r = (value >> 16) & 0xFF
            g = (value >> 8) & 0xFF
            b = value & 0xFF
        } else {
            r = 100; g = 116; b = 139
        }
        self.init(.sRGB, red: Double(r) / 255.0, green: Double(g) / 255.0,
                  blue: Double(b) / 255.0, opacity: 1)
    }
}
