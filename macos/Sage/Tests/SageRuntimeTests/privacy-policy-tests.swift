/*
 Native observation tests establish a conservative deny-by-context boundary before Accessibility APIs run.
 */

import Testing
@testable import SageRuntime

@Test("Permitted developer applications can be observed")
func permitsDeveloperApplication() {
    let decision = DesktopPrivacyPolicy.evaluate(
        appBundleId: "com.microsoft.VSCode",
        isScreenLocked: false,
        isSecureInputEnabled: false
    )

    #expect(decision == .allow)
}

@Test(
    "Sensitive and browser applications are denied",
    arguments: [
        "com.google.Chrome",
        "com.apple.Safari",
        "com.apple.keychainaccess",
        "com.1password.1password",
        "com.apple.MobileSMS",
        "com.apple.systempreferences",
    ]
)
func deniesExcludedApplication(appBundleId: String) {
    let decision = DesktopPrivacyPolicy.evaluate(
        appBundleId: appBundleId,
        isScreenLocked: false,
        isSecureInputEnabled: false
    )

    #expect(decision == .denyExcludedApplication)
}

@Test("Lock and Secure Input suppress collection")
func suppressesUncertainSensitiveState() {
    #expect(
        DesktopPrivacyPolicy.evaluate(
            appBundleId: "com.microsoft.VSCode",
            isScreenLocked: true,
            isSecureInputEnabled: false
        ) == .denyScreenLocked
    )
    #expect(
        DesktopPrivacyPolicy.evaluate(
            appBundleId: "com.microsoft.VSCode",
            isScreenLocked: false,
            isSecureInputEnabled: true
        ) == .denySecureInput
    )
}
