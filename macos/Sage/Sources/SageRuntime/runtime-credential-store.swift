/*
 The unsigned local app reads only its two scoped tokens from Core's protected host file.
 This avoids unstable ad-hoc code-signing ACLs while keeping secrets out of app resources.
 */

import Foundation

/// Credentials used only for native runtime controls and desktop event ingress.
public struct RuntimeCredentials: Equatable, Sendable {
    public let nativeObserverToken: String
    public let operatorToken: String

    /// Create one immutable pair of scoped native credentials.
    public init(nativeObserverToken: String, operatorToken: String) {
        self.nativeObserverToken = nativeObserverToken
        self.operatorToken = operatorToken
    }
}

/// Safe configuration failures that never reveal credential values.
public enum RuntimeCredentialError: Error, Equatable, Sendable {
    case insecurePermissions
    case missingCredential
    case unreadableFile
}

/// Reads exact values from the existing mode-600 Core environment file.
public struct RuntimeCredentialStore: Sendable {
    private let environmentUrl: URL

    /// Bind the reader to one explicit local Core configuration file.
    public init(environmentUrl: URL) {
        self.environmentUrl = environmentUrl
    }

    /// Return only the native credentials, ignoring all unrelated private settings.
    public func readCredentials() throws -> RuntimeCredentials {
        let fileAttributes: [FileAttributeKey: Any]
        let fileText: String
        do {
            fileAttributes = try FileManager.default.attributesOfItem(
                atPath: environmentUrl.path
            )
            fileText = try String(contentsOf: environmentUrl, encoding: .utf8)
        } catch {
            throw RuntimeCredentialError.unreadableFile
        }
        guard let permissions = fileAttributes[.posixPermissions] as? NSNumber,
              permissions.intValue & 0o077 == 0
        else {
            throw RuntimeCredentialError.insecurePermissions
        }

        var nativeObserverToken: String?
        var operatorToken: String?
        for rawLine in fileText.split(whereSeparator: \Character.isNewline) {
            let line = String(rawLine)
            let assignment = line.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard assignment.count == 2 else {
                continue
            }
            let variableName = String(assignment[0])
            let variableValue = String(assignment[1])
            if variableName == "SAGE_NATIVE_OBSERVER_TOKEN" {
                nativeObserverToken = variableValue
            } else if variableName == "SAGE_OPERATOR_TOKEN" {
                operatorToken = variableValue
            }
        }
        guard let nativeObserverToken, !nativeObserverToken.isEmpty,
              let operatorToken, !operatorToken.isEmpty
        else {
            throw RuntimeCredentialError.missingCredential
        }
        return RuntimeCredentials(
            nativeObserverToken: nativeObserverToken,
            operatorToken: operatorToken
        )
    }
}
