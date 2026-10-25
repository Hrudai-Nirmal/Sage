/*
 Event planning tests prevent duplicate foreground observations before network or database work begins.
 */

import Foundation
import Testing
@testable import SageRuntime

@Test("First permitted foreground app creates an activation event")
func plansInitialActivation() {
    let occurredAt = Date(timeIntervalSince1970: 1_798_000_000)
    let result = DesktopEventPlanner.plan(
        observation: DesktopObservation(
            appBundleId: "com.microsoft.VSCode",
            appName: "Visual Studio Code",
            windowTitle: "Sage"
        ),
        previousState: .empty,
        hostId: "hrudais-macbook-pro",
        occurredAt: occurredAt,
        eventId: "event-1"
    )

    #expect(result.event?.eventType == .applicationActivated)
    #expect(result.event?.windowTitle == "Sage")
    #expect(result.state.lastSignature == "com.microsoft.VSCode\u{1F}Sage")
}

@Test("Unchanged foreground metadata is suppressed")
func suppressesDuplicateObservation() {
    let occurredAt = Date(timeIntervalSince1970: 1_798_000_000)
    let observation = DesktopObservation(
        appBundleId: "com.microsoft.VSCode",
        appName: "Visual Studio Code",
        windowTitle: "Sage"
    )
    let first = DesktopEventPlanner.plan(
        observation: observation,
        previousState: .empty,
        hostId: "hrudais-macbook-pro",
        occurredAt: occurredAt,
        eventId: "event-1"
    )
    let duplicate = DesktopEventPlanner.plan(
        observation: observation,
        previousState: first.state,
        hostId: "hrudais-macbook-pro",
        occurredAt: occurredAt.addingTimeInterval(30),
        eventId: "event-2"
    )

    #expect(duplicate.event == nil)
    #expect(duplicate.state == first.state)
}

@Test("Window title changes are debounced for five seconds")
func debouncesWindowTitleChanges() {
    let occurredAt = Date(timeIntervalSince1970: 1_798_000_000)
    let first = DesktopEventPlanner.plan(
        observation: DesktopObservation(
            appBundleId: "com.microsoft.VSCode",
            appName: "Visual Studio Code",
            windowTitle: "Sage"
        ),
        previousState: .empty,
        hostId: "hrudais-macbook-pro",
        occurredAt: occurredAt,
        eventId: "event-1"
    )
    let tooSoon = DesktopEventPlanner.plan(
        observation: DesktopObservation(
            appBundleId: "com.microsoft.VSCode",
            appName: "Visual Studio Code",
            windowTitle: "context.md"
        ),
        previousState: first.state,
        hostId: "hrudais-macbook-pro",
        occurredAt: occurredAt.addingTimeInterval(4),
        eventId: "event-2"
    )
    let accepted = DesktopEventPlanner.plan(
        observation: DesktopObservation(
            appBundleId: "com.microsoft.VSCode",
            appName: "Visual Studio Code",
            windowTitle: "context.md"
        ),
        previousState: first.state,
        hostId: "hrudais-macbook-pro",
        occurredAt: occurredAt.addingTimeInterval(5),
        eventId: "event-3"
    )

    #expect(tooSoon.event == nil)
    #expect(accepted.event?.eventType == .windowChanged)
    #expect(accepted.event?.activeDurationSeconds == 5)
}

@Test("Excluded apps never produce event payloads")
func suppressesExcludedObservation() {
    let result = DesktopEventPlanner.plan(
        observation: DesktopObservation(
            appBundleId: "com.google.Chrome",
            appName: "Google Chrome",
            windowTitle: "Private"
        ),
        previousState: .empty,
        hostId: "hrudais-macbook-pro",
        occurredAt: Date(),
        eventId: "event-1"
    )

    #expect(result.event == nil)
    #expect(result.privacyDecision == .denyExcludedApplication)
}
