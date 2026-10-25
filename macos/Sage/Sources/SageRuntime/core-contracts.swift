/*
 Codable contracts isolate the native app from transport details and mirror Sage Core's bounded APIs.
 */

import Foundation

/// Native foreground event types accepted by Sage Core.
public enum DesktopEventType: String, Codable, Sendable {
    case applicationActivated = "APPLICATION_ACTIVATED"
    case windowChanged = "WINDOW_CHANGED"
}

/// One metadata-only native activity event; it intentionally has no screenshot or body-text field.
public struct DesktopEvent: Codable, Equatable, Sendable {
    public let activeDurationSeconds: Int?
    public let appBundleId: String
    public let appName: String
    public let eventId: String
    public let eventType: DesktopEventType
    public let hostId: String
    public let occurredAt: Date
    public let windowTitle: String?

    /// Create one validated-by-Core desktop activity payload.
    public init(
        activeDurationSeconds: Int?,
        appBundleId: String,
        appName: String,
        eventId: String,
        eventType: DesktopEventType,
        hostId: String,
        occurredAt: Date,
        windowTitle: String?
    ) {
        self.activeDurationSeconds = activeDurationSeconds
        self.appBundleId = appBundleId
        self.appName = appName
        self.eventId = eventId
        self.eventType = eventType
        self.hostId = hostId
        self.occurredAt = occurredAt
        self.windowTitle = windowTitle
    }
}

/// Current local Core health and requested mode.
public struct SystemStatus: Codable, Equatable, Sendable {
    public let mode: SageMode
    public let status: String
}

/// Effective Observer state after user intent and runtime mode are combined.
public struct ObserverStatus: Codable, Equatable, Sendable {
    public let isCollecting: Bool
    public let monitoringState: String
    public let pauseUntil: String?
    public let runtimeMode: SageMode
}

/// User-controlled Observer collection intents accepted by Core.
public enum ObserverMonitoringState: String, Codable, Sendable {
    case off = "OFF"
    case on = "ON"
    case paused = "PAUSED"
}

/// One explicit Observer control change.
public struct ObserverMonitoringUpdate: Codable, Equatable, Sendable {
    public let monitoringState: ObserverMonitoringState
    public let pauseUntil: String?

    /// Create one control update, leaving validation of pause semantics to Core.
    public init(monitoringState: ObserverMonitoringState, pauseUntil: String?) {
        self.monitoringState = monitoringState
        self.pauseUntil = pauseUntil
    }
}

/// Shared JSON configuration keeps dates stable across all loopback calls.
public enum CoreJsonCoding {
    /// Encoder matching Core's ISO-8601 contract with deterministic keys for tests and diagnostics.
    public static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }

    /// Decoder matching Core's ISO-8601 contract.
    public static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}
