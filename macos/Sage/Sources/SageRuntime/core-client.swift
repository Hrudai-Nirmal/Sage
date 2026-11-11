/*
 Authenticated loopback transport keeps privileged and ingress credentials scoped to their endpoints.
 */

import Foundation

/// Failures detected before or while communicating with local Sage Core.
public enum CoreRequestError: Error, Equatable, Sendable {
    case invalidBaseUrl
    case invalidIdentifier
    case invalidSearchBounds
    case missingCredential
    case rejected(statusCode: Int)
}

private struct ModeUpdate: Codable, Sendable {
    let mode: SageMode
}

/// Builds auditable requests without placing secrets in URLs.
public struct CoreRequestFactory: Sendable {
    private let baseUrl: URL

    /// Bind requests to an HTTP loopback origin only.
    public init(baseUrl: URL) throws {
        guard baseUrl.scheme == "http",
              ["127.0.0.1", "localhost"].contains(baseUrl.host),
              baseUrl.user == nil,
              baseUrl.password == nil
        else {
            throw CoreRequestError.invalidBaseUrl
        }
        self.baseUrl = baseUrl
    }

    /// Build a read-only health request.
    public func makeSystemStatusRequest() -> URLRequest {
        makeRequest(path: "/v1/system/status", method: "GET")
    }

    /// Build a read-only effective Observer status request.
    public func makeObserverStatusRequest() -> URLRequest {
        makeRequest(path: "/v1/observer/status", method: "GET")
    }

    /// Build a bounded read-only Observer memory search.
    public func makeObserverMemorySearchRequest(
        query: String,
        resultLimit: Int
    ) throws -> URLRequest {
        guard query.count <= 2_000, (1...100).contains(resultLimit) else {
            throw CoreRequestError.invalidSearchBounds
        }
        let endpointUrl = baseUrl.appending(path: "v1/observer/memories")
        guard var components = URLComponents(
            url: endpointUrl,
            resolvingAgainstBaseURL: false
        ) else {
            throw CoreRequestError.invalidBaseUrl
        }
        components.queryItems = [
            URLQueryItem(name: "query", value: query),
            URLQueryItem(name: "resultLimit", value: String(resultLimit)),
        ]
        guard let requestUrl = components.url else {
            throw CoreRequestError.invalidBaseUrl
        }
        return makeRequest(url: requestUrl, method: "GET")
    }

    /// Build a read-only provenance request for one validated memory identifier.
    public func makeObserverMemoryEvidenceRequest(memoryId: String) throws -> URLRequest {
        let allowedCharacters = CharacterSet.alphanumerics.union(
            CharacterSet(charactersIn: "-_")
        )
        guard !memoryId.isEmpty,
              memoryId.count <= 100,
              memoryId.unicodeScalars.allSatisfy(allowedCharacters.contains)
        else {
            throw CoreRequestError.invalidIdentifier
        }
        return makeRequest(
            path: "/v1/observer/memories/\(memoryId)/evidence",
            method: "GET"
        )
    }

    /// Build an operator-authorized runtime mode change.
    public func makeModeRequest(mode: SageMode, operatorToken: String) throws -> URLRequest {
        try makeAuthenticatedJsonRequest(
            path: "/v1/system/mode",
            method: "PATCH",
            headerName: "X-Sage-Operator-Token",
            credential: operatorToken,
            payload: ModeUpdate(mode: mode)
        )
    }

    /// Build an ingress-only desktop metadata event request.
    public func makeDesktopEventRequest(
        event: DesktopEvent,
        nativeObserverToken: String
    ) throws -> URLRequest {
        try makeAuthenticatedJsonRequest(
            path: "/v1/observer/desktop-events",
            method: "POST",
            headerName: "X-Sage-Native-Observer-Token",
            credential: nativeObserverToken,
            payload: event
        )
    }

    /// Build an operator-authorized Observer collection change.
    public func makeObserverControlRequest(
        monitoringState: ObserverMonitoringState,
        pauseUntil: String?,
        operatorToken: String
    ) throws -> URLRequest {
        try makeAuthenticatedJsonRequest(
            path: "/v1/observer/status",
            method: "PATCH",
            headerName: "X-Sage-Operator-Token",
            credential: operatorToken,
            payload: ObserverMonitoringUpdate(
                monitoringState: monitoringState,
                pauseUntil: pauseUntil
            )
        )
    }

