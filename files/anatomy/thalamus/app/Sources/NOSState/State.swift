// The thalamus's `state` answer (contracts/thalamus-shell.yml wire.state; contract/src/wire.rs EstateState).
// A required key that is missing fails the decode, null included: a renamed field never reads as off.
import Foundation

public struct SetPoint: Decodable, Sendable, Equatable {
    public let on: Bool?          // nil: the file could not be read, UNKNOWN
    public let since: String?
    public let reason: String?
    public let file: String

    enum CodingKeys: String, CodingKey { case on, since, reason, file }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        on = try c.decode(Bool?.self, forKey: .on)
        since = try c.decodeIfPresent(String.self, forKey: .since)
        reason = try c.decodeIfPresent(String.self, forKey: .reason)
        file = try c.decode(String.self, forKey: .file)
    }
}

public struct Organ: Decodable, Sendable, Equatable {
    public let name: String
    public let label: String
    public let running: Bool?     // nil: the host did not say, UNKNOWN (never stopped)
    public let pid: Int?          // nil or absent: UNKNOWN, never 0
    public let last_exit: Int?

    enum CodingKeys: String, CodingKey { case name, label, running, pid, last_exit }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        label = try c.decode(String.self, forKey: .label)
        running = try c.decode(Bool?.self, forKey: .running)
        pid = try c.decodeIfPresent(Int.self, forKey: .pid)
        last_exit = try c.decodeIfPresent(Int.self, forKey: .last_exit)
    }
}

/// Any JSON value: a setting's value is the genome's to shape, not the app's.
public enum JSONValue: Codable, Sendable, Equatable {
    case null, bool(Bool), number(Double), string(String), array([JSONValue]), object([String: JSONValue])

    public init(from d: Decoder) throws {
        let c = try d.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    public func encode(to e: Encoder) throws {
        var c = e.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let n): try c.encode(n)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }
    public subscript(_ k: String) -> JSONValue? { if case .object(let o) = self { o[k] } else { nil } }
    public var string: String? { if case .string(let s) = self { s } else { nil } }
}

/// Whether Wing recorded a halt / lift_halt / setting act (v14, v15); the set-point holds either way.
public struct ActRecord: Decodable, Sendable, Equatable {
    public let recorded: Bool
    public let why: String?
}

/// One job pulse.paused holds: who paused it, when, why.
public struct PausedJob: Sendable, Equatable {
    public let job: String, by: String?, at: String?, reason: String?
}

public struct EstateState: Decodable, Sendable, Equatable {
    public let halt: SetPoint
    public let loops_paused: SetPoint
    public let organs: [Organ]
    public let settings: [String: JSONValue]?  // nil: the genome did not read, UNKNOWN; a value null: its file did not
    public let act: ActRecord?                   // only on the answer to a halt or a setting

    enum CodingKeys: String, CodingKey { case t, halt, loops_paused, organs, settings, act }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        guard try c.decode(String.self, forKey: .t) == "state" else {
            throw DecodingError.dataCorruptedError(forKey: .t, in: c, debugDescription: "not a state message")
        }
        halt = try c.decode(SetPoint.self, forKey: .halt)
        loops_paused = try c.decode(SetPoint.self, forKey: .loops_paused)
        organs = try c.decode([Organ].self, forKey: .organs)
        settings = try c.decode([String: JSONValue]?.self, forKey: .settings)
        act = try c.decodeIfPresent(ActRecord.self, forKey: .act)
    }

    /// The jobs pulse.paused holds, by job id; nil when it is UNKNOWN (the genome or its file did not read).
    public var pausedJobs: [PausedJob]? {
        guard case .object(let m)? = settings?["pulse.paused"] else { return nil }
        return m.keys.sorted().map { PausedJob(job: $0, by: m[$0]?["by"]?.string, at: m[$0]?["at"]?.string, reason: m[$0]?["reason"]?.string) }
    }

    public static func decode(_ line: Data) throws -> EstateState {
        try JSONDecoder().decode(EstateState.self, from: line)
    }
}

/// The to_thalamus `setting {key, value}` line (v15). A map setting's value is the change: {job: {reason?}} sets
/// an entry, {job: null} removes it; a sentinel's is {reason?} or null. The key is one the genome names.
public func setting(_ key: String, _ value: JSONValue) -> Data {
    let line: JSONValue = .object(["t": .string("setting"), "key": .string(key), "value": value])
    return (try? JSONEncoder().encode(line)) ?? Data()  // a JSONValue always encodes
}

