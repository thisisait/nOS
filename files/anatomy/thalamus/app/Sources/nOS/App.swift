// nOS.app: the estate's state in the menu bar, read over the thalamus socket, and Iris in a window.
// It writes nothing itself: a halt is asked of the medulla over the socket, which checks the person and
// this signed exe (NOS_DECIDER_EXES), writes the set-point and tells Wing. Never a file here.
import AppKit
import Darwin
import NOSState
import SwiftUI
import WebKit

/// One request line on the thalamus socket, its one answer line; nil when it does not answer in `secs`.
func ask(_ request: String, secs: Int = 2) -> Data? {
    let env = ProcessInfo.processInfo.environment["THALAMUS_SOCKET"] ?? ""
    let path = env.isEmpty ? NSHomeDirectory() + "/.nos/thalamus.sock" : env
    let fd = socket(AF_UNIX, SOCK_STREAM, 0)
    guard fd >= 0 else { return nil }
    defer { close(fd) }
    var tv = timeval(tv_sec: secs, tv_usec: 0)
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
    let req = Array((request + "\n").utf8)
    guard write(fd, req, req.count) == req.count else { return nil }
    var line = [UInt8](), chunk = [UInt8](repeating: 0, count: 65536)
    while !line.contains(10) {
        let n = read(fd, &chunk, chunk.count)
        guard n > 0, line.count + n <= 1 << 20 else { return nil }  // one line is at most 1 MiB
        line += chunk[0..<n]
    }
    return Data(line.prefix { $0 != 10 })
}

func readState() -> EstateState? { ask(#"{"t":"state"}"#).flatMap { try? EstateState.decode($0) } }

/// Halt or lift it through the medulla; what it said, in words. 15 s: it waits on Wing's record (10 s).
func setHalt(_ on: Bool) -> String {
    guard let d = ask(on ? #"{"t":"halt","reason":"nOS.app"}"# : #"{"t":"lift_halt"}"#, secs: 15),
          let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return "the medulla did not answer: nothing changed" }
    if j["t"] as? String == "refused" { return "refused: \(j["reason"] as? String ?? "no reason given")" }
    let act = j["act"] as? [String: Any]
    let what = on ? "Halted" : "Resumed"
    return act?["recorded"] as? Bool == true ? "\(what); Wing recorded it" : "\(what); NOT recorded: \(act?["why"] as? String ?? "?")"
}

@MainActor final class Estate: ObservableObject {
    @Published var state: EstateState?  // nil: the medulla did not answer, never green
    @Published var said: String?        // the last halt/resume answer
    private var timer: Timer?

    init() {
        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.poll() }
        }
    }

    /// Asked twice on purpose: a halt holds every Pulse job, a native dialog is the confirmation.
    func toggleHalt() {
        let on = state?.halt.on != true
        let alert = NSAlert()
        alert.messageText = on ? "Halt every Pulse job?" : "Lift the halt?"
        alert.informativeText = on ? "Nothing scheduled runs until you resume." : "Scheduled jobs start firing again."
        alert.addButton(withTitle: on ? "Halt" : "Resume"); alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        Task.detached {
            let words = setHalt(on)
            await MainActor.run { self.said = words; self.poll() }
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
        Button(estate.state?.halt.on == true ? "Resume…" : "Halt…") { estate.toggleHalt() }
            .disabled(estate.state?.halt.on == nil)  // unknown: neither verb is honest
        if let w = estate.said { Text(w) }
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
    func makeCoordinator() -> Failure { Failure() }
    func makeNSView(context: Context) -> WKWebView {
        let v = WKWebView()
        v.navigationDelegate = context.coordinator
        v.load(URLRequest(url: url))
        return v
    }
    func updateNSView(_ v: WKWebView, context: Context) {}

    /// A load that fails is said in the window, never a blank page (2026-10-28: a wrong host showed white).
    final class Failure: NSObject, WKNavigationDelegate {
        func webView(_ v: WKWebView, didFailProvisionalNavigation _: WKNavigation!, withError e: Error) { say(v, e) }
        func webView(_ v: WKWebView, didFail _: WKNavigation!, withError e: Error) { say(v, e) }
        private func say(_ v: WKWebView, _ e: Error) {
            let url = (e as NSError).userInfo[NSURLErrorFailingURLStringErrorKey] as? String ?? ""
            let esc = { (s: String) in s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;") }
            v.loadHTMLString("<body style='font:14px -apple-system;padding:2em'><h3>Iris could not load</h3><p>\(esc(url))</p><p>\(esc(e.localizedDescription))</p><p>Set it: <code>defaults write eu.thisisait.nos.app NOSFaceURL https://…/</code></p></body>", baseURL: nil)
        }
    }
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
