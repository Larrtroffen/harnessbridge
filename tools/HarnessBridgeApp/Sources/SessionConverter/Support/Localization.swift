// In-app localization for HarnessBridge.
//
// Source strings are Simplified Chinese (the app's original language). The
// English and zh-Hans `.lproj/Localizable.strings` files are copied into the
// app bundle by build.sh. Literal SwiftUI `Text`/`Button`/`Label` keys
// localize automatically through the environment locale; `LanguageManager.t`
// covers dynamic strings used in menus, window titles and pickers.
import Foundation
import SwiftUI

enum AppLanguage: String, CaseIterable, Identifiable {
    case system = "system"
    case english = "en"
    case simplifiedChinese = "zh-Hans"

    var id: String { rawValue }

    /// Locale used for SwiftUI's LocalizedStringKey lookup.
    var resolvedCode: String {
        let manager = LanguageManager.shared
        switch self {
        case .english: return "en"
        case .simplifiedChinese: return "zh-Hans"
        case .system:
            let raw = Locale.current.language.languageCode?.identifier ?? "en"
            return raw.hasPrefix("zh") ? "zh-Hans" : "en"
        }
    }

    var locale: Locale {
        Locale(identifier: resolvedCode)
    }

    var displayName: String {
        switch self {
        case .system: return LanguageManager.shared.t("跟随系统")
        case .english: return "English"
        case .simplifiedChinese: return "简体中文"
        }
    }
}

final class LanguageManager: ObservableObject {
    static let shared = LanguageManager()

    @Published var language: AppLanguage {
        didSet {
            guard !envOverride else { return }
            defaults.set(language.rawValue, forKey: Self.defaultsKey)
        }
    }

    private static let defaultsKey = "HBLanguage"
    private let defaults = UserDefaults.standard
    private let envOverride: Bool

    private init() {
        let env = ProcessInfo.processInfo.environment["HB_LANGUAGE"]?
            .trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        envOverride = !(env?.isEmpty ?? true)
        if let env, !env.isEmpty {
            switch env {
            case "en", "en-us", "english": language = .english
            case "zh", "zh-hans", "zh-cn", "chinese": language = .simplifiedChinese
            default: language = .system
            }
        } else if let raw = defaults.string(forKey: Self.defaultsKey),
                  let saved = AppLanguage(rawValue: raw) {
            language = saved
        } else {
            language = .system
        }
    }

    /// Locale for the selected language (never returns an unsupported locale).
    var locale: Locale { language.locale }
    var resolvedCode: String { language.resolvedCode }
    var isChinese: Bool { resolvedCode == "zh-Hans" }

    /// Force a lookup in the selected `.lproj` bundle. Used where SwiftUI's
    /// automatic LocalizedStringKey resolution is unavailable (App commands,
    /// window titles, picker labels built from runtime values).
    func t(_ key: String) -> String {
        let code = resolvedCode
        if code == "zh-Hans" {
            return key
        }
        if let path = Bundle.main.path(forResource: code, ofType: "lproj"),
           let bundle = Bundle(path: path) {
            return bundle.localizedString(forKey: key, value: key, table: nil)
        }
        return key
    }

