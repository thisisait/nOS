// state-check <fixture.json>: decodes every to_shell `state` sample with the app's decoder and checks null
// stays UNKNOWN, decodes every `questions` and `answer_result` sample, then encodes every to_thalamus `setting`
// and `answer` sample with the app's encoder. Exit 0 and "ok N states M settings Q questions R results A answers"
// when all hold; run by tests/anatomy/test_nos_app_reads_state.py.
import Foundation
import NOSState

func fail(_ why: String) -> Never { FileHandle.standardError.write(Data((why + "\n").utf8)); exit(1) }
func same(_ a: Any, _ b: Any) -> Bool { NSDictionary(dictionary: ["v": a]).isEqual(to: ["v": b]) }

guard CommandLine.arguments.count == 2 else { fail("usage: state-check <fixture.json>") }
let raw = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
guard let fixture = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
      let cases = fixture["to_shell"] as? [[String: Any]],
      let asks = fixture["to_thalamus"] as? [[String: Any]] else { fail("the fixture has no to_shell or to_thalamus list") }
let samples = cases.compactMap { $0["msg"] as? [String: Any] }.filter { $0["t"] as? String == "state" }
if samples.isEmpty { fail("the fixture carries no to_shell state sample") }
for msg in samples {
    let s: EstateState
    do { s = try EstateState.decode(try JSONSerialization.data(withJSONObject: msg)) } catch { fail("decode: \(error)") }
    let organs = msg["organs"] as? [[String: Any]] ?? []
    if s.organs.count != organs.count { fail("organs: \(s.organs.count) decoded, \(organs.count) sent") }
    for (o, j) in zip(s.organs, organs) {
        if o.running != (j["running"] as? Bool) { fail("\(o.name): running mis-read") }
        if o.pid != (j["pid"] as? Int) || o.last_exit != (j["last_exit"] as? Int) { fail("\(o.name): pid or last_exit mis-read") }
    }
    if (s.settings == nil) != (msg["settings"] is NSNull) { fail("settings: null and a map mis-read") }
    let act = msg["act"] as? [String: Any]
    if s.act?.recorded != act?["recorded"] as? Bool || s.act?.why != act?["why"] as? String { fail("act mis-read") }
}
let settings = asks.compactMap { $0["msg"] as? [String: Any] }.filter { $0["t"] as? String == "setting" }
for msg in settings {
    guard let key = msg["key"] as? String, let v = msg["value"],
          let value = try? JSONDecoder().decode(JSONValue.self, from: JSONSerialization.data(withJSONObject: v, options: .fragmentsAllowed)),
          let line = try? JSONSerialization.jsonObject(with: setting(key, value)) else { fail("setting: \(msg) does not encode") }
    if !same(line, msg) { fail("setting: \(msg) encodes as \(line)") }
}
func data(_ m: [String: Any]) -> Data { (try? JSONSerialization.data(withJSONObject: m)) ?? Data() }
let shell = cases.compactMap { $0["msg"] as? [String: Any] }
let qs = shell.filter { $0["t"] as? String == "questions" }
for msg in qs {
    let q: Questions
    do { q = try Questions.decode(data(msg)) } catch { fail("questions: \(error)") }
    let items = msg["items"] as? [[String: Any]] ?? []
    if q.items.map(\.uuid) != items.compactMap({ $0["uuid"] as? String }) { fail("questions: items mis-read") }
    for (i, j) in zip(q.items, items) where i.prompt != j["prompt"] as? String || i.expires_at != j["expires_at"] as? String
        || (i.options != nil) != (j["options_json"] is String) { fail("questions: \(i.uuid) mis-read") }
}
let results = shell.filter { $0["t"] as? String == "answer_result" }
var outcomes = Set<String>()
for msg in results {
    let r: AnswerResult
    do { r = try AnswerResult.decode(data(msg)) } catch { fail("answer_result: \(error)") }
    switch r.outcome {
    case .answered: outcomes.insert("answered")
    case .lost(let w): if w != msg["winning_answer"] as? String { fail("lost: winning_answer mis-read") }; outcomes.insert("lost")
    case .expired: outcomes.insert("expired")
    case .refused(let why): if why != msg["why"] as? String { fail("refused: why mis-read") }; outcomes.insert("refused")
    }
    if r.decided != (msg["outcome"] as? String == "answered") { fail("\(msg): decided mis-read (lost or refused is never decided)") }
}
if outcomes != ["answered", "lost", "expired", "refused"] { fail("the fixture misses an answer_result outcome: \(outcomes)") }
// An outcome the contract does not name, or a lost race with no winner, must fail the decode.
for bad in [["t": "answer_result", "uuid": "u", "outcome": "maybe"], ["t": "answer_result", "uuid": "u", "outcome": "lost"]] {
    if (try? AnswerResult.decode(data(bad))) != nil { fail("answer_result: \(bad) decoded") }
}
let answers = asks.compactMap { $0["msg"] as? [String: Any] }.filter { $0["t"] as? String == "answer" }
for msg in answers {
    guard let u = msg["uuid"] as? String, let a = msg["answer"] as? String,
          let line = try? JSONSerialization.jsonObject(with: answer(u, a)) else { fail("answer: \(msg) does not encode") }
    if !same(line, msg) { fail("answer: \(msg) encodes as \(line)") }
}
if qs.isEmpty || answers.isEmpty { fail("the fixture carries no questions or answer sample") }
let keys = Set(settings.compactMap { $0["key"] as? String })
if !keys.isSuperset(of: ["pulse.paused", "loops.paused"]) { fail("the fixture misses a setting sample: \(keys)") }
let opens = shell.filter { $0["t"] as? String == "approvals_open" }
for msg in opens {
    let o: ApprovalsOpen
    do { o = try ApprovalsOpen.decode(data(msg)) } catch { fail("approvals_open: \(error)") }
    let items = msg["items"] as? [[String: Any]] ?? []
    if o.items.map(\.approval) != items.compactMap({ $0["approval"] as? String }) { fail("approvals_open: items mis-read") }
}
if opens.isEmpty { fail("the fixture carries no approvals_open sample") }
// A card is announced once: the second poll of the same card says nothing, a new card says itself.
let card = OpenApproval(session: "s", approval: "a1", tool: "files.move", asked_at: "t")
let (first, seen) = newCards([card], announced: [])
let (again, _) = newCards([card], announced: seen)
if first.count != 1 || !again.isEmpty { fail("newCards: a card was not announced exactly once") }
print("ok \(samples.count) states \(settings.count) settings \(qs.count) questions \(results.count) results \(answers.count) answers \(opens.count) open")
