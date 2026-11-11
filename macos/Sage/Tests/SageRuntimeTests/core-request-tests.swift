/*
 Loopback request tests prevent credentials from leaking into URLs or crossing API boundaries.
 */

import Foundation
import Testing
@testable import SageRuntime

@Test("Mode requests use the privileged operator header")
func buildsModeRequest() throws {
    let request = try CoreRequestFactory(baseUrl: URL(string: "http://127.0.0.1:8787")!)
        .makeModeRequest(mode: .eco, operatorToken: "operator-secret")

    #expect(request.httpMethod == "PATCH")
    #expect(request.url?.absoluteString == "http://127.0.0.1:8787/v1/system/mode")
    #expect(request.value(forHTTPHeaderField: "X-Sage-Operator-Token") == "operator-secret")
    #expect(request.url?.absoluteString.contains("operator-secret") == false)
    #expect(request.httpBody == Data(#"{"mode":"ECO"}"#.utf8))
}

@Test("Desktop events use only the native observer credential")
func buildsDesktopEventRequest() throws {
    let event = DesktopEvent(
        activeDurationSeconds: 30,
        appBundleId: "com.microsoft.VSCode",
        appName: "Visual Studio Code",
        eventId: "event-1",
        eventType: .windowChanged,
        hostId: "hrudais-macbook-pro",
        occurredAt: Date(timeIntervalSince1970: 1_798_000_000),
        windowTitle: "Sage"
    )
    let request = try CoreRequestFactory(baseUrl: URL(string: "http://127.0.0.1:8787")!)
        .makeDesktopEventRequest(event: event, nativeObserverToken: "native-secret")

    #expect(request.httpMethod == "POST")
    #expect(request.url?.path == "/v1/observer/desktop-events")
    #expect(request.value(forHTTPHeaderField: "X-Sage-Native-Observer-Token") == "native-secret")
    #expect(request.value(forHTTPHeaderField: "X-Sage-Operator-Token") == nil)
    #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
}

@Test("Empty credentials are rejected before network access")
func rejectsEmptyCredential() {
    #expect(throws: CoreRequestError.missingCredential) {
        try CoreRequestFactory(baseUrl: URL(string: "http://127.0.0.1:8787")!)
            .makeModeRequest(mode: .normal, operatorToken: "  ")
    }
}

@Test("Desktop event JSON uses Core contract names and timezone")
func encodesDesktopEventContract() throws {
    let event = DesktopEvent(
        activeDurationSeconds: nil,
        appBundleId: "com.apple.Preview",
        appName: "Preview",
        eventId: "event-2",
        eventType: .applicationActivated,
        hostId: "hrudais-macbook-pro",
        occurredAt: Date(timeIntervalSince1970: 1_798_000_000),
        windowTitle: "Observer Architecture.pdf"
    )

    let jsonObject = try JSONSerialization.jsonObject(
        with: CoreJsonCoding.encoder.encode(event)
    ) as? [String: Any]

    #expect(jsonObject?["eventType"] as? String == "APPLICATION_ACTIVATED")
    #expect((jsonObject?["occurredAt"] as? String)?.contains("T") == true)
    #expect(jsonObject?["activeDurationSeconds"] == nil)
}

@Test("Observer controls use the operator credential and PATCH contract")
func buildsObserverControlRequest() throws {
    let request = try CoreRequestFactory(baseUrl: URL(string: "http://127.0.0.1:8787")!)
        .makeObserverControlRequest(
            monitoringState: .paused,
            pauseUntil: "2026-10-25T12:00:00+05:30",
            operatorToken: "operator-secret"
        )

    #expect(request.httpMethod == "PATCH")
    #expect(request.url?.path == "/v1/observer/status")
    #expect(request.value(forHTTPHeaderField: "X-Sage-Operator-Token") == "operator-secret")
    #expect(
        request.httpBody
            == Data(
                #"{"monitoringState":"PAUSED","pauseUntil":"2026-10-25T12:00:00+05:30"}"#.utf8
            )
    )
}

@Test("Memory search encodes a bounded query without credentials")
func buildsObserverMemorySearchRequest() throws {
    let request = try CoreRequestFactory(baseUrl: URL(string: "http://127.0.0.1:8787")!)
        .makeObserverMemorySearchRequest(query: "dive watches & bezels", resultLimit: 20)

    #expect(request.httpMethod == "GET")
    #expect(request.url?.path == "/v1/observer/memories")
    let queryItems = try #require(request.url).queryItems
    #expect(queryItems["query"] == "dive watches & bezels")
    #expect(queryItems["resultLimit"] == "20")
    #expect(request.allHTTPHeaderFields?.isEmpty != false)
}

@Test("Memory search rejects invalid local bounds before network access")
func rejectsInvalidObserverMemorySearchBounds() throws {
    let requestFactory = try CoreRequestFactory(
        baseUrl: URL(string: "http://127.0.0.1:8787")!
    )

    #expect(throws: CoreRequestError.invalidSearchBounds) {
        try requestFactory.makeObserverMemorySearchRequest(query: "watch", resultLimit: 101)
    }
    #expect(throws: CoreRequestError.invalidSearchBounds) {
        try requestFactory.makeObserverMemorySearchRequest(
            query: String(repeating: "a", count: 2_001),
            resultLimit: 20
        )
    }
}

@Test("Memory evidence addresses one validated local memory")
func buildsObserverMemoryEvidenceRequest() throws {
    let requestFactory = try CoreRequestFactory(
        baseUrl: URL(string: "http://127.0.0.1:8787")!
    )
    let request = try requestFactory.makeObserverMemoryEvidenceRequest(memoryId: "memory-1")

    #expect(request.httpMethod == "GET")
    #expect(request.url?.path == "/v1/observer/memories/memory-1/evidence")
    #expect(throws: CoreRequestError.invalidIdentifier) {
        try requestFactory.makeObserverMemoryEvidenceRequest(memoryId: "../invalid")
    }
}

@Test("Observer memory contracts decode trust and evidence provenance")
func decodesObserverMemoryContracts() throws {
    let memoryJson = Data(
        #"[{"confidence":0.72,"evidenceCount":3,"firstSeenAt":"2026-10-20T08:00:00+00:00","id":"memory-1","independentSessionCount":2,"isUncertain":false,"lastSeenAt":"2026-10-25T09:30:00+00:00","memoryKind":"SEMANTIC","subjectKey":"watch:dive","summary":"Researched dive watches","trustLevel":"INFERRED"}]"#.utf8
    )
    let evidenceJson = Data(
        #"[{"eventId":"event-1","evidenceExcerpt":"Dive watch comparison","observedAt":"2026-10-25T09:30:00+00:00","sessionId":"session-1"}]"#.utf8
    )

    let memories = try CoreJsonCoding.decoder.decode([ObserverMemory].self, from: memoryJson)
    let evidence = try CoreJsonCoding.decoder.decode(
        [ObserverMemoryEvidence].self,
        from: evidenceJson
    )

    #expect(memories.first?.trustLevel == "INFERRED")
    #expect(memories.first?.confidence == 0.72)
    #expect(evidence.first?.sessionId == "session-1")
    #expect(evidence.first?.evidenceExcerpt == "Dive watch comparison")
}

private extension URL {
    var queryItems: [String: String] {
        URLComponents(url: self, resolvingAgainstBaseURL: false)?.queryItems?.reduce(into: [:]) {
            queryItems, queryItem in
            queryItems[queryItem.name] = queryItem.value
        } ?? [:]
    }
}
