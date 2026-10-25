"""Verify the native Sage bundle and installer retain privacy and single-instance guarantees."""

from pathlib import Path
import plistlib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def testNativeAppInfoPlistDeclaresStableIdentityAndPermissions():
    """macOS needs a stable bundle identity for permissions and duplicate-process prevention."""
    with (PROJECT_ROOT / "macos/Sage/Resources/Info.plist").open("rb") as plistFile:
        appInfo = plistlib.load(plistFile)

    assert appInfo["CFBundleIdentifier"] == "in.hrudainirmal.sage"
    assert appInfo["CFBundleExecutable"] == "Sage"
    assert appInfo["LSMultipleInstancesProhibited"] is True
    assert appInfo["NSAccessibilityUsageDescription"]
    assert appInfo["NSScreenCaptureUsageDescription"]


def testNativeBuildCreatesAndAdHocSignsApplicationBundle():
    """The local build remains installable without a paid Developer ID certificate."""
    buildScript = (PROJECT_ROOT / "scripts/build-macos-app.sh").read_text()

    assert "swift build -c release" in buildScript
    assert 'appPath="${appInstallRoot}/Sage.app"' in buildScript
    assert 'codesign --force --deep --sign -' in buildScript
    assert "SAGE_OPERATOR_TOKEN=" not in buildScript
    assert "SAGE_NATIVE_OBSERVER_TOKEN=" not in buildScript


def testNativeInstallerUsesProtectedRuntimeConfigurationAndLoginAgent():
    """Installation leaves credentials in the existing mode-600 runtime file."""
    installScript = (PROJECT_ROOT / "scripts/install-macos-app.sh").read_text()
    launchAgent = (PROJECT_ROOT / "launchd/com.sage.desktop-app.plist.template").read_text()

    assert "security add-generic-password" not in installScript
    assert 'chmod 600 "${coreEnvironmentFile}"' in installScript
    assert 'pkill -TERM -f "^${appExecutable}$"' in installScript
    assert "launchctl bootstrap" in installScript
    assert "<key>RunAtLoad</key>" in launchAgent
    assert "<true/>" in launchAgent
    assert "<key>KeepAlive</key>" in launchAgent
    assert "<false/>" in launchAgent


def testRuntimeBootstrapCreatesIndependentNativeObserverCredential():
    """Desktop ingress must not share the browser extension or operator token."""
    bootstrapScript = (PROJECT_ROOT / "scripts/bootstrap-runtime.sh").read_text()

    assert "SAGE_NATIVE_OBSERVER_TOKEN=$(openssl rand -hex 32)" in bootstrapScript


def testNativeRuntimeStartsWithoutDependingOnMainWindowVisibility():
    """Menu-bar launches must start observation even when macOS restores no main window."""
    stateSource = (PROJECT_ROOT / "macos/Sage/Sources/SageApp/app-state.swift").read_text()
    appSource = (PROJECT_ROOT / "macos/Sage/Sources/SageApp/sage-app.swift").read_text()

    assert "start()" in stateSource.split("init()", maxsplit=1)[1].split("/// Start", maxsplit=1)[0]
    assert ".task {" not in appSource


def testNativeRuntimeReadsOnlyScopedCredentialsFromProtectedEnvironment():
    """The app must not embed tokens or source the private file through a shell."""
    credentialSource = (
        PROJECT_ROOT / "macos/Sage/Sources/SageRuntime/runtime-credential-store.swift"
    ).read_text()

    assert "SAGE_OPERATOR_TOKEN" in credentialSource
    assert "SAGE_NATIVE_OBSERVER_TOKEN" in credentialSource
    assert "SAGE_APPROVAL_TOKEN" not in credentialSource


def testRuntimeModeControlKeepsSleepAndShutdownAvailableOnBattery():
    """Power policy may reject Normal or Eco without disabling the whole mode control."""
    dashboardSource = (
        PROJECT_ROOT / "macos/Sage/Sources/SageApp/sage-dashboard-view.swift"
    ).read_text()

    assert ".disabled(appState.powerState.isOnBattery" not in dashboardSource


def testDashboardSectionSelectionCannotEnterEmptyState():
    """Section changes must avoid the split-view rendering path that blanked the window."""
    dashboardSource = (
        PROJECT_ROOT / "macos/Sage/Sources/SageApp/sage-dashboard-view.swift"
    ).read_text()

    assert "@State private var selection: DashboardSection = .overview" in dashboardSource
    assert "Button {\n                        selection = section" in dashboardSource
    assert "List(DashboardSection.allCases, selection:" not in dashboardSource
    assert "NavigationLink(value: section)" not in dashboardSource
    assert "HSplitView {" in dashboardSource
    assert "NavigationSplitView" not in dashboardSource
    assert "switch selection {" in dashboardSource
    assert "selection ??" not in dashboardSource


def testSageShutdownStopsTheLaunchedDesktopProcess():
    """Unloading the one-shot login agent must not leave its already-launched app alive."""
    shutdownScript = (PROJECT_ROOT / "scripts/shutdown-sage.sh").read_text()

    assert 'pkill -TERM -f "^${appExecutable}$"' in shutdownScript
