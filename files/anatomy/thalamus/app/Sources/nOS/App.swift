// nOS.app: the estate's state in the menu bar, read over the thalamus socket, and the face desktop in a window.
// It writes nothing itself: a halt or a setting is asked of the medulla over the socket, which checks the person and
// this signed exe (NOS_DECIDER_EXES), writes the set-point and tells Wing. Never a file here.
import AppKit
import Darwin
import NOSState
import SwiftUI
import UserNotifications
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

/// A halt or a setting asked of the medulla; what it said, in words, and the state it answered with (the new
/// set-points, so the menu need not wait for a poll). 15 s: it waits on Wing's record (10 s).
func tell(_ request: String, done what: String) -> (String, EstateState?) {
    guard let d = ask(request, secs: 15),
          let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return ("the medulla did not answer: nothing changed", nil) }
    if j["t"] as? String == "refused" { return ("refused: \(j["reason"] as? String ?? "no reason given")", nil) }
    let s = try? EstateState.decode(d)
    return (s?.act?.recorded == true ? "\(what); Wing recorded it" : "\(what); NOT recorded: \(s?.act?.why ?? "?")", s)
}

/// The open questions; nil and why when the medulla refused or did not answer (UNKNOWN, never "none").
func readQuestions() -> ([Question]?, String) {
    guard let d = ask(#"{"t":"questions"}"#) else { return (nil, "the medulla did not answer") }
    if let q = try? Questions.decode(d) { return (q.items, "") }
    let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
    return (nil, j?["t"] as? String == "refused" ? "refused: \(j?["reason"] as? String ?? "no reason given")" : "an answer the app cannot read")
}

/// This person's open Iris cards (v17); nil and why when refused or unanswered (UNKNOWN, never "none").
func readApprovals() -> ([OpenApproval]?, String) {
    guard let d = ask(#"{"t":"approvals_open"}"#) else { return (nil, "the medulla did not answer") }
    if let o = try? ApprovalsOpen.decode(d) { return (o.items, "") }
    let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
    return (nil, j?["t"] as? String == "refused" ? "refused: \(j?["reason"] as? String ?? "no reason given")" : "an answer the app cannot read")
}

/// One native notification per new card; a click opens the Face window, where the card is decided. Only in a
/// bundle: outside one (swift run) UNUserNotificationCenter traps, so nothing is posted and the badge still counts.
final class Notes: NSObject, UNUserNotificationCenterDelegate, @unchecked Sendable {
    private var onClick: (@Sendable () -> Void)?
    private var center: UNUserNotificationCenter? { Bundle.main.bundleIdentifier == nil ? nil : .current() }

    func start(_ click: @escaping @Sendable () -> Void) {
        onClick = click
        guard let c = center else { return }
        c.delegate = self
        c.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func post(_ a: OpenApproval) {
        guard let c = center else { return }
        let n = UNMutableNotificationContent()
        n.title = "Iris waits for your approval"
        n.body = "\(a.tool), asked \(a.asked_at)"  // the tool's name, never the card's arguments
        n.sound = .default
        c.add(UNNotificationRequest(identifier: a.approval, content: n, trigger: nil))
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, didReceive r: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        onClick?(); done()
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }
}

/// An answer relayed to Wing, in words. Only `answered` says decided; lost and refused never read as it.
func relay(_ q: Question, _ text: String) -> String {
    guard let d = ask(String(decoding: answer(q.uuid, text), as: UTF8.self), secs: 15) else {
        return "The medulla did not answer: nothing was decided."
    }
    guard let r = try? AnswerResult.decode(d) else {
        let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
        return "NOT decided: refused: \(j?["reason"] as? String ?? "an answer the app cannot read")"
    }
    switch r.outcome {
    case .answered: return "Decided: \(text). Wing recorded it."
    case .lost(let w): return "NOT yours: someone answered first with \(w)."
    case .expired: return "NOT decided: the deadline passed first."
    case .refused(let why): return "NOT decided: Wing refused it: \(why ?? "no reason given")."
    }
}

@MainActor final class Estate: ObservableObject {
    @Published var state: EstateState?  // nil: the medulla did not answer, never green
    @Published var said: String?        // the last halt/resume answer
    @Published var busy: String?        // a verb asked and not yet answered
    @Published var questions: [Question]?
    @Published var questionsWhy = ""    // why questions is nil
    @Published var approvals: [OpenApproval]?  // this person's open Iris cards; nil: UNKNOWN
    @Published var faceAsked = 0        // a notification click; the menu-bar label opens the Face window
    private var announced = Set<String>()
    private let notes = Notes()
    private var timer: Timer?
    private var open = false, ticks = 0  // questions: every 30 s, every 5 s while the menu is open

    init() {
        notes.start { Task { @MainActor [weak self] in self?.faceAsked += 1 } }
        poll(); pollQuestions()
        for (n, v) in [(NSMenu.didBeginTrackingNotification, true), (NSMenu.didEndTrackingNotification, false)] {
            NotificationCenter.default.addObserver(forName: n, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.open = v; if v { self?.pollQuestions() } }
            }
        }
        let t = Timer(timeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.poll(); self.ticks += 1
                if self.open || self.ticks % 6 == 0 { self.pollQuestions() }
            }
        }
        // .common: a default-mode timer never fires while the menu is open (event tracking), so it went stale.
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    /// Asked twice on purpose: a native dialog is the confirmation. With `reason`, a field for one; the
    /// answer is nil on Cancel, else the reason typed ("" when none).
    func confirm(_ title: String, _ info: String, verb: String, reason: Bool = false) -> String? {
        let alert = NSAlert()
        alert.messageText = title; alert.informativeText = info
        alert.addButton(withTitle: verb); alert.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.placeholderString = "reason (optional)"
        if reason { alert.accessoryView = field }
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        return field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// `doing` shows at once, so a menu opened before the answer says the verb is in flight, never the old verb.
    func send(_ request: String, doing: String, done: String) {
        busy = doing; said = nil
        Task.detached {
            let (words, s) = tell(request, done: done)
            await MainActor.run {
                self.busy = nil; self.said = words
                if let s { self.state = s }
                self.poll()
            }
        }
    }

    func toggleHalt() {
        let on = state?.halt.on != true
        guard confirm(on ? "Halt every Pulse job?" : "Lift the halt?",
                      on ? "Nothing scheduled runs until you resume." : "Scheduled jobs start firing again.",
                      verb: on ? "Halt" : "Resume") != nil else { return }
        send(on ? #"{"t":"halt","reason":"nOS.app"}"# : #"{"t":"lift_halt"}"#, doing: on ? "Halting…" : "Resuming…",
             done: on ? "Halted" : "Resumed")
    }

    func toggleLoops() {
        let on = state?.loops_paused.on != true
        guard let r = confirm(on ? "Pause the loops?" : "Resume the loops?",
                              on ? "Agent runs skip as a hold until you resume." : "Agent runs start again.",
                              verb: on ? "Pause" : "Resume", reason: on) else { return }
        let value: JSONValue = on ? .object(r.isEmpty ? [:] : ["reason": .string(r)]) : .null
        send(String(decoding: setting("loops.paused", value), as: UTF8.self), doing: on ? "Pausing the loops…" : "Resuming the loops…",
             done: on ? "Loops paused" : "Loops resumed")
    }

    func unpause(_ job: String) {
        guard confirm("Unpause \(job)?", "It is due again on its schedule; the halt and the loops pause still hold.",
                      verb: "Unpause") != nil else { return }
        send(String(decoding: setting("pulse.paused", .object([job: .null])), as: UTF8.self), doing: "Unpausing \(job)…",
             done: "\(job) unpaused")
    }

    /// The agent's words go in as plain strings (NSAlert renders no markup); options are buttons, else a field.
    func answerQuestion(_ q: Question) {
        let alert = NSAlert()
        alert.messageText = "\(q.agent_name) asks (\(q.kind)\(q.severity.map { ", \($0)" } ?? ""))"
        let deadline = q.expires_at.map { "Deadline: \($0)" + (q.default_on_expiry.map { ", then \($0)" } ?? "") } ?? "No deadline"
        alert.informativeText = q.prompt + "\n\n" + deadline
        let options = q.options ?? []
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        if options.isEmpty { field.placeholderString = "your answer"; alert.accessoryView = field; alert.addButton(withTitle: "Answer") }
        for o in options { alert.addButton(withTitle: o) }
        let cancel = alert.addButton(withTitle: "Cancel")
        if !options.isEmpty {  // Return never picks an option ("yes" to an approval): it cancels (11-01 ruling)
            alert.buttons.first?.keyEquivalent = ""
            cancel.keyEquivalent = "\r"
        }
        NSApp.activate(ignoringOtherApps: true)
        let i = alert.runModal().rawValue - NSApplication.ModalResponse.alertFirstButtonReturn.rawValue
        let text = options.isEmpty ? (i == 0 ? field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) : "")
                                   : (i >= 0 && i < options.count ? options[i] : "")
        guard !text.isEmpty, text.count <= 2000 else { return }  // Cancel, or an answer the contract refuses
        busy = "Answering \(q.agent_name)…"; said = nil
        Task.detached {
            let words = relay(q, text)
            await MainActor.run {
                self.busy = nil; self.said = words; self.pollQuestions()
                let done = NSAlert(); done.messageText = words; done.runModal()
            }
        }
    }

    func pollQuestions() {
        Task.detached {
            let (q, why) = readQuestions()
            await MainActor.run { self.questions = q; self.questionsWhy = why }
        }
        pollApprovals()
    }

    /// The cards on the same clock as the questions; each new one is announced once. UNKNOWN announces
    /// nothing and forgets nothing.
    func pollApprovals() {
        Task.detached {
            let (a, _) = readApprovals()
            await MainActor.run {
                self.approvals = a
                guard let a else { return }
                let (fresh, now) = newCards(a, announced: self.announced)
                self.announced = now
                fresh.forEach { self.notes.post($0) }
            }
        }
    }

    /// What the menu-bar number counts: open questions and open cards, each only when read.
    var waiting: Int { (questions?.count ?? 0) + (approvals?.count ?? 0) }

    func poll() {
        Task.detached {
            let s = readState()
            await MainActor.run { self.state = s }
        }
    }
}

func word(_ b: Bool?, on: String, off: String) -> String { b.map { $0 ? on : off } ?? "UNKNOWN" }

/// running with its pid, stopped with its last exit; a value the host did not give is UNKNOWN, never 0.
func organLine(_ o: Organ) -> String {
    let unknown = "UNKNOWN"
    switch o.running {
    case true?: return "\(o.name): running, pid \(o.pid.map(String.init) ?? unknown)"
    case false?: return "\(o.name): stopped, exit \(o.last_exit.map(String.init) ?? unknown)"
    case nil: return "\(o.name): \(unknown)"
    }
}

struct MenuView: View {
    @ObservedObject var estate: Estate
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if let s = estate.state {
            Text("Halt: " + word(s.halt.on, on: "ON" + (s.halt.since.map { " since \($0)" } ?? ""), off: "off"))
            if let r = s.halt.reason { Text("  " + r) }
            Text("Loops paused: " + word(s.loops_paused.on, on: "yes", off: "no"))
            Divider()
            ForEach(s.organs, id: \.label) { o in Text(verbatim: organLine(o)) }
        } else {
            Text("medulla unreachable")
        }
        if let b = estate.busy { Text(b) }
        if let w = estate.said { Text(w) }
        Divider()
        Button(estate.state?.halt.on == true ? "Resume…" : "Halt…") { estate.toggleHalt() }
            .disabled(estate.state?.halt.on == nil || estate.busy != nil)  // unknown: neither verb is honest
        Button(estate.state?.loops_paused.on == true ? "Resume loops…" : "Pause loops…") { estate.toggleLoops() }
            .disabled(estate.state?.loops_paused.on == nil || estate.busy != nil)
        if let qs = estate.questions {
            Menu("Questions (\(qs.count))") {
                if qs.isEmpty { Text("none waiting") }
                ForEach(qs, id: \.uuid) { q in
                    // Agent-written: a String title, never a LocalizedStringKey (which would read markdown).
                    let title: String = "\(q.agent_name): " + String(q.prompt.prefix(80)) + (q.prompt.count > 80 ? "…" : "")
                    Button(title) { estate.answerQuestion(q) }.disabled(estate.busy != nil)
                }
            }
        } else {
            Text(verbatim: "Questions: UNKNOWN (\(estate.questionsWhy))")
        }
        if let a = estate.approvals {
            Menu("Iris cards (\(a.count))") {
                if a.isEmpty { Text("none waiting") }
                ForEach(a, id: \.approval) { c in
                    Button("\(c.tool), asked \(c.asked_at)") { openWindow(id: "face"); NSApp.activate(ignoringOtherApps: true) }
                }
            }
        } else {
            Text("Iris cards: UNKNOWN")
        }
        if let s = estate.state {
            if let jobs = s.pausedJobs {
                Menu("Paused jobs (\(jobs.count))") {
                    if jobs.isEmpty { Text("none") }
                    ForEach(jobs, id: \.job) { j in
                        Text("\(j.job): by \(j.by ?? "?") at \(j.at ?? "?")" + (j.reason.map { ", \($0)" } ?? ""))
                        Button("Unpause \(j.job)…") { estate.unpause(j.job) }.disabled(estate.busy != nil)
                    }
                }
            } else {
                Text("Paused jobs: UNKNOWN")
            }
        }
        Divider()
        Button("Face") { openWindow(id: "face"); NSApp.activate(ignoringOtherApps: true) }
        Button("Quit nOS") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}

/// The menu-bar icon and the waiting count; it also opens the Face window when a notification is clicked,
/// since the label is the one view always there to hold `openWindow`.
struct BarLabel: View {
    @ObservedObject var estate: Estate
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        let on = estate.state?.halt.on  // unreachable or unreadable: a question mark, never the calm icon
        Image(systemName: on == nil ? "questionmark.circle" : on == true ? "stop.circle.fill" : "circle.hexagongrid")
            .onChange(of: estate.faceAsked) { openWindow(id: "face"); NSApp.activate(ignoringOtherApps: true) }
        if estate.waiting > 0 { Text(verbatim: "\(estate.waiting)") }
    }
}

/// The face URL: the `NOSFaceURL` default (defaults write eu.thisisait.nos.app NOSFaceURL ...), else Info.plist's.
func faceURL() -> URL? {
    let s = UserDefaults.standard.string(forKey: "NOSFaceURL") ?? Bundle.main.object(forInfoDictionaryKey: "NOSFaceURL") as? String
    return s.flatMap(URL.init(string:))
}

/// Authentik, the face's login: the `NOSAuthURL` default, else Info.plist's. Unset: the face origin only.
func authURL() -> URL? {
    let s = UserDefaults.standard.string(forKey: "NOSAuthURL") ?? Bundle.main.object(forInfoDictionaryKey: "NOSAuthURL") as? String
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
        func webView(_ v: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
            guard a.targetFrame?.isMainFrame != false, let url = a.request.url else { return decisionHandler(.allow) }
            if faceKeeps(url, origins: [faceURL(), authURL()].compactMap { $0 }) { return decisionHandler(.allow) }
            if ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
        func webView(_ v: WKWebView, didFailProvisionalNavigation _: WKNavigation!, withError e: Error) { say(v, e) }
        func webView(_ v: WKWebView, didFail _: WKNavigation!, withError e: Error) { say(v, e) }
        private func say(_ v: WKWebView, _ e: Error) {
            let url = (e as NSError).userInfo[NSURLErrorFailingURLStringErrorKey] as? String ?? ""
            let esc = { (s: String) in s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;") }
            v.loadHTMLString("<body style='font:14px -apple-system;padding:2em'><h3>The face could not load</h3><p>\(esc(url))</p><p>\(esc(e.localizedDescription))</p><p>Set it: <code>defaults write eu.thisisait.nos.app NOSFaceURL https://…/</code></p></body>", baseURL: nil)
        }
    }
}

@main struct NOSApp: App {
    @StateObject private var estate = Estate()

    var body: some Scene {
        MenuBarExtra {
            MenuView(estate: estate)
        } label: {
            BarLabel(estate: estate)
        }
        Window("Face", id: "face") {
            if let url = faceURL() { WebView(url: url).frame(minWidth: 900, minHeight: 600) } else { Text("NOSFaceURL is not set") }
        }
    }
}
