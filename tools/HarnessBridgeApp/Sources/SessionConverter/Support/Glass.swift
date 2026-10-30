import SwiftUI
import AppKit

/// Design-system glass surfaces for HarnessBridge.
///
/// macOS 26+ uses Liquid Glass (`.glassEffect`); macOS 13–25 and
/// "Reduce Transparency" fall back to material/solid backgrounds.
/// Light/dark both keep text on the system background layer for readability.
enum GlassStyle {
    static var reduceTransparency: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceTransparency
    }

    static var reduceMotion: Bool { Motion.reduceMotion }
}

private struct GlassFallbackBackground: View {
    var cornerRadius: CGFloat
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        shape.fill(GlassStyle.reduceTransparency
                   ? AnyShapeStyle(Color(nsColor: .windowBackgroundColor))
                   : AnyShapeStyle(.ultraThinMaterial))
            .overlay(shape.strokeBorder(Color.secondary.opacity(0.16), lineWidth: 1))
    }
}

private struct GlassCardModifier: ViewModifier {
    var cornerRadius: CGFloat = 12

    func body(content: Content) -> some View {
        Group {
            if #available(macOS 26.0, *), !GlassStyle.reduceTransparency {
                content
                    .glassEffect(.regular, in: RoundedRectangle(cornerRadius: cornerRadius,
                                                                style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .strokeBorder(.white.opacity(0.18), lineWidth: 0.8))
                    .shadow(color: .black.opacity(0.14), radius: 14, y: 5)
            } else {
                content
                    .background(GlassFallbackBackground(cornerRadius: cornerRadius))
                    .shadow(color: .black.opacity(0.08), radius: 8, y: 3)
            }
        }
    }
}

private struct GlassBarModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background {
                if #available(macOS 26.0, *), !GlassStyle.reduceTransparency {
                    Rectangle()
                        .fill(.clear)
                        .glassEffect(.regular, in: Rectangle())
                } else {
                    Rectangle()
                        .fill(GlassStyle.reduceTransparency
                              ? AnyShapeStyle(Color(nsColor: .windowBackgroundColor))
                              : AnyShapeStyle(.ultraThinMaterial))
                }
            }
            .overlay(alignment: .bottom) {
                Rectangle().fill(Color.secondary.opacity(0.12)).frame(height: 0.5)
            }
    }
}

private struct GlassSelectionCardModifier: ViewModifier {
    var selected: Bool
    var cornerRadius: CGFloat = 12

    func body(content: Content) -> some View {
        Group {
            if #available(macOS 26.0, *), !GlassStyle.reduceTransparency {
                if selected {
                    content
                        .glassEffect(.regular.tint(Color.accentColor.opacity(0.28)),
                                     in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .strokeBorder(Color.accentColor.opacity(0.55), lineWidth: 1.2))
                } else {
                    content
                        .glassEffect(.regular,
                                     in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .strokeBorder(.white.opacity(0.16), lineWidth: 0.8))
                }
            } else {
                content
                    .background(selected
                                ? AnyShapeStyle(Color.accentColor.opacity(0.12))
                                : AnyShapeStyle(GlassStyle.reduceTransparency
                                                ? Color(nsColor: .windowBackgroundColor)
                                                : Color(nsColor: .controlBackgroundColor)))
                    .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .strokeBorder(selected ? Color.accentColor.opacity(0.55) : Color.secondary.opacity(0.18),
                                      lineWidth: selected ? 1.5 : 1))
            }
        }
        .shadow(color: .black.opacity(selected ? 0.10 : 0.05), radius: 10, y: 3)
    }
}

/// Window backdrop: translucent vibrancy behind everything (macOS 13+).
struct VisionBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .underWindowBackground
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

/// Reusable glass card wrapper (use for content that needs its own panel).
struct GlassCard<Content: View>: View {
    var cornerRadius: CGFloat = 14
    let content: Content

    init(cornerRadius: CGFloat = 14, @ViewBuilder content: () -> Content) {
        self.cornerRadius = cornerRadius
        self.content = content()
    }

    var body: some View {
        content.padding(14).glassCard(cornerRadius: cornerRadius)
    }
}

/// Prominent button with glass tint on macOS 26, accent capsule fallback below.
struct GlassProminentButtonStyle: ButtonStyle {
    var tint: Color = .accentColor

    func makeBody(configuration: Configuration) -> some View {
        Group {
            if #available(macOS 26.0, *), !GlassStyle.reduceTransparency {
                configuration.label
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .glassEffect(.regular.tint(tint.opacity(0.45)), in: Capsule())
            } else {
                configuration.label
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(tint.opacity(0.85), in: Capsule())
                    .foregroundStyle(.white)
            }
        }
        .scaleEffect(configuration.isPressed && !GlassStyle.reduceMotion ? 0.97 : 1)
        .animation(Motion.quick, value: configuration.isPressed)
    }
}

extension View {
    func glassCard(cornerRadius: CGFloat = 12) -> some View {
        modifier(GlassCardModifier(cornerRadius: cornerRadius))
    }

    func glassBar() -> some View {
        modifier(GlassBarModifier())
    }

    func glassSelectionCard(selected: Bool, cornerRadius: CGFloat = 12) -> some View {
        modifier(GlassSelectionCardModifier(selected: selected, cornerRadius: cornerRadius))
    }
}
