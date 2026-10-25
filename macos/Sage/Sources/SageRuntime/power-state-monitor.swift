/*
 Native power notifications drive Sage's deterministic sleep policy without a polling loop.
 */

import AppKit
import Foundation
import IOKit.ps

/// Current host facts relevant to Sage's power policy.
public struct HostPowerState: Equatable, Sendable {
    public let isLowPowerModeEnabled: Bool
    public let isOnBattery: Bool
    public let isScreenLocked: Bool

    /// Create one immutable host power snapshot.
    public init(
        isLowPowerModeEnabled: Bool,
        isOnBattery: Bool,
        isScreenLocked: Bool
    ) {
        self.isLowPowerModeEnabled = isLowPowerModeEnabled
        self.isOnBattery = isOnBattery
        self.isScreenLocked = isScreenLocked
    }
}

/// Emits event-driven power and lock-state changes on the main actor.
@MainActor
public final class PowerStateMonitor {
    private let onChange: @MainActor @Sendable (HostPowerState) -> Void
    private var notificationTokens: [NSObjectProtocol] = []
    private var isScreenLocked = false

    /// Create a monitor that reports each material power-state transition.
    public init(onChange: @escaping @MainActor @Sendable (HostPowerState) -> Void) {
        self.onChange = onChange
    }

    /// Start observing process power and workspace lock notifications once.
    public func start() {
        guard notificationTokens.isEmpty else {
            return
        }
        let processToken = NotificationCenter.default.addObserver(
            forName: Notification.Name.NSProcessInfoPowerStateDidChange,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.emitCurrentState()
            }
        }
        let lockToken = DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.apple.screenIsLocked"),
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.isScreenLocked = true
                self?.emitCurrentState()
            }
        }
        let unlockToken = DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.apple.screenIsUnlocked"),
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.isScreenLocked = false
                self?.emitCurrentState()
            }
        }
        notificationTokens = [processToken, lockToken, unlockToken]
        emitCurrentState()
    }

    /// Stop every registered notification without changing Sage's requested mode.
    public func stop() {
        for token in notificationTokens {
            NotificationCenter.default.removeObserver(token)
            DistributedNotificationCenter.default().removeObserver(token)
        }
        notificationTokens.removeAll()
    }

    /// Return the latest locally derived power state.
    public func currentState() -> HostPowerState {
        HostPowerState(
            isLowPowerModeEnabled: ProcessInfo.processInfo.isLowPowerModeEnabled,
            isOnBattery: Self.readIsOnBattery(),
            isScreenLocked: isScreenLocked
        )
    }

    private func emitCurrentState() {
        onChange(currentState())
    }

    private static func readIsOnBattery() -> Bool {
        guard let snapshot = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let sourceType = IOPSGetProvidingPowerSourceType(snapshot)?.takeUnretainedValue()
                  as String?
        else {
            return true
        }
        return sourceType == kIOPSBatteryPowerValue
    }
}
