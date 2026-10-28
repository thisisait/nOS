// swift-tools-version:6.0
// nOS.app: the medulla's face on the desktop. Built with Command Line Tools only (build-app.sh).
import PackageDescription

let package = Package(
    name: "nOS",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "NOSState"),
        .executableTarget(name: "nOS", dependencies: ["NOSState"]),
        // The contract gate's decoder run; a plain executable: CLT's Testing module is not on the default path.
        .executableTarget(name: "state-check", dependencies: ["NOSState"]),
    ]
)
