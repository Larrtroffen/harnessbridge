// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "HarnessBridge",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "HarnessBridge",
            path: "Sources/SessionConverter"
        )
    ]
)
