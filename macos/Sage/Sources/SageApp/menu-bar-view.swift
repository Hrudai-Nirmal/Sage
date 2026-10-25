/*
 The compact menu mirrors safe runtime and monitoring controls without creating a second conversation surface.
 */

import AppKit
import SageRuntime
import SwiftUI

struct MenuBarView: View {
    @ObservedObject var appState: AppState
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Button("Open Sage", systemImage: "macwindow") {
            openWindow(id: "main")
            NSApplication.shared.activate(ignoringOtherApps: true)
        }
        Divider()
        Text("Mode: \(appState.mode.rawValue.capitalized)")
        Text("Observer: \(appState.monitoringState.capitalized)")
        if appState.queuedEventCount > 0 {
            Text("Queued: \(appState.queuedEventCount)")
        }
        Divider()
        Menu("Sage Mode") {
            ForEach(SageMode.allCases, id: \.self) { mode in
                Button(mode.rawValue.capitalized) {
                    appState.requestMode(mode)
                }
                .disabled(
                    (appState.powerState.isOnBattery
                        || appState.powerState.isLowPowerModeEnabled)
                        && (mode == .normal || mode == .eco)
                )
            }
        }
        Menu("Monitoring") {
            Button("On") {
                appState.requestMonitoring(.on)
            }
            Button("Off") {
                appState.requestMonitoring(.off)
            }
        }
        Button("Refresh", systemImage: "arrow.clockwise") {
            appState.refresh()
        }
        Divider()
        Button("Quit Sage App", systemImage: "power") {
            NSApplication.shared.terminate(nil)
        }
    }
}