    /// Translate generated/runtime text. Exact keys win; then a small set of
    /// count/status patterns produced by interpolation in AppModel/UI code.
    func localizeDynamic(_ value: String) -> String {
        guard !value.isEmpty, !isChinese else { return value }
        let direct = t(value)
        if direct != value { return direct }
        let patterns: [(String, String)] = [
            ("^(\\d+) 个会话$", "$1 sessions"),
            ("^(\\d+) 个工具$", "$1 tools"),
            ("^共 (\\d+) 个会话$", "$1 sessions total"),
            ("^全部 (\\d+) 个会话$", "All $1 sessions"),
            ("^已选择最近 (\\d+) 个会话$", "Selected the last $1 sessions"),
            ("^已选择全部 (\\d+) 个会话$", "Selected all $1 sessions"),
            ("^已检测 (\\d+) 个工具 · (\\d+) 个会话$", "Detected $1 tools · $2 sessions"),
            ("^发现 (\\d+) 个工具，共 (\\d+) 个会话$", "Found $1 tools, $2 sessions"),
            ("^最近 (.+)$", "Latest $1"),
            ("^暂无会话$", "No sessions yet"),
            ("^未检测到$", "Not detected"),
            ("^已安装 · 暂无会话$", "Installed · no sessions yet"),
            ("^会话库：(.+)$", "Session store: $1"),
            ("^(.+) 个会话 · (.+)$", "$1 sessions · $2"),
            ("^共 (\\d+) 个会话：成功 (\\d+)，失败 (\\d+)$", "$1 sessions: $2 succeeded, $3 failed"),
            ("^迁移完成，共 (\\d+) 个会话$", "Migration complete: $1 sessions"),
            ("^迁移完成：(\\d+) 个会话成功$", "Migration complete: $1 sessions succeeded"),
            ("^\\(?(\\d+)/(\\d+) 成功\\)?$", "$1/$2 succeeded"),
            ("^已导出 (\\d+) / (\\d+) 个会话$", "Exported $1 / $2 sessions"),
            ("^已选 (\\d+) / 共 (\\d+)（筛选后）$", "Selected $1 / $2 (filtered)"),
            ("^共 (\\d+) 个会话 · 显示 (\\d+)$", "$1 sessions · showing $2"),
            ("^步骤 (\\d+) / 5$", "Step $1 / 5"),
            ("^目标：(.+)$", "Target: $1"),
            ("^源文件：(.+)$", "Source file: $1"),
            ("^源：(.+)$", "Source: $1"),
            ("^· 显示 (\\d+) / 共 (\\d+) 条匹配$", "· showing $1 / $2 matches"),
            ("^运行日志（(\\d+) 条）$", "Run log ($1 entries)"),
            ("^正在检测…$", "Detecting…"),
            ("^刷新中…$", "Refreshing…"),
            ("^准备就绪$", "Ready"),
            ("^已连接（自动检测）$", "Connected (auto-detected)"),
            ("^已从旧版应用（(.+)）迁移：(.+)（旧数据保留）$", "Migrated from legacy app ($1): $2 (old data retained)"),
            ("^已选择最近 (\\d+) 个会话$", "Selected the last $1 sessions"),
        ]
        if let re = try? NSRegularExpression(pattern: "") { _ = re } // keep Foundation linked
        var out = value
        for (pattern, template) in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern),
               let match = regex.firstMatch(in: out, range: NSRange(out.startIndex..., in: out)) {
                var result = template
                for i in stride(from: match.numberOfRanges - 1, through: 1, by: -1) {
                    if let r = Range(match.range(at: i), in: out) {
                        result = result.replacingOccurrences(of: "$\(i)", with: String(out[r]))
                    }
                }
                out = result
                break
            }
        }
        return out
    }
}


/// Localize a dynamic source string (exact `.strings` lookup, then a few
/// common Chinese count/status patterns that are generated at runtime).
func L(_ key: String) -> String {
    LanguageManager.shared.localizeDynamic(key)
}

enum L10n {
    static var isChinese: Bool { LanguageManager.shared.isChinese }

    static func sessions(_ n: Int) -> String {
        isChinese ? "\(n) 个会话" : "\(n) session\(n == 1 ? "" : "s")"
    }

    static func tools(_ n: Int) -> String {
        isChinese ? "\(n) 个工具" : "\(n) tool\(n == 1 ? "" : "s")"
    }

    static func detected(tools: Int, sessions: Int) -> String {
        isChinese ? "已检测 \(tools) 个工具 · \(sessions) 个会话"
                  : "Detected \(tools) tools · \(sessions) sessions"
    }

    static func found(tools: Int, sessions: Int) -> String {
        isChinese ? "发现 \(tools) 个工具，共 \(sessions) 个会话"
                  : "Found \(tools) tools with \(sessions) sessions"
    }

    static func lastDetected(_ date: String) -> String {
        isChinese ? "上次检测：\(date)" : "Last detected: \(date)"
    }
}
