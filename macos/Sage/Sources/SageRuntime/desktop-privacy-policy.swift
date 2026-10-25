/*
 This policy suppresses native observation before titles or accessibility trees cross a process boundary.
 */

import Foundation

/// Why one foreground application may or may not be observed.
public enum DesktopPrivacyDecision: Equatable, Sendable {
    case allow
    case denyExcludedApplication
    case denyScreenLocked
    case denySecureInput
}

/// Conservative native application exclusions shared by collector and tests.
public enum DesktopPrivacyPolicy {
    private static let excludedBundleMarkers = [
        "1password",
        "authenticator",
        "bitwarden",
        "chrome",
        "chromium",
        "keychain",
        "lastpass",
        "microsoft.edgemac",
        "mobilesms",
        "onepassword",
        "safari",
        "signal",
        "slack",
        "systempreferences",
        "telegram",
        "whatsapp",
    ]

    /// Decide whether any metadata may be collected for the foreground process.
    public static func evaluate(
        appBundleId: String,
        isScreenLocked: Bool,
        isSecureInputEnabled: Bool
    ) -> DesktopPrivacyDecision {
        if isScreenLocked {
            return .denyScreenLocked
        }
        if isSecureInputEnabled {
            return .denySecureInput
        }
        let normalizedBundleId = appBundleId.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        if normalizedBundleId.isEmpty
            || excludedBundleMarkers.contains(where: normalizedBundleId.contains)
        {
            return .denyExcludedApplication
        }
        return .allow
    }
}
