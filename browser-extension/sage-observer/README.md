# Sage Observer Chromium extension

The unpacked Manifest V3 extension supports Chrome, Brave, Edge, Arc, and Chromium. Load this directory from each browser profile's extension developer page, then open the extension options and paste the observation-ingress token shown by the future Sage macOS pairing screen.

The stable extension ID is `ehkgdljmlcdijndcbcjgcpphkogmjbod`. Core must allow the exact origin `chrome-extension://ehkgdljmlcdijndcbcjgcpphkogmjbod`.

This initial collector records permitted navigation, search terms derived from Google result URLs, bounded visible semantic text after a five-second debounce, idle/resume state, and YouTube metadata after 50% playback. It never collects incognito activity, inputs, keystrokes, clipboard contents, downloads, captions, or payment/password fields.
