// HarnessBridge — native macOS SwiftUI product front-end for session
// migration. All conversion semantics come from the `asi` CLI backend; this
// app only drives it and renders the results.
//
// Explicit `@main` entry point (instead of `main.swift`) so the headless
// `--self-test` / `--diagnose` modes can run without starting the GUI.
import Foundation
import SwiftUI

@main
struct Launcher {
    static func main() {
        let args = CommandLine.arguments
        if args.contains("--self-test") {
            exit(Headless.selfTest())
        }
        if args.contains("--diagnose") {
            exit(Headless.diagnose())
        }
        HarnessBridgeApp.main()
    }
}

@MainActor
enum SharedModel {
    static let shared = AppModel()
}

struct HarnessBridgeApp: App {
    var body: some Scene {
        WindowGroup("HarnessBridge — Agent Session Converter") {
            ContentView()
                .environmentObject(SharedModel.shared)
                .frame(minWidth: 1080, minHeight: 720)
        }
        .windowStyle(.titleBar)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("HarnessBridge") {
                Button("开始 / 继续迁移") { SharedModel.shared.handlePrimaryAction() }
                    .keyboardShortcut(.return, modifiers: [.command])
                Divider()
                Button("刷新当前页面") { SharedModel.shared.refreshCurrent() }
                    .keyboardShortcut("r", modifiers: [.command])
                Button("聚焦搜索") { SharedModel.shared.focusSearch() }
                    .keyboardShortcut("f", modifiers: [.command])
                Button("全选当前列表") { SharedModel.shared.handleSelectAll() }
                    .keyboardShortcut("a", modifiers: [.command])
                Button("打开输出文件夹") { SharedModel.shared.openOutputFolder() }
                    .keyboardShortcut("o", modifiers: [.command])
                Button("设置…") { SharedModel.shared.openSettingsShortcut() }
                    .keyboardShortcut(",", modifiers: [.command])
                Divider()
                Button("跳到第一个工具调用") { SharedModel.shared.jumpFirstTool() }
                    .keyboardShortcut(.upArrow, modifiers: [.command])
                Button("跳到最后一个工具调用") { SharedModel.shared.jumpLastTool() }
                    .keyboardShortcut(.downArrow, modifiers: [.command])
                Divider()
                Button("打开会话详情（Return）") { SharedModel.shared.handleReturn() }
                Button("返回 / 取消（Esc）") { SharedModel.shared.handleEscape() }
                Button("重新检测本机工具") {
                    Task { await SharedModel.shared.refreshHarnesses() }
                }
                Button("浏览会话") { SharedModel.shared.openSessionsBrowser() }
                Button("迁移历史") { SharedModel.shared.page = .history }
            }
        }
    }
}
