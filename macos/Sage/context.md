# Native Sage App Context

## Purpose

Provide one local macOS operator surface and an event-driven desktop metadata collector without creating another conversational agent.

## Decisions

- The app is a SwiftUI menu-bar and normal-window application built with Apple frameworks only.
- App startup is owned by `AppState`, not window visibility, because macOS can restore a menu-bar app without recreating its main window.
- Foreground application changes use `NSWorkspace` notifications. Accessible window-title changes use AX notifications; neither path polls or records the screen.
- Browser applications, password/authentication tools, messaging apps, System Settings, locked screens, and Secure Input are denied before title access.
- Native events use a dedicated Core ingress token. Runtime controls use the operator token. The unsigned local app reads only those two values from the existing mode-`0600` Core environment file; it never sources that file through a shell or reads approval credentials.
- A disk-backed FIFO retains at most 1,000 permitted events through Core outages. Events are removed only after a successful Core acknowledgement.
- Battery power or Low Power Mode immediately forces Sleep and stops collection. The prior Normal or Eco mode is restored only when that sleep was power-forced, external power returns, Low Power Mode is off, and the screen is unlocked.
- The visual reference is standard macOS utility software: system typography, semantic colors, SF Symbols, a native split pane, and native controls. Decorative card grids and custom chrome are intentionally avoided.
- Dashboard navigation keeps one non-optional section selected. The app uses `HSplitView` with explicit sidebar buttons because `NavigationSplitView` dropped its rendered layer on section changes on this macOS build even though its accessibility tree remained populated.

## Gotchas

- Ad-hoc signatures change when the executable changes, so binary-bound Keychain ACLs block unattended local rebuilds. Runtime credentials remain in Core's already-protected host file instead.
- `SageMode` validation remains code-owned. The UI keeps Sleep and Shutdown selectable on battery while `AppState` rejects Normal or Eco with a clear warning.
- Browsers are observed only by the Chromium extension; the native app never reads browser window titles.
- Screen capture, OCR, and vision classification are not active in this slice. Their separate permission and deny-first pipeline must be added before any screenshot API is called.
