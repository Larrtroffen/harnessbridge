import SwiftUI
import AppKit

/// Displays a Harness logo from `Contents/Resources/Logos/<id>.png`
/// (packaged by build.sh from Assets/Logos or the workspace assets/harness-logos).
/// Falls back to a branded letter tile when no raster asset is available.
struct HarnessLogoView: View {
    let harnessID: String
    var size: CGFloat = 28
    var cornerRadius: CGFloat? = nil

    var body: some View {
        Group {
            if let asset = HarnessLogoStore.shared.asset(for: harnessID) {
                // Adaptive tile: dark glyphs (e.g. black-on-transparent logos) get a light
                // backdrop, light glyphs keep the dark app tile — guarantees contrast on any UI theme.
                ZStack {
                    RoundedRectangle(cornerRadius: cornerRadius ?? size * 0.26)
                        .fill(asset.isDark ? Color(white: 0.95) : Color(white: 0.12))
                    Image(nsImage: asset.image)
                        .resizable()
                        .interpolation(.high)
                        .scaledToFit()
                        .padding(size * 0.09)
                }
                .frame(width: size, height: size)
                .overlay(
                    RoundedRectangle(cornerRadius: cornerRadius ?? size * 0.26)
                        .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
                )
            } else {
                fallback
            }
        }
        .frame(width: size, height: size)
    }

    private var fallback: some View {
        let color = Color(hex: HarnessCatalog.color(for: harnessID))
        let letter = HarnessLogoStore.initial(for: harnessID)
        return ZStack {
            RoundedRectangle(cornerRadius: cornerRadius ?? size * 0.26)
                .fill(LinearGradient(colors: [color.opacity(0.95), color.opacity(0.65)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
            Text(letter)
                .font(.system(size: size * 0.44, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
        }
    }
}

/// Loads and caches harness logo raster assets (never fetches from the network).
final class HarnessLogoStore: @unchecked Sendable {
    static let shared = HarnessLogoStore()

    struct LogoAsset {
        let image: NSImage
        let isDark: Bool
    }

    private let lock = NSLock()
    private var cache: [String: LogoAsset?] = [:]

    /// Canonical alias map: different adapter ids may point at the same brand.
    private static let aliases: [String: String] = [
        "claude-code": "claude", "claude_code": "claude",
        "kimi-code": "kimi", "kimi_code": "kimi",
        "kilo": "kilo-code", "kilo_code": "kilo-code",
        "factory-droid": "droid", "factory_droid": "droid",
        "open-code": "opencode", "open_code": "opencode",
        "deepseek-harness": "dsh", "deepseek": "dsh",
        "oh-my-pi": "omp",
        "antigravity-cli": "antigravity",
        "vib(e)": "vibe", "vib": "vibe",
        "mini-swe": "mini-swe-agent",
        "github-copilot": "copilot", "copilot-cli": "copilot",
        "gemini-cli": "gemini", "cursor-cli": "cursor", "qwen-code": "qwen",
        "roo-code": "roo", "codebuff-ai": "codebuff",
    ]

    static func canonical(_ id: String) -> String {
        let lowered = id.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if let alias = aliases[lowered] { return alias }
        return lowered
    }

    static func initial(for id: String) -> String {
        let name = HarnessCatalog.name(for: canonical(id))
        if let first = name.first, first.isLetter { return String(first).uppercased() }
        return String(canonical(id).prefix(1)).uppercased()
    }

    func asset(for harnessID: String) -> LogoAsset? {
        let key = Self.canonical(harnessID)
        lock.lock()
        if let cached = cache[key] {
            lock.unlock()
            return cached
        }
        lock.unlock()
        let asset = Self.loadAsset(for: key)
        lock.lock()
        cache[key] = asset
        lock.unlock()
        return asset
    }

    private static func loadAsset(for key: String) -> LogoAsset? {
        let candidates = [key, key.replacingOccurrences(of: "-", with: "_"),
                          key.replacingOccurrences(of: "_", with: "-")]
        for directory in logoDirectories() {
            let index = rasterIndex(in: directory)
            for name in candidates {
                if let url = index[name], let image = NSImage(contentsOf: url) {
                    return LogoAsset(image: image, isDark: isDarkGlyph(image))
                }
            }
        }
        return nil
    }

    /// Average alpha-weighted luminance of visible pixels; dark glyphs need a light tile.
    private static func isDarkGlyph(_ image: NSImage) -> Bool {
        guard let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              rep.pixelsWide > 0, rep.pixelsHigh > 0 else { return false }
        let stepX = max(1, rep.pixelsWide / 16)
        let stepY = max(1, rep.pixelsHigh / 16)
        var total = 0.0, weight = 0.0
        for y in stride(from: 0, to: rep.pixelsHigh, by: stepY) {
            for x in stride(from: 0, to: rep.pixelsWide, by: stepX) {
                guard let c = rep.colorAt(x: x, y: y) else { continue }
                let a = c.alphaComponent
                if a < 0.15 { continue }
                let lum = 0.2126 * c.redComponent + 0.7152 * c.greenComponent + 0.0722 * c.blueComponent
                total += lum * a
                weight += a
            }
        }
        return weight > 0 && (total / weight) < 0.45
    }

    /// Recursively indexes raster assets (max depth 2) by lowercased filename
    /// without extension, so both Logos/<id>.png and Logos/raw/<id>.png work.
    private static func rasterIndex(in directory: URL) -> [String: URL] {
        var index: [String: URL] = [:]
        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: directory.path) else { return index }
        let keys: [URLResourceKey] = [.isDirectoryKey, .nameKey]
        guard let enumerator = fileManager.enumerator(at: directory,
                                                      includingPropertiesForKeys: keys,
                                                      options: [.skipsHiddenFiles],
                                                      errorHandler: nil) else { return index }
        var visited = 0
        for case let url as URL in enumerator {
            visited += 1
            if visited > 500 { break }
            let values = try? url.resourceValues(forKeys: Set(keys))
            if values?.isDirectory == true {
                // limit recursion depth to 2 levels
                let depth = url.pathComponents.count - directory.pathComponents.count
                if depth >= 2 { enumerator.skipDescendants() }
                continue
            }
            let ext = url.pathExtension.lowercased()
            guard ["png", "jpg", "jpeg", "tiff", "heic"].contains(ext) else { continue }
            let name = url.deletingPathExtension().lastPathComponent.lowercased()
            index[name] = url
            index[name.replacingOccurrences(of: "_", with: "-")] = url
            index[name.replacingOccurrences(of: "-", with: "_")] = url
        }
        return index
    }

    /// Search order: app bundle Resources/Logos → workspace assets/harness-logos
    /// → repository Assets/Logos (dev builds). Never touches the network.
    private static func logoDirectories() -> [URL] {
        var dirs: [URL] = []
        if let resource = Bundle.main.resourceURL {
            dirs.append(resource.appendingPathComponent("Logos", isDirectory: true))
        }
        if let workspace = Paths.discoverWorkspace() {
            dirs.append(workspace.appendingPathComponent("assets/harness-logos", isDirectory: true))
            dirs.append(workspace.appendingPathComponent("tools/SessionConverterApp/Assets/Logos", isDirectory: true))
        }
        dirs.append(URL(fileURLWithPath: "Assets/Logos", isDirectory: true))
        return dirs
    }
}
