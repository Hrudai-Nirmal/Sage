/*
 Native operator views favor scan-friendly system controls, dividers, and semantic status over decorative cards.
 */

import AppKit
import SageRuntime
import SwiftUI

private enum DashboardSection: String, CaseIterable, Identifiable {
    case overview = "Overview"
    case activity = "Activity"
    case privacy = "Privacy"
    case runtime = "Runtime"

    var id: String { rawValue }

    var symbolName: String {
        switch self {
        case .overview: "gauge.with.dots.needle.50percent"
        case .activity: "waveform.path.ecg"
        case .privacy: "hand.raised"
        case .runtime: "switch.2"
        }
    }
}

struct SageDashboardView: View {
    @ObservedObject var appState: AppState
    @State private var selection: DashboardSection? = .overview

    var body: some View {
        NavigationSplitView {
            List(DashboardSection.allCases, selection: $selection) { section in
                Label(section.rawValue, systemImage: section.symbolName)
                    .tag(section)
            }
            .navigationTitle("Sage")
            .navigationSplitViewColumnWidth(min: 180, ideal: 210)
        } detail: {
            detailView
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .toolbar {
                    ToolbarItem {
                        Button("Refresh", systemImage: "arrow.clockwise") {
                            appState.refresh()
                        }
                        .help("Refresh Sage Core and Observer status")
                    }
                }
        }
        .frame(minWidth: 820, minHeight: 560)
    }

    @ViewBuilder
    private var detailView: some View {
        switch selection ?? .overview {
        case .overview:
            OverviewView(appState: appState)
        case .activity:
            ActivityView(appState: appState)
        case .privacy:
            PrivacyView(appState: appState)
        case .runtime:
            RuntimeView(appState: appState)
        }
    }
}

private struct OverviewView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                PageHeading(
                    title: "Overview",
                    subtitle: "Local runtime, observation, and power policy at a glance."
                )
                if let lastError = appState.lastError {
                    Label(lastError, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .accessibilityLabel("Warning: \(lastError)")
                }
                StatusRows(appState: appState)
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    Text("Current Permitted Activity")
                        .font(.headline)
                    Text(appState.currentAppName)
                        .font(.title3.weight(.medium))
                    Text(appState.currentWindowTitle ?? "No accessible window title")
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            .padding(28)
            .frame(maxWidth: 760, alignment: .leading)
        }
    }
}

private struct ActivityView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            PageHeading(
                title: "Activity",
                subtitle: "Metadata-only desktop events. Chromium browsing arrives through the extension."
            )
            LabeledContent("Application", value: appState.currentAppName)
            LabeledContent(
                "Window",
                value: appState.currentWindowTitle ?? "Unavailable or excluded"
            )
            LabeledContent("Queued Events", value: "\(appState.queuedEventCount)")
            Divider()
            Text("The native collector observes app switches and accessible window titles. It does not capture browser windows, passwords, screenshots, microphone, or camera in this milestone.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
        }
        .padding(28)
        .frame(maxWidth: 760, alignment: .leading)
    }
}

private struct PrivacyView: View {
    @ObservedObject var appState: AppState

    private let excludedCategories = [
        "Browsers handled by the authenticated extension",
        "Password managers, Keychain, and authenticators",
        "Messaging and mail applications",
        "System Settings",
        "Locked screen or Secure Input sessions",
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                PageHeading(
                    title: "Privacy",
                    subtitle: "Collection is filtered locally before metadata reaches Core."
                )
                LabeledContent(
                    "Accessibility",
                    value: appState.hasAccessibilityPermission ? "Granted" : "Not Granted"
                )
                if !appState.hasAccessibilityPermission {
                    Button("Open Accessibility Settings") {
                        openPrivacySettings(anchor: "Privacy_Accessibility")
                    }
                }
                Divider()
                Text("Always Excluded")
                    .font(.headline)
                ForEach(excludedCategories, id: \.self) { category in
                    Label(category, systemImage: "nosign")
                        .foregroundStyle(.secondary)
                }
                Divider()
                Text("Screen capture is not active. When that later capability is added, it will require the separate macOS Screen Recording permission and the same local deny-first policy.")
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(28)
            .frame(maxWidth: 760, alignment: .leading)
        }
    }

    private func openPrivacySettings(anchor: String) {
        guard let settingsUrl = URL(
            string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)"
        ) else {
            return
        }
        NSWorkspace.shared.open(settingsUrl)
    }
}

private struct RuntimeView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            PageHeading(
                title: "Runtime",
                subtitle: "Normal and Eco are available only on external power with Low Power Mode off."
            )
            Picker("Sage Mode", selection: Binding(
                get: { appState.mode },
                set: { appState.requestMode($0) }
            )) {
                ForEach(SageMode.allCases, id: \.self) { mode in
                    Text(mode.rawValue.capitalized).tag(mode)
                }
            }
            .pickerStyle(.segmented)

            HStack(spacing: 10) {
                Button("Monitoring On") {
                    appState.requestMonitoring(.on)
                }
                .buttonStyle(.borderedProminent)
                Button("Monitoring Off") {
                    appState.requestMonitoring(.off)
                }
                .buttonStyle(.bordered)
            }
            Divider()
            LabeledContent(
                "Power Source",
                value: appState.powerState.isOnBattery ? "Battery" : "External Power"
            )
            LabeledContent(
                "Low Power Mode",
                value: appState.powerState.isLowPowerModeEnabled ? "On" : "Off"
            )
            LabeledContent(
                "Screen",
                value: appState.powerState.isScreenLocked ? "Locked" : "Unlocked"
            )
            Spacer()
        }
        .padding(28)
        .frame(maxWidth: 760, alignment: .leading)
    }
}

private struct StatusRows: View {
    @ObservedObject var appState: AppState

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 12) {
            StatusRow(
                label: "Core",
                value: appState.isCoreReachable ? "Connected" : "Offline",
                color: appState.isCoreReachable ? .green : .red
            )
            StatusRow(
                label: "Mode",
                value: appState.mode.rawValue.capitalized,
                color: appState.mode == .normal || appState.mode == .eco ? .green : .secondary
            )
            StatusRow(
                label: "Observer",
                value: appState.monitoringState.capitalized,
                color: appState.isObserverCollecting ? .green : .orange
            )
            StatusRow(
                label: "Power",
                value: appState.powerState.isOnBattery ? "Battery · forced Sleep" : "External Power",
                color: appState.powerState.isOnBattery ? .orange : .green
            )
        }
    }
}

private struct StatusRow: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        GridRow {
            Text(label)
                .foregroundStyle(.secondary)
                .frame(width: 92, alignment: .leading)
            HStack(spacing: 8) {
                Circle()
                    .fill(color)
                    .frame(width: 8, height: 8)
                    .accessibilityHidden(true)
                Text(value)
            }
        }
    }
}

private struct PageHeading: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.largeTitle.weight(.semibold))
            Text(subtitle)
                .foregroundStyle(.secondary)
        }
    }
}
