/*
 A small disk-backed FIFO preserves permitted metadata through Core restarts without unbounded storage growth.
 */

import Foundation

/// Configuration and persistence failures for the native event queue.
public enum DesktopEventQueueError: Error, Equatable, Sendable {
    case invalidCapacity
}

/// Serializes bounded desktop events to one app-owned JSON file.
public actor DesktopEventQueue {
    private let storageUrl: URL
    private let capacity: Int
    private let fileManager: FileManager

    /// Create a durable queue with an explicit positive capacity.
    public init(
        storageUrl: URL,
        capacity: Int,
        fileManager: FileManager = .default
    ) throws {
        guard capacity > 0 else {
            throw DesktopEventQueueError.invalidCapacity
        }
        self.storageUrl = storageUrl
        self.capacity = capacity
        self.fileManager = fileManager
    }

    /// Append an event once and evict oldest entries beyond the configured bound.
    public func enqueue(_ event: DesktopEvent) throws {
        var events = try loadEvents()
        guard !events.contains(where: { $0.eventId == event.eventId }) else {
            return
        }
        events.append(event)
        if events.count > capacity {
            events.removeFirst(events.count - capacity)
        }
        try saveEvents(events)
    }

    /// Return the oldest queued event without removing it.
    public func peek() throws -> DesktopEvent? {
        try loadEvents().first
    }

    /// Remove one acknowledged event while preserving FIFO order.
    public func remove(eventId: String) throws {
        let normalizedEventId = eventId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedEventId.isEmpty else {
            return
        }
        let events = try loadEvents().filter { $0.eventId != normalizedEventId }
        try saveEvents(events)
    }

    /// Return the current bounded queue length for status UI.
    public func count() throws -> Int {
        try loadEvents().count
    }

    private func loadEvents() throws -> [DesktopEvent] {
        guard fileManager.fileExists(atPath: storageUrl.path) else {
            return []
        }
        let eventData = try Data(contentsOf: storageUrl)
        return try CoreJsonCoding.decoder.decode([DesktopEvent].self, from: eventData)
    }

    private func saveEvents(_ events: [DesktopEvent]) throws {
        let parentUrl = storageUrl.deletingLastPathComponent()
        try fileManager.createDirectory(
            at: parentUrl,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let eventData = try CoreJsonCoding.encoder.encode(events)
        try eventData.write(to: storageUrl, options: [.atomic, .completeFileProtection])
        try fileManager.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: storageUrl.path
        )
    }
}
