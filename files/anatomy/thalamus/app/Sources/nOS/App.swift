// nOS.app: the estate's state in the menu bar, read over the thalamus socket, and Iris in a window.
// It writes nothing: halt and pause round-trip through the medulla (increment 2), never a file here.
import AppKit
import Darwin
import NOSState
import SwiftUI
import WebKit

/// One `{"t":"state"}` round trip on the thalamus socket; nil when it does not answer in 2 s.
func readState() -> EstateState? {
    let env = ProcessInfo.processInfo.environment["THALAMUS_SOCKET"] ?? ""
    let path = env.isEmpty ? NSHomeDirectory() + "/.nos/thalamus.sock" : env
    let fd = socket(AF_UNIX, SOCK_STREAM, 0)
    guard fd >= 0 else { return nil }
    defer { close(fd) }
    var tv = timeval(tv_sec: 2, tv_usec: 0)
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
    var addr = sockaddr_un()
    addr.sun_family = sa_family_t(AF_UNIX)
    let bytes = Array(path.utf8)
    guard bytes.count < MemoryLayout.size(ofValue: addr.sun_path) else { return nil }
    withUnsafeMutableBytes(of: &addr.sun_path) { $0.copyBytes(from: bytes) }
    let rc = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
    }
    guard rc == 0 else { return nil }
    let req = Array("{\"t\":\"state\"}\n".utf8)
    guard write(fd, req, req.count) == req.count else { return nil }
    var line = [UInt8](), chunk = [UInt8](repeating: 0, count: 65536)
    while !line.contains(10) {
        let n = read(fd, &chunk, chunk.count)
        guard n > 0, line.count + n <= 1 << 20 else { return nil }  // one line is at most 1 MiB
        line += chunk[0..<n]
    }
    return try? EstateState.decode(Data(line.prefix { $0 != 10 }))
}

@MainActor final class Estate: ObservableObject {
    @Published var state: EstateState?  // nil: the medulla did not answer, never green
    private var timer: Timer?

    init() {
        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.poll() }
        }
    }

    func poll() {
        Task.detached {
            let s = readState()
            await MainActor.run { self.state = s }
        }
    }
}

func word(_ b: Bool?, on: String, off: String) -> String { b.map { $0 ? on : off } ?? "UNKNOWN" }

struct MenuView: View {
    @ObservedObject var estate: Estate
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if let s = estate.state {
            Text("Halt: " + word(s.halt.on, on: "ON" + (s.halt.since.map { " since \($0)" } ?? ""), off: "off"))
            if let r = s.halt.reason { Text("  " + r) }
            Text("Loops paused: " + word(s.loops_paused.on, on: "yes", off: "no"))
            Divider()
            ForEach(s.organs, id: \.label) { o in Text("\(o.name): " + word(o.running, on: "running", off: "stopped")) }
        } else {
            Text("medulla unreachable")
        }
        Divider()
        Button(estate.state?.halt.on == true ? "Resume" : "Halt") {}.disabled(true)
        Text("Halt/Resume: coming in increment 2")
        Divider()
        Button("Iris") { openWindow(id: "iris"); NSApp.activate(ignoringOtherApps: true) }
        Button("Quit nOS") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}

/// The face URL: the `NOSFaceURL` default (defaults write eu.thisisait.nos.app NOSFaceURL ...), else Info.plist's.
func faceURL() -> URL? {
    let s = UserDefaults.standard.string(forKey: "NOSFaceURL") ?? Bundle.main.object(forInfoDictionaryKey: "NOSFaceURL") as? String
    return s.flatMap(URL.init(string:))
}

struct WebView: NSViewRepresentable {
    let url: URL
    func makeNSView(context: Context) -> WKWebView {
        let v = WKWebView()
        v.load(URLRequest(url: url))
        return v
    }
    func updateNSView(_ v: WKWebView, context: Context) {}
}

@main struct NOSApp: App {
    @StateObject private var estate = Estate()

    var body: some Scene {
        MenuBarExtra {
            MenuView(estate: estate)
        } label: {
            let on = estate.state?.halt.on  // unreachable or unreadable: a question mark, never the calm icon
            Image(systemName: on == nil ? "questionmark.circle" : on == true ? "stop.circle.fill" : "circle.hexagongrid")
        }
        Window("Iris", id: "iris") {
            if let url = faceURL() { WebView(url: url).frame(minWidth: 900, minHeight: 600) } else { Text("NOSFaceURL is not set") }
        }
    }
}
