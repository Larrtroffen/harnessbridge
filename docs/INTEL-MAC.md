# Intel Mac support / Intel Mac 支持

Issue: [#1 Add Intel Mac Support](https://github.com/Larrtroffen/harnessbridge/issues/1)

## Status

HarnessBridge **v1.6.3** ships two portable builds:

| Mac | Artifact | Status |
|---|---|---|
| Apple Silicon (arm64) | `HarnessBridge-1.6.3-macos-arm64.dmg` | built and self-tested on Apple Silicon (`31 PASS`) |
| Intel (x86_64) | `HarnessBridge-1.6.3-macos-x86_64.dmg` | cross-compiled and structurally verified on Apple Silicon; **needs an Intel-Mac smoke test** |

The Intel build embeds an x86_64 Python 3.12 runtime and a cross-compiled x86_64 `zstd`;
the Swift app binary, Python runtime and zstd were all verified as `Mach-O 64-bit executable x86_64`.
The app is ad-hoc signed; the DMG mounts and signature-verifies.

The build host is an Apple Silicon Mac without Rosetta installed, so the Intel executable
cannot be executed there. This is why the Intel build is marked "needs an Intel-Mac smoke test"
rather than "runtime-tested". Intel users can right-click → Open on first launch (ad-hoc signing).

## Build

```bash
cd tools/HarnessBridgeApp
./build.sh --intel        # x86_64 portable app + DMG
./build.sh                # arm64 portable app + DMG
```

The Intel path downloads the x86_64 python-build-standalone runtime, cross-compiles
zstd 1.5.7 from source for x86_64, embeds the backend, and codesigns the app/DMG.
SwiftPM scratch dirs are separated per architecture (`.build-arm64`, `.build-x86_64`).

## Homebrew

The cask is per-architecture:

```ruby
on_arm do
  url ".../HarnessBridge-#{version}-macos-arm64.dmg"
  sha256 "..."
end
on_intel do
  url ".../HarnessBridge-#{version}-macos-x86_64.dmg"
  sha256 "..."
end
```

Intel users with a supported macOS get the x86_64 artifact automatically.

## Coverage/config

Both architectures share the same backend, coverage ledger and app features. The Intel build
contains the same 43 source adapters / 32 native writers and the same four coverage numbers as
the arm64 build.
