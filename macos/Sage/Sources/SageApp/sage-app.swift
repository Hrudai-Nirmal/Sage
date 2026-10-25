/*
 The application shell will host one normal window and one lightweight menu-bar control surface.
 */

import SwiftUI

@main
struct SageApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        Window("Sage", id: "main") {
            SageDashboardView(appState: appState)
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    appState.stop()
                }
        }
        .defaultSize(width: 920, height: 640)

        MenuBarExtra {
            MenuBarView(appState: appState)
        } label: {
            Image(
                systemName: appState.isObserverCollecting
                    ? "eye.circle.fill"
                    : "eye.slash.circle"
            )
            .accessibilityLabel(
                appState.isObserverCollecting ? "Sage monitoring on" : "Sage monitoring off"
            )
        }
    }
}
