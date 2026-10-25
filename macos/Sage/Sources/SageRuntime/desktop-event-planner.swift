/*
 A pure planner removes duplicate app/window notifications before they consume battery or Core capacity.
 */

import Foundation

/// One bounded foreground snapshot produced by native macOS APIs.
public struct DesktopObservation: Equatable, Sendable {
    public let appBundleId: String
    public let appName: String
    public let windowTitle: String?
    public let isScreenLocked: Bool
    public let isSecureInputEnabled: Bool

    /// Create one metadata-only observation with explicit sensitive-state gates.
    public init(
        appBundleId: String,
        appName: String,
        windowTitle: String?,
        isScreenLocked: Bool = false,
        isSecureInputEnabled: Bool = false
    ) {
        self.appBundleId = appBundleId
        self.appName = appName
        self.windowTitle = windowTitle
        self.isScreenLocked = isScreenLocked
        self.isSecureInputEnabled = isSecureInputEnabled
    }
}

/// Minimal state needed to deduplicate and debounce foreground observations.
public struct DesktopEventPlanState: Equatable, Sendable {
    public let lastAcceptedAt: Date?
    public let lastBundleId: String?
    public let lastSignature: String?

    /// Initial planner state before any permitted observation.
    public static let empty = DesktopEventPlanState(
        lastAcceptedAt: nil,
        lastBundleId: nil,
        lastSignature: nil
    )

    /// Create an immutable event-planning state.
    public init(lastAcceptedAt: Date?, lastBundleId: String?, lastSignature: String?) {
        self.lastAcceptedAt = lastAcceptedAt
        self.lastBundleId = lastBundleId
        self.lastSignature = lastSignature
    }
}

/// One planner decision containing a possible event and the next deduplication state.
public struct DesktopEventPlanResult: Equatable, Sendable {
    public let event: DesktopEvent?
    public let privacyDecision: DesktopPrivacyDecision
    public let state: DesktopEventPlanState

    /// Create a complete immutable planner result.
    public init(
        event: DesktopEvent?,
        privacyDecision: DesktopPrivacyDecision,
        state: DesktopEventPlanState
    ) {
        self.event = event
        self.privacyDecision = privacyDecision
        self.state = state
    }
}

/// Converts native notifications into privacy-gated, debounced Core events.
public enum DesktopEventPlanner {
    private static let debounceSeconds: TimeInterval = 5

    /// Plan one event without performing I/O or retaining sensitive metadata.
    public static func plan(
        observation: DesktopObservation,
        previousState: DesktopEventPlanState,
        hostId: String,
        occurredAt: Date,
        eventId: String
    ) -> DesktopEventPlanResult {
        let privacyDecision = DesktopPrivacyPolicy.evaluate(
            appBundleId: observation.appBundleId,
            isScreenLocked: observation.isScreenLocked,
            isSecureInputEnabled: observation.isSecureInputEnabled
        )
        guard privacyDecision == .allow else {
            return DesktopEventPlanResult(
                event: nil,
                privacyDecision: privacyDecision,
                state: previousState
            )
        }

        let normalizedTitle = observation.windowTitle?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let signature = "\(observation.appBundleId)\u{1F}\(normalizedTitle ?? "")"
        if signature == previousState.lastSignature {
            return DesktopEventPlanResult(
                event: nil,
                privacyDecision: .allow,
                state: previousState
            )
        }
        if let lastAcceptedAt = previousState.lastAcceptedAt,
           occurredAt.timeIntervalSince(lastAcceptedAt) < debounceSeconds
        {
            return DesktopEventPlanResult(
                event: nil,
                privacyDecision: .allow,
                state: previousState
            )
        }

        let eventType: DesktopEventType = previousState.lastBundleId == observation.appBundleId
            ? .windowChanged
            : .applicationActivated
        let activeDurationSeconds = previousState.lastAcceptedAt.map {
            min(86_400, max(0, Int(occurredAt.timeIntervalSince($0))))
        }
        let event = DesktopEvent(
            activeDurationSeconds: activeDurationSeconds,
            appBundleId: observation.appBundleId,
            appName: observation.appName,
            eventId: eventId,
            eventType: eventType,
            hostId: hostId,
            occurredAt: occurredAt,
            windowTitle: normalizedTitle?.isEmpty == false ? normalizedTitle : nil
        )
        return DesktopEventPlanResult(
            event: event,
            privacyDecision: .allow,
            state: DesktopEventPlanState(
                lastAcceptedAt: occurredAt,
                lastBundleId: observation.appBundleId,
                lastSignature: signature
            )
        )
    }
}
