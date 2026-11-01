// state-check <fixture.json>: decodes every to_shell `state` sample with the app's decoder and checks null
// stays UNKNOWN, then encodes every to_thalamus `setting` sample with the app's encoder. Exit 0 and
// "ok N states M settings" when all hold; run by tests/anatomy/test_nos_app_reads_state.py.
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
    for (o, j) in zip(s.organs, organs) where o.running != (j["running"] as? Bool) { fail("\(o.name): running mis-read") }
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
let keys = Set(settings.compactMap { $0["key"] as? String })
if !keys.isSuperset(of: ["pulse.paused", "loops.paused"]) { fail("the fixture misses a setting sample: \(keys)") }
print("ok \(samples.count) states \(settings.count) settings")
