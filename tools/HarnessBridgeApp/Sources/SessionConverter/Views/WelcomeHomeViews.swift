import SwiftUI

// MARK: - Welcome / first launch
struct WelcomeView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack(spacing: 14) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 16)
                                .fill(LinearGradient(colors: [.blue, .purple],
                                                     startPoint: .topLeading, endPoint: .bottomTrailing))
                                .frame(width: 60, height: 60)
                            Image(systemName: "arrow.triangle.2.circlepath")
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        VStack(alignment: .leading, spacing: 3) {
                            Text("欢迎使用 HarnessBridge")
                                .font(.largeTitle.weight(.bold))
                            Text("Agent Session Converter · 在不同 AI 编程工具之间安全地搬运会话历史。")
                                .font(.title3)
                                .foregroundStyle(.secondary)
                        }
                    }

                    Text("只需几步：选择来源 → 选择会话 → 选择目标 → 开始迁移。原始会话永远只读，迁移结果会先保存在你选择的文件夹。")
                        .font(.callout)
                        .foregroundStyle(.secondary)

                    CardBox(title: "本机检测", subtitle: model.detecting ? "正在检测…" : nil,
                            systemImage: "sparkle.magnifyingglass") {
                        if model.detecting && model.harnesses.isEmpty && model.backendError == nil {
                            VStack(alignment: .leading, spacing: 10) {
                                HStack(spacing: 10) {
                                    ProgressView().controlSize(.small)
                                    Text("正在查找本机已安装的 AI 编程工具，请稍候…").foregroundStyle(.secondary)
                                }
                                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 8)], spacing: 8) {
                                    ForEach(0..<4, id: \.self) { _ in SkeletonHarnessCard() }
                                }
                            }
                        } else if let error = model.backendError {
                            VStack(alignment: .leading, spacing: 6) {
                                Label(error, systemImage: "exclamationmark.triangle.fill")
                                    .foregroundStyle(.orange)
                                Button("打开设置") { model.page = .settings }
                            }
                        } else {
                            VStack(alignment: .leading, spacing: 10) {
                                Text(L10n.found(tools: model.detectedHarnesses.count, sessions: model.totalSessionCount)).font(.title3)
                                HStack(spacing: 8) {
                                    if let time = model.detectCacheTime {
                                        Text(L10n.lastDetected(Fmt.date(time)))
                                            .font(.caption2).foregroundStyle(.secondary)
                                    }
                                    if model.detecting {
                                        HStack(spacing: 4) {
                                            ProgressView().controlSize(.mini)
                                            Text("刷新中…").font(.caption2).foregroundStyle(.secondary)
                                        }
                                    }
                                }
                                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 8)], spacing: 8) {
                                    ForEach(model.harnesses.filter { $0.detected }) { harness in
                                        HStack(spacing: 6) {
                                            Circle().fill(Color(hex: harness.colorHex)).frame(width: 8, height: 8)
                                            Text(harness.name).font(.callout)
                                            Spacer()
                                            Text("\(harness.sessionCount)").font(.caption.monospaced())
                                                .foregroundStyle(.secondary)
                                        }
                                        .padding(8)
                                        .background(Color(hex: harness.colorHex).opacity(0.10))
                                        .clipShape(RoundedRectangle(cornerRadius: 8))
                                    }
                                }
                                if model.detectedHarnesses.isEmpty {
                                    Text("暂未检测到已安装的工具。你可以先用「设置」手动指定工具所在目录，或继续体验导出功能。")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Button {
                                    Task { await model.refreshHarnesses() }
                                } label: {
                                    Label("重新检测", systemImage: "arrow.clockwise")
                                }
                                .controlSize(.small)
                            }
                        }
                    }

                    CardBox(title: "保存位置", subtitle: "迁移生成的文件会保存在这里（不会修改原始会话）",
                            systemImage: "folder") {
                        HStack(spacing: 10) {
                            Text(model.outputDir)
                                .font(.callout.monospaced())
                                .lineLimit(1)
                                .textSelection(.enabled)
                            Spacer()
                            Button("选择文件夹…") { model.chooseOutputDirectory() }
                        }
                    }

                    HStack(spacing: 12) {
                        Button {
                            model.completeWelcome()
                        } label: {
                            Label("开始使用", systemImage: "arrow.right.circle.fill")
                                .font(.headline)
                                .frame(minWidth: 150)
                        }
                        .buttonStyle(GlassProminentButtonStyle())
                        .controlSize(.large)
                        .disabled(model.detecting)
                        Spacer()
                        Text("所有操作都可以随时在设置里重新查看本页。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(40)
                .frame(maxWidth: 860)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Home / overview
struct HomeView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("你好 👋")
                            .font(.largeTitle.weight(.bold))
                        Text("这是你本机的会话总览。选择一种方式开始吧。")
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button {
                        Task { await model.refreshHarnesses() }
                    } label: {
                        Label("刷新检测", systemImage: "arrow.clockwise")
                    }
                    .disabled(model.detecting)
                }

                HStack(spacing: 12) {
                    primaryButton("迁移会话", icon: "arrow.right.circle.fill",
                                  subtitle: "一步步把会话搬到另一个工具") {
                        model.migrateFromHome()
                    }
                    primaryButton("一键迁移", icon: "square.stack.3d.up.fill",
                                  subtitle: "把其他所有工具的会话一次迁到指定目标") {
                        model.openMigrateAll()
                    }
                    primaryButton("浏览会话", icon: "list.bullet.rectangle",
                                  subtitle: "查看本机各工具的全部会话") {
                        model.openSessionsBrowser()
                    }
                }

                CardBox(title: "本机工具", subtitle: "点击卡片直接用该工具开始迁移",
                        systemImage: "square.grid.2x2") {
                    if model.harnesses.isEmpty {
                        if model.detecting {
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 12)], spacing: 12) {
                                ForEach(0..<4, id: \.self) { _ in SkeletonHarnessCard() }
                            }
                        } else {
                            EmptyHint(icon: "sparkle.magnifyingglass",
                                      text: "尚未检测到工具，请检查设置",
                                      actionTitle: "重新检测") {
                                Task { await model.refreshHarnesses() }
                            }
                        }
                    } else {
                        if model.detecting {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text(L(model.detectionNote)).font(.caption).foregroundStyle(.secondary)
                                Spacer()
                            }
                        }
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 12)], spacing: 12) {
                            ForEach(model.harnesses) { harness in
                                HarnessCardView(harness: harness) {
                                    if harness.sessionCount > 0 {
                                        model.startWizard(sourceID: harness.id)
                                    }
                                }
                            }
                        }
                    }
                }

                CardBox(title: "最近迁移", systemImage: "clock.arrow.circlepath") {
                    if model.recentMigrations.isEmpty {
                        EmptyHint(text: "还没有迁移记录。完成一次迁移后，记录会显示在这里。",
                                  actionTitle: "开始迁移") {
                            model.migrateFromHome()
                        }
                    } else {
                        VStack(spacing: 0) {
                            ForEach(model.recentMigrations) { record in
                                MigrationRowView(record: record)
                                Divider()
                            }
                        }
                        Button {
                            model.page = .history
                        } label: {
                            Label("查看全部历史", systemImage: "arrow.right")
                        }
                        .controlSize(.small)
                    }
                }
            }
            .padding(20)
        }
    }

    private func primaryButton(_ title: String, icon: String, subtitle: String,
                               action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 22))
                    .foregroundStyle(.tint)
                Text(L(title)).font(.headline)
                Text(L(subtitle)).font(.caption).foregroundStyle(.secondary)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, minHeight: 116, alignment: .leading)
            .padding(14)
            .glassSelectionCard(selected: false, cornerRadius: 12)
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.accentColor.opacity(0.25)))
            .contentShape(Rectangle())
        }
        .buttonStyle(PressScaleButtonStyle())
        .hoverLift(scale: 1.01, shadow: 0.10)
    }
}
