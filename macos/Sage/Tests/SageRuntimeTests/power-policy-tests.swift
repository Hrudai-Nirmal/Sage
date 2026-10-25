/*
 Deterministic policy tests keep battery protection independent from UI and notification timing.
 */

import Testing
@testable import SageRuntime

@Test("Battery power forces Sleep and remembers Normal")
func batteryPowerForcesSleep() {
    let result = PowerPolicy.evaluate(
        currentMode: .normal,
        previousRestorableMode: nil,
        isOnBattery: true,
        isLowPowerModeEnabled: false,
        isScreenLocked: false,
        wasPowerForced: false
    )

    #expect(result.desiredMode == .sleep)
    #expect(result.previousRestorableMode == .normal)
    #expect(result.isPowerForced)
}

@Test("Low Power Mode forces Sleep even on external power")
func lowPowerModeForcesSleep() {
    let result = PowerPolicy.evaluate(
        currentMode: .eco,
        previousRestorableMode: nil,
        isOnBattery: false,
        isLowPowerModeEnabled: true,
        isScreenLocked: false,
        wasPowerForced: false
    )

    #expect(result.desiredMode == .sleep)
    #expect(result.previousRestorableMode == .eco)
    #expect(result.isPowerForced)
}

@Test("External power restores a power-forced mode after unlock")
func externalPowerRestoresPriorMode() {
    let result = PowerPolicy.evaluate(
        currentMode: .sleep,
        previousRestorableMode: .normal,
        isOnBattery: false,
        isLowPowerModeEnabled: false,
        isScreenLocked: false,
        wasPowerForced: true
    )

    #expect(result.desiredMode == .normal)
    #expect(result.previousRestorableMode == nil)
    #expect(!result.isPowerForced)
}

@Test("Locked Mac waits before restoring a power-forced mode")
func lockedMacDefersRestore() {
    let result = PowerPolicy.evaluate(
        currentMode: .sleep,
        previousRestorableMode: .eco,
        isOnBattery: false,
        isLowPowerModeEnabled: false,
        isScreenLocked: true,
        wasPowerForced: true
    )

    #expect(result.desiredMode == .sleep)
    #expect(result.previousRestorableMode == .eco)
    #expect(result.isPowerForced)
}

@Test("Manual Sleep is never automatically restored")
func manualSleepRemainsAsleep() {
    let result = PowerPolicy.evaluate(
        currentMode: .sleep,
        previousRestorableMode: nil,
        isOnBattery: false,
        isLowPowerModeEnabled: false,
        isScreenLocked: false,
        wasPowerForced: false
    )

    #expect(result.desiredMode == .sleep)
    #expect(result.previousRestorableMode == nil)
    #expect(!result.isPowerForced)
}
