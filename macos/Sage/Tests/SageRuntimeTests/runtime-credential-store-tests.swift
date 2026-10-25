/*
 Credential tests keep the unsigned local build independent from interactive Keychain ACL prompts.
 */

import Foundation
import Testing
@testable import SageRuntime

@Test("Credential store reads exact scoped tokens from the protected Core environment")
func readsRuntimeCredentials() throws {
    let environmentUrl = FileManager.default.temporaryDirectory
        .appending(path: UUID().uuidString)
        .appending(path: "core.env")
    try FileManager.default.createDirectory(
        at: environmentUrl.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try """
    # unrelated values remain private and ignored
    SAGE_OPERATOR_TOKEN=operator=value
    SAGE_NATIVE_OBSERVER_TOKEN=native-value
    SAGE_APPROVAL_TOKEN=approval-value
    """.write(to: environmentUrl, atomically: true, encoding: .utf8)
    try FileManager.default.setAttributes(
        [.posixPermissions: 0o600],
        ofItemAtPath: environmentUrl.path
    )

    let credentials = try RuntimeCredentialStore(environmentUrl: environmentUrl).readCredentials()

    #expect(credentials.operatorToken == "operator=value")
    #expect(credentials.nativeObserverToken == "native-value")
}

@Test("Credential store rejects a missing required token")
func rejectsIncompleteRuntimeCredentials() throws {
    let environmentUrl = FileManager.default.temporaryDirectory
        .appending(path: UUID().uuidString)
        .appending(path: "core.env")
    try FileManager.default.createDirectory(
        at: environmentUrl.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try "SAGE_OPERATOR_TOKEN=operator-value\n".write(
        to: environmentUrl,
        atomically: true,
        encoding: .utf8
    )
    try FileManager.default.setAttributes(
        [.posixPermissions: 0o600],
        ofItemAtPath: environmentUrl.path
    )

    #expect(throws: RuntimeCredentialError.missingCredential) {
        try RuntimeCredentialStore(environmentUrl: environmentUrl).readCredentials()
    }
}

@Test("Credential store rejects a file readable by other users")
func rejectsPermissiveRuntimeCredentialFile() throws {
    let environmentUrl = FileManager.default.temporaryDirectory
        .appending(path: UUID().uuidString)
        .appending(path: "core.env")
    try FileManager.default.createDirectory(
        at: environmentUrl.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try "SAGE_OPERATOR_TOKEN=operator\nSAGE_NATIVE_OBSERVER_TOKEN=native\n".write(
        to: environmentUrl,
        atomically: true,
        encoding: .utf8
    )
    try FileManager.default.setAttributes(
        [.posixPermissions: 0o644],
        ofItemAtPath: environmentUrl.path
    )

    #expect(throws: RuntimeCredentialError.insecurePermissions) {
        try RuntimeCredentialStore(environmentUrl: environmentUrl).readCredentials()
    }
}
