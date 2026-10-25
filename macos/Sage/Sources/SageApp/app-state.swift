/*
 One main-actor state owner coordinates Core, power policy, native observation, and the durable event queue.
 */

import AppKit
import ApplicationServices
import Combine
import Foundation
import SageRuntime

@MainActor
final class AppState: ObservableObject {
    @Published private(set) var currentAppName = "No permitted activity"
    @Published private(set) var currentWindowTitle: String?
    @Published private(set) var hasAccessibilityPermission = AXIsProcessTrusted()
    @Published private(set) var isCoreReachable = false
    @Published private(set) var isObserverCollecting = false
    @Published private(set) var lastError: String?
    @Published private(set) var mode: SageMode = .sleep
    @Published private(set) var monitoringState = "UNKNOWN"
    @Published private(set) var powerState = HostPowerState(
        isLowPowerModeEnabled: false,
        isOnBattery: true,
        isScreenLocked: false
    )
    @Published private(set) var queuedEventCount = 0

    private let coreClient: CoreClient?
    private let eventQueue: DesktopEventQueue?
    private let hostId: String
    private var eventPlanState = DesktopEventPlanState.empty
    private var isFlushing = false
    private var isStarted = false
    private var nativeObserverToken: String?
    private var operatorToken: String?
    private var statusTask: Task<Void, Never>?
    private var previousRestorableMode: SageMode?
    private var isPowerForced = false

    private lazy var activityObserver = ForegroundActivityObserver { [weak self] observation in
        self?.handleObservation(observation)
    }
    private lazy var powerMonitor = PowerStateMonitor { [weak self] powerState in
        self?.handlePowerState(powerState)
    }

    init() {
        hostId = Self.makeHostId(ProcessInfo.processInfo.hostName)
        var configuredClient: CoreClient?
        var configuredQueue: DesktopEventQueue?
        var initializationFailed = false
        do {
            let requestFactory = try CoreRequestFactory(
                baseUrl: URL(string: "http://127.0.0.1:8787")!
            )
            configuredClient = CoreClient(requestFactory: requestFactory)
            let supportUrl = try FileManager.default.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            configuredQueue = try DesktopEventQueue(
                storageUrl: supportUrl
                    .appending(path: "Sage")
                    .appending(path: "observer")
                    .appending(path: "desktop-events.json"),
                capacity: 1_000
            )
        } catch {
            initializationFailed = true
        }
        coreClient = configuredClient
        eventQueue = configuredQueue
        previousRestorableMode = UserDefaults.standard.string(
            forKey: "power.previousRestorableMode"
        ).flatMap(SageMode.init(rawValue:))
        isPowerForced = UserDefaults.standard.bool(forKey: "power.isForced")
        if initializationFailed {
            lastError = "Sage could not initialize its local runtime."
        }
        // Menu-bar launches do not guarantee that SwiftUI constructs the main window view.
        start()
    }

    /// Start the single native observer and lightweight health reconciliation loop.
    func start() {
        guard !isStarted else {
            return
        }
        isStarted = true
        do {
            let configuredDataRoot = ProcessInfo.processInfo.environment["SAGE_DATA_ROOT"]
                .map(URL.init(fileURLWithPath:))
                ?? FileManager.default.homeDirectoryForCurrentUser.appending(path: "SageData")
            let credentials = try RuntimeCredentialStore(
                environmentUrl: configuredDataRoot
                    .appending(path: "secrets")
                    .appending(path: "core.env")
            ).readCredentials()
            operatorToken = credentials.operatorToken
            nativeObserverToken = credentials.nativeObserverToken
        } catch {
            lastError = "Sage credentials are unavailable or not protected with private permissions."
        }
        powerMonitor.start()
        synchronizeObserverLifecycle(shouldPromptForAccessibility: true)
        statusTask = Task { [weak self] in
            await self?.runStatusLoop()
        }
    }

    /// Stop host observers and pending UI refresh work during clean app termination.
    func stop() {
        statusTask?.cancel()
        statusTask = nil
        activityObserver.stop()
        powerMonitor.stop()
        isStarted = false
    }

    /// Refresh Core and Observer health immediately from a user action.
    func refresh() {
        Task { [weak self] in
            await self?.refreshStatus()
        }
    }

    /// Request a mode from the native operator, respecting mandatory power sleep.
    func requestMode(_ requestedMode: SageMode) {
        if (powerState.isOnBattery || powerState.isLowPowerModeEnabled)
            && (requestedMode == .normal || requestedMode == .eco)
        {
            lastError = "External power and Low Power Mode off are required for Normal or Eco."
            return
        }
        isPowerForced = false
        previousRestorableMode = nil
        persistPowerPolicyState()
        Task { [weak self] in
            await self?.commitMode(requestedMode)
        }
    }

    /// Turn automatic observation on or off through the operator credential.
    func requestMonitoring(_ state: ObserverMonitoringState) {
        guard let coreClient, let operatorToken else {
            lastError = "Sage Core or its operator credential is unavailable."
            return
        }
        Task { [weak self] in
            do {
                let status = try await coreClient.setObserverMonitoring(
                    state,
                    pauseUntil: nil,
                    operatorToken: operatorToken
                )
                self?.applyObserverStatus(status)
            } catch {
                self?.lastError = "Observer control failed. Core may be offline."
            }
        }
    }

    private var canCollectDesktopActivity: Bool {
        isObserverCollecting
            && !powerState.isOnBattery
            && !powerState.isLowPowerModeEnabled
            && !powerState.isScreenLocked
            && (mode == .normal || mode == .eco)
    }

