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

    enum CodingKeys: String, CodingKey { case name, label, running }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        label = try c.decode(String.self, forKey: .label)
        running = try c.decode(Bool?.self, forKey: .running)
    }
}

public struct EstateState: Decodable, Sendable, Equatable {
    public let halt: SetPoint
    public let loops_paused: SetPoint
    public let organs: [Organ]

    enum CodingKeys: String, CodingKey { case t, halt, loops_paused, organs }
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        guard try c.decode(String.self, forKey: .t) == "state" else {
            throw DecodingError.dataCorruptedError(forKey: .t, in: c, debugDescription: "not a state message")
        }
        halt = try c.decode(SetPoint.self, forKey: .halt)
        loops_paused = try c.decode(SetPoint.self, forKey: .loops_paused)
        organs = try c.decode([Organ].self, forKey: .organs)
    }

    public static func decode(_ line: Data) throws -> EstateState {
        try JSONDecoder().decode(EstateState.self, from: line)
    }
}
