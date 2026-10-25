/*
 Queue tests guarantee that temporary Core outages neither drop events nor grow storage without a bound.
 */

import Foundation
import Testing
@testable import SageRuntime

@Test("Queue persists FIFO events across instances")
func persistsQueuedEvents() async throws {
    let queueUrl = FileManager.default.temporaryDirectory
        .appending(path: UUID().uuidString)
        .appending(path: "desktop-events.json")
    let firstQueue = try DesktopEventQueue(storageUrl: queueUrl, capacity: 3)
    let firstEvent = makeQueuedEvent(eventId: "event-1")
    let secondEvent = makeQueuedEvent(eventId: "event-2")

    try await firstQueue.enqueue(firstEvent)
    try await firstQueue.enqueue(secondEvent)
    let restoredQueue = try DesktopEventQueue(storageUrl: queueUrl, capacity: 3)

    #expect(try await restoredQueue.peek()?.eventId == "event-1")
    try await restoredQueue.remove(eventId: "event-1")
    #expect(try await restoredQueue.peek()?.eventId == "event-2")
}

@Test("Queue evicts its oldest event at the capacity bound")
func boundsQueuedEvents() async throws {
    let queueUrl = FileManager.default.temporaryDirectory
        .appending(path: UUID().uuidString)
        .appending(path: "desktop-events.json")
    let queue = try DesktopEventQueue(storageUrl: queueUrl, capacity: 2)

    try await queue.enqueue(makeQueuedEvent(eventId: "event-1"))
    try await queue.enqueue(makeQueuedEvent(eventId: "event-2"))
    try await queue.enqueue(makeQueuedEvent(eventId: "event-3"))

    #expect(try await queue.count() == 2)
    #expect(try await queue.peek()?.eventId == "event-2")
}

private func makeQueuedEvent(eventId: String) -> DesktopEvent {
    DesktopEvent(
        activeDurationSeconds: 30,
        appBundleId: "com.microsoft.VSCode",
        appName: "Visual Studio Code",
        eventId: eventId,
        eventType: .windowChanged,
        hostId: "hrudais-macbook-pro",
        occurredAt: Date(timeIntervalSince1970: 1_798_000_000),
        windowTitle: "Sage"
    )
}
