// swift-tools-version: 6.2
// Sage's native app uses only Apple frameworks to keep its idle footprint and supply chain small.

import PackageDescription

let package = Package(
    name: "Sage",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "Sage", targets: ["SageApp"]),
    ],
    targets: [
        .target(name: "SageRuntime"),
        .executableTarget(name: "SageApp", dependencies: ["SageRuntime"]),
        .testTarget(name: "SageRuntimeTests", dependencies: ["SageRuntime"]),
    ]
)
