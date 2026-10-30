# App icon assets

- `AppIcon.icns` — macOS app icon (built from `AppIcon.png` via Pillow + iconutil)
- `AppIcon.png` — 1024×1024 master PNG

Design: two session cards exchanging via bidirectional arrows on a deep blue→violet squircle.
Used by `build.sh` (copied to `Contents/Resources/AppIcon.icns`, `Info.plist` → `CFBundleIconFile=AppIcon`).
