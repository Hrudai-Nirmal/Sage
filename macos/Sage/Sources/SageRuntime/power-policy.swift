/*
 Pure power-mode decisions make battery protection testable and immune to notification ordering.
 */

import Foundation

/// Sage runtime modes shared by the native operator and Core API.
public enum SageMode: String, Codable, CaseIterable, Sendable {
    case normal = "NORMAL"
    case eco = "ECO"
    case sleep = "SLEEP"
    case shutdown = "SHUTDOWN"
}

/// One deterministic outcome for a power-state transition.
public struct PowerPolicyResult: Equatable, Sendable {
    public let desiredMode: SageMode
    public let previousRestorableMode: SageMode?
    public let isPowerForced: Bool

    /// Create a complete immutable power-policy result.
    public init(
        desiredMode: SageMode,
        previousRestorableMode: SageMode?,
        isPowerForced: Bool
    ) {
        self.desiredMode = desiredMode
        self.previousRestorableMode = previousRestorableMode
        self.isPowerForced = isPowerForced
    }
}

/// Converts host power facts into a mode request without hidden side effects.
public enum PowerPolicy {
    /// Decide whether Sage must sleep or may restore a previously active mode.
    public static func evaluate(
        currentMode: SageMode,
        previousRestorableMode: SageMode?,
        isOnBattery: Bool,
        isLowPowerModeEnabled: Bool,
        isScreenLocked: Bool,
        wasPowerForced: Bool
    ) -> PowerPolicyResult {
        let shouldForceSleep = isOnBattery || isLowPowerModeEnabled
        if shouldForceSleep {
            let restorableMode = currentMode == .normal || currentMode == .eco
                ? currentMode
                : previousRestorableMode
            return PowerPolicyResult(
                desiredMode: .sleep,
                previousRestorableMode: restorableMode,
                isPowerForced: true
            )
        }
        if wasPowerForced, !isScreenLocked, let previousRestorableMode {
            return PowerPolicyResult(
                desiredMode: previousRestorableMode,
                previousRestorableMode: nil,
                isPowerForced: false
            )
        }
        return PowerPolicyResult(
            desiredMode: currentMode,
            previousRestorableMode: previousRestorableMode,
            isPowerForced: wasPowerForced
        )
    }
}