/// One open agent question (v16 `questions {items}`, AgentQuestionRepository::public()). Its text is the
/// agent's: shown as plain text, never interpreted.
public struct Question: Decodable, Sendable, Equatable {
    public let uuid: String, agent_name: String, kind: String, prompt: String
    public let options_json: String?, severity: String?, expires_at: String?, default_on_expiry: String?

    enum CodingKeys: String, CodingKey { case uuid, agent_name, kind, prompt, options_json, severity, expires_at, default_on_expiry }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        uuid = try c.decode(String.self, forKey: .uuid)
        agent_name = try c.decode(String.self, forKey: .agent_name)
        kind = try c.decode(String.self, forKey: .kind)
        prompt = try c.decode(String.self, forKey: .prompt)
        options_json = try c.decode(String?.self, forKey: .options_json)
        severity = try c.decode(String?.self, forKey: .severity)
        expires_at = try c.decode(String?.self, forKey: .expires_at)
        default_on_expiry = try c.decode(String?.self, forKey: .default_on_expiry)
    }

    /// The options as button labels; nil when there are none (or not all are strings): a text field then.
    public var options: [String]? {
        guard let j = options_json?.data(using: .utf8), let a = try? JSONDecoder().decode([String].self, from: j), !a.isEmpty else { return nil }
        return a
    }
}

public struct Questions: Decodable, Sendable, Equatable {
    public let items: [Question]
    enum CodingKeys: String, CodingKey { case t, items }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        guard try c.decode(String.self, forKey: .t) == "questions" else {
            throw DecodingError.dataCorruptedError(forKey: .t, in: c, debugDescription: "not a questions message")
        }
        items = try c.decode([Question].self, forKey: .items)
    }
    public static func decode(_ line: Data) throws -> Questions { try JSONDecoder().decode(Questions.self, from: line) }
}

/// How Wing resolved one answer (v16). Only `answered` is the operator's decision; an outcome the contract does
/// not name fails the decode, and a lost race must say who won.
public enum AnswerOutcome: Sendable, Equatable { case answered, lost(winning: String), expired, refused(why: String?) }

public struct AnswerResult: Decodable, Sendable, Equatable {
    public let uuid: String
    public let outcome: AnswerOutcome
    public var decided: Bool { outcome == .answered }

    enum CodingKeys: String, CodingKey { case t, uuid, outcome, winning_answer, why }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        guard try c.decode(String.self, forKey: .t) == "answer_result" else {
            throw DecodingError.dataCorruptedError(forKey: .t, in: c, debugDescription: "not an answer_result")
        }
        uuid = try c.decode(String.self, forKey: .uuid)
        switch try c.decode(String.self, forKey: .outcome) {
        case "answered": outcome = .answered
        case "lost": outcome = .lost(winning: try c.decode(String.self, forKey: .winning_answer))
        case "expired": outcome = .expired
        case "refused": outcome = .refused(why: try c.decodeIfPresent(String.self, forKey: .why))
        case let o: throw DecodingError.dataCorruptedError(forKey: .outcome, in: c, debugDescription: "unknown outcome \(o)")
        }
    }
    public static func decode(_ line: Data) throws -> AnswerResult { try JSONDecoder().decode(AnswerResult.self, from: line) }
}

/// The to_thalamus `answer {uuid, answer}` line (v16).
public func answer(_ uuid: String, _ text: String) -> Data {
    let line: JSONValue = .object(["t": .string("answer"), "uuid": .string(uuid), "answer": .string(text)])
    return (try? JSONEncoder().encode(line)) ?? Data()
}

/// The face window's main frame stays on these origins (face, Authentik); any other page goes to the browser,
/// which shows its URL: a redirect here could draw a look-alike login with no URL bar (review 11-03).
public func faceKeeps(_ url: URL, origins: [URL]) -> Bool {
    if url.absoluteString == "about:blank" { return true }  // the window's own failure page (loadHTMLString)
    let key = { (u: URL) -> String? in
        guard let s = u.scheme?.lowercased(), s == "http" || s == "https", let h = u.host?.lowercased() else { return nil }
        return "\(s)://\(h):\(u.port ?? (s == "http" ? 80 : 443))"
    }
    guard let k = key(url) else { return false }
    return origins.contains { key($0) == k }
}