    private func runStatusLoop() async {
        while !Task.isCancelled {
            await refreshStatus()
            do {
                try await Task.sleep(for: .seconds(15))
            } catch {
                return
            }
        }
    }

    private func refreshStatus() async {
        guard let coreClient else {
            isCoreReachable = false
            return
        }
        do {
            async let systemStatus = coreClient.getSystemStatus()
            async let observerStatus = coreClient.getObserverStatus()
            let (system, observer) = try await (systemStatus, observerStatus)
            mode = system.mode
            isCoreReachable = system.status.lowercased() == "healthy"
            applyObserverStatus(observer)
            lastError = nil
            await updateQueueCount()
            await flushQueuedEvents()
        } catch {
            isCoreReachable = false
            lastError = "Sage Core is offline. Activity will remain queued locally."
        }
        synchronizeObserverLifecycle(shouldPromptForAccessibility: false)
    }

    private func applyObserverStatus(_ status: ObserverStatus) {
        monitoringState = status.monitoringState
        isObserverCollecting = status.isCollecting
        mode = status.runtimeMode
        synchronizeObserverLifecycle(shouldPromptForAccessibility: false)
    }

    private func handlePowerState(_ newPowerState: HostPowerState) {
        powerState = newPowerState
        activityObserver.setScreenLocked(newPowerState.isScreenLocked)
        synchronizeObserverLifecycle(shouldPromptForAccessibility: false)
        let result = PowerPolicy.evaluate(
            currentMode: mode,
            previousRestorableMode: previousRestorableMode,
            isOnBattery: newPowerState.isOnBattery,
            isLowPowerModeEnabled: newPowerState.isLowPowerModeEnabled,
            isScreenLocked: newPowerState.isScreenLocked,
            wasPowerForced: isPowerForced
        )
        previousRestorableMode = result.previousRestorableMode
        isPowerForced = result.isPowerForced
        persistPowerPolicyState()
        if result.desiredMode != mode {
            Task { [weak self] in
                await self?.commitMode(result.desiredMode)
            }
        }
    }

    private func commitMode(_ requestedMode: SageMode) async {
        guard let coreClient, let operatorToken else {
            lastError = "Sage Core or its operator credential is unavailable."
            return
        }
        do {
            let status = try await coreClient.setMode(requestedMode, operatorToken: operatorToken)
            mode = status.mode
            isCoreReachable = true
            lastError = nil
        } catch {
            isCoreReachable = false
            lastError = "Sage could not apply the requested runtime mode."
        }
        synchronizeObserverLifecycle(shouldPromptForAccessibility: false)
    }

    private func synchronizeObserverLifecycle(shouldPromptForAccessibility: Bool) {
        hasAccessibilityPermission = AXIsProcessTrusted()
        if canCollectDesktopActivity {
            activityObserver.start(
                shouldPromptForAccessibility: shouldPromptForAccessibility
            )
        } else {
            activityObserver.stop()
        }
    }

    private func handleObservation(_ observation: DesktopObservation) {
        guard canCollectDesktopActivity else {
            return
        }
        let plan = DesktopEventPlanner.plan(
            observation: observation,
            previousState: eventPlanState,
            hostId: hostId,
            occurredAt: Date(),
            eventId: UUID().uuidString
        )
        guard let event = plan.event else {
            return
        }
        eventPlanState = plan.state
        currentAppName = observation.appName
        currentWindowTitle = observation.windowTitle
        guard let eventQueue else {
            lastError = "The native activity queue is unavailable."
            return
        }
        Task { [weak self] in
            do {
                try await eventQueue.enqueue(event)
                await self?.updateQueueCount()
                await self?.flushQueuedEvents()
            } catch {
                self?.lastError = "Sage could not save a permitted activity event."
            }
        }
    }

    private func flushQueuedEvents() async {
        guard !isFlushing,
              canCollectDesktopActivity,
              let coreClient,
              let eventQueue,
              let nativeObserverToken
        else {
            return
        }
        isFlushing = true
        defer { isFlushing = false }
        for _ in 0..<50 {
            do {
                guard let event = try await eventQueue.peek() else {
                    break
                }
                try await coreClient.submitDesktopEvent(
                    event,
                    nativeObserverToken: nativeObserverToken
                )
                try await eventQueue.remove(eventId: event.eventId)
            } catch {
                lastError = "Core is unavailable; permitted activity remains queued locally."
                break
            }
        }
        await updateQueueCount()
    }

    private func updateQueueCount() async {
        guard let eventQueue else {
            queuedEventCount = 0
            return
        }
        do {
            queuedEventCount = try await eventQueue.count()
        } catch {
            lastError = "Sage could not read its local activity queue."
        }
    }

    private func persistPowerPolicyState() {
        UserDefaults.standard.set(
            previousRestorableMode?.rawValue,
            forKey: "power.previousRestorableMode"
        )
        UserDefaults.standard.set(isPowerForced, forKey: "power.isForced")
    }

    private static func makeHostId(_ hostName: String) -> String {
        let allowedCharacters = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_.-"))
        let normalizedScalars = hostName.lowercased().unicodeScalars.map { scalar in
            allowedCharacters.contains(scalar) ? Character(String(scalar)) : "-"
        }
        let normalizedHostName = String(normalizedScalars)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return normalizedHostName.isEmpty ? "sage-mac" : normalizedHostName
    }
}