    private func makeAuthenticatedJsonRequest<Payload: Encodable>(
        path: String,
        method: String,
        headerName: String,
        credential: String,
        payload: Payload
    ) throws -> URLRequest {
        let normalizedCredential = credential.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedCredential.isEmpty else {
            throw CoreRequestError.missingCredential
        }
        var request = makeRequest(path: path, method: method)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(normalizedCredential, forHTTPHeaderField: headerName)
        request.httpBody = try CoreJsonCoding.encoder.encode(payload)
        return request
    }

    private func makeRequest(path: String, method: String) -> URLRequest {
        makeRequest(
            url: baseUrl.appending(path: path.trimmingPrefix("/")),
            method: method
        )
    }

    private func makeRequest(url: URL, method: String) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 5
        return request
    }
}

/// Executes bounded loopback calls for the native app.
public struct CoreClient: Sendable {
    private let requestFactory: CoreRequestFactory
    private let urlSession: URLSession

    /// Create a Core transport with an injectable session for tests.
    public init(requestFactory: CoreRequestFactory, urlSession: URLSession = .shared) {
        self.requestFactory = requestFactory
        self.urlSession = urlSession
    }

    /// Fetch the current Core health and mode.
    public func getSystemStatus() async throws -> SystemStatus {
        do {
            return try await execute(
                requestFactory.makeSystemStatusRequest(),
                responseType: SystemStatus.self
            )
        } catch {
            throw error
        }
    }

    /// Fetch the effective Observer collection state.
    public func getObserverStatus() async throws -> ObserverStatus {
        do {
            return try await execute(
                requestFactory.makeObserverStatusRequest(),
                responseType: ObserverStatus.self
            )
        } catch {
            throw error
        }
    }

    /// Search recent active Observer memories without loading the full store.
    public func searchObserverMemories(
        query: String,
        resultLimit: Int = 20
    ) async throws -> [ObserverMemory] {
        do {
            return try await execute(
                requestFactory.makeObserverMemorySearchRequest(
                    query: query,
                    resultLimit: resultLimit
                ),
                responseType: [ObserverMemory].self
            )
        } catch {
            throw error
        }
    }

    /// Fetch bounded evidence provenance for one Observer memory.
    public func getObserverMemoryEvidence(
        memoryId: String
    ) async throws -> [ObserverMemoryEvidence] {
        do {
            return try await execute(
                requestFactory.makeObserverMemoryEvidenceRequest(memoryId: memoryId),
                responseType: [ObserverMemoryEvidence].self
            )
        } catch {
            throw error
        }
    }

    /// Persist one explicit or power-policy runtime mode request.
    public func setMode(_ mode: SageMode, operatorToken: String) async throws -> SystemStatus {
        do {
            return try await execute(
                requestFactory.makeModeRequest(mode: mode, operatorToken: operatorToken),
                responseType: SystemStatus.self
            )
        } catch {
            throw error
        }
    }

    /// Persist one explicit Observer on, off, or paused state.
    public func setObserverMonitoring(
        _ monitoringState: ObserverMonitoringState,
        pauseUntil: String?,
        operatorToken: String
    ) async throws -> ObserverStatus {
        do {
            return try await execute(
                requestFactory.makeObserverControlRequest(
                    monitoringState: monitoringState,
                    pauseUntil: pauseUntil,
                    operatorToken: operatorToken
                ),
                responseType: ObserverStatus.self
            )
        } catch {
            throw error
        }
    }

    /// Submit one permitted metadata-only desktop event.
    public func submitDesktopEvent(
        _ event: DesktopEvent,
        nativeObserverToken: String
    ) async throws {
        do {
            let request = try requestFactory.makeDesktopEventRequest(
                event: event,
                nativeObserverToken: nativeObserverToken
            )
            let (_, response) = try await urlSession.data(for: request)
            try validate(response)
        } catch {
            throw error
        }
    }

    private func execute<Response: Decodable>(
        _ request: URLRequest,
        responseType: Response.Type
    ) async throws -> Response {
        do {
            let (responseData, response) = try await urlSession.data(for: request)
            try validate(response)
            return try CoreJsonCoding.decoder.decode(responseType, from: responseData)
        } catch {
            throw error
        }
    }

    private func validate(_ response: URLResponse) throws {
        guard let httpResponse = response as? HTTPURLResponse,
              (200..<300).contains(httpResponse.statusCode)
        else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw CoreRequestError.rejected(statusCode: statusCode)
        }
    }
}

private extension String {
    func trimmingPrefix(_ prefix: Character) -> String {
        first == prefix ? String(dropFirst()) : self
    }
}
