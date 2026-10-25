/*
 Event-driven AppKit and Accessibility notifications collect only foreground app identity and window title.
 */

import AppKit
import ApplicationServices
import Carbon.HIToolbox
import Foundation

private func handleAccessibilityNotification(
    observer: AXObserver,
    element: AXUIElement,
    notification: CFString,
    reference: UnsafeMutableRawPointer?
) {
    guard let reference else {
        return
    }
    let activityObserver = Unmanaged<ForegroundActivityObserver>
        .fromOpaque(reference)
        .takeUnretainedValue()
    Task { @MainActor in
        activityObserver.handleAccessibilityChange()
    }
}

/// Observes foreground application and accessible title changes without periodic screen capture.
@MainActor
public final class ForegroundActivityObserver {
    private let onObservation: @MainActor @Sendable (DesktopObservation) -> Void
    private var activationToken: NSObjectProtocol?
    private var accessibilityObserver: AXObserver?
    private var observedApplication: AXUIElement?
    private var observedWindow: AXUIElement?
    private var isScreenLocked = false

    /// Create an observer that emits privacy-evaluable metadata snapshots.
    public init(
        onObservation: @escaping @MainActor @Sendable (DesktopObservation) -> Void
    ) {
        self.onObservation = onObservation
    }

    /// Ask for Accessibility permission when requested and begin event-driven observation.
    public func start(shouldPromptForAccessibility: Bool) {
        guard activationToken == nil else {
            return
        }
        if shouldPromptForAccessibility {
            let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(options)
        }
        activationToken = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            let application = notification.userInfo?[NSWorkspace.applicationUserInfoKey]
                as? NSRunningApplication
            Task { @MainActor in
                self?.observe(application: application)
            }
        }
        observe(application: NSWorkspace.shared.frontmostApplication)
    }

    /// Update lock state before any subsequent Accessibility value is read.
    public func setScreenLocked(_ isLocked: Bool) {
        isScreenLocked = isLocked
        if isLocked {
            detachAccessibilityObserver()
        } else {
            observe(application: NSWorkspace.shared.frontmostApplication)
        }
    }

    /// Stop AppKit and Accessibility observation and release their run-loop source.
    public func stop() {
        if let activationToken {
            NSWorkspace.shared.notificationCenter.removeObserver(activationToken)
        }
        activationToken = nil
        detachAccessibilityObserver()
    }

    /// Re-read the current focused window after a registered AX notification.
    public func handleAccessibilityChange() {
        observe(application: NSWorkspace.shared.frontmostApplication)
    }

    private func observe(application: NSRunningApplication?) {
        guard let application,
              let appBundleId = application.bundleIdentifier,
              let appName = application.localizedName
        else {
            return
        }
        let secureInputEnabled = IsSecureEventInputEnabled()
        let privacyDecision = DesktopPrivacyPolicy.evaluate(
            appBundleId: appBundleId,
            isScreenLocked: isScreenLocked,
            isSecureInputEnabled: secureInputEnabled
        )
        guard privacyDecision == .allow else {
            detachAccessibilityObserver()
            return
        }

        var windowTitle: String?
        if AXIsProcessTrusted() {
            attachAccessibilityObserver(processId: application.processIdentifier)
            windowTitle = readFocusedWindowTitle()
        }
        onObservation(
            DesktopObservation(
                appBundleId: appBundleId,
                appName: appName,
                windowTitle: windowTitle,
                isScreenLocked: isScreenLocked,
                isSecureInputEnabled: secureInputEnabled
            )
        )
    }

    private func attachAccessibilityObserver(processId: pid_t) {
        detachAccessibilityObserver()
        let applicationElement = AXUIElementCreateApplication(processId)
        var newObserver: AXObserver?
        guard AXObserverCreate(
            processId,
            handleAccessibilityNotification,
            &newObserver
        ) == .success,
        let newObserver
        else {
            return
        }
        let reference = Unmanaged.passUnretained(self).toOpaque()
        guard AXObserverAddNotification(
            newObserver,
            applicationElement,
            kAXFocusedWindowChangedNotification as CFString,
            reference
        ) == .success
        else {
            return
        }
        accessibilityObserver = newObserver
        observedApplication = applicationElement
        CFRunLoopAddSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(newObserver),
            .commonModes
        )
        attachTitleNotification(reference: reference)
    }

    private func attachTitleNotification(reference: UnsafeMutableRawPointer) {
        guard let accessibilityObserver,
              let focusedWindow = copyFocusedWindow()
        else {
            return
        }
        let result = AXObserverAddNotification(
            accessibilityObserver,
            focusedWindow,
            kAXTitleChangedNotification as CFString,
            reference
        )
        if result == .success || result == .notificationAlreadyRegistered {
            observedWindow = focusedWindow
        }
    }

    private func readFocusedWindowTitle() -> String? {
        guard let focusedWindow = copyFocusedWindow() else {
            return nil
        }
        var titleValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            focusedWindow,
            kAXTitleAttribute as CFString,
            &titleValue
        ) == .success
        else {
            return nil
        }
        return (titleValue as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func copyFocusedWindow() -> AXUIElement? {
        guard let observedApplication else {
            return nil
        }
        var windowValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            observedApplication,
            kAXFocusedWindowAttribute as CFString,
            &windowValue
        ) == .success,
        let windowValue,
        CFGetTypeID(windowValue) == AXUIElementGetTypeID()
        else {
            return nil
        }
        return unsafeDowncast(windowValue, to: AXUIElement.self)
    }

    private func detachAccessibilityObserver() {
        if let accessibilityObserver {
            CFRunLoopRemoveSource(
                CFRunLoopGetMain(),
                AXObserverGetRunLoopSource(accessibilityObserver),
                .commonModes
            )
        }
        accessibilityObserver = nil
        observedApplication = nil
        observedWindow = nil
    }
}
