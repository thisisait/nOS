// state-check <fixture.json>: decodes every to_shell `state` sample with the app's decoder and
// checks null stays UNKNOWN. Exit 0 and "ok N" when all hold; run by tests/anatomy/test_nos_app_reads_state.py.
import Foundation
import NOSState

func fail(_ why: String) -> Never { FileHandle.standardError.write(Data((why + "\n").utf8)); exit(1) }

guard CommandLine.arguments.count == 2 else { fail("usage: state-check <fixture.json>") }
let raw = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
guard let fixture = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
      let cases = fixture["to_shell"] as? [[String: Any]] else { fail("the fixture has no to_shell list") }
let samples = cases.compactMap { $0["msg"] as? [String: Any] }.filter { $0["t"] as? String == "state" }
if samples.isEmpty { fail("the fixture carries no to_shell state sample") }
for msg in samples {
    let s: EstateState
    do { s = try EstateState.decode(try JSONSerialization.data(withJSONObject: msg)) } catch { fail("decode: \(error)") }
    let organs = msg["organs"] as? [[String: Any]] ?? []
    if s.organs.count != organs.count { fail("organs: \(s.organs.count) decoded, \(organs.count) sent") }
    for (o, j) in zip(s.organs, organs) where o.running != (j["running"] as? Bool) { fail("\(o.name): running mis-read") }
}
print("ok \(samples.count)")
