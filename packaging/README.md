# Packaging the desktop app

`nixync.spec` builds the Nixync host application (`src/front`) into a
self-contained directory, so someone can run it without Python, Qt or a checkout
of this repository. The result is `dist/nixync/` — plus `dist/Nixync.app` on
macOS.

PyInstaller cannot cross-compile: a Windows build has to run on Windows, a macOS
build on macOS. Either follow the steps for the platform you are on, or let
[CI build all four](#letting-ci-build-everything) and skip owning the machines.

Two build-time packages are needed everywhere on top of `requirements.txt`:

- `pyinstaller==6.22.3` — the version CI uses.
- `pillow` — not a runtime dependency. The app's icon is a PNG, and PyInstaller
  converts it to the `.ico`/`.icns` that Windows and macOS require. Without
  Pillow it fails rather than skipping the icon.

## Building for each platform

### NixOS

`nix develop` exports `LD_LIBRARY_PATH` from the flake's `qtRuntimeLibraries`,
which is where pip-installed PySide6 finds its native libraries. Those include
`krb5` and `brotli`: PyInstaller's PySide6 hook imports `QtNetwork`, so without
them the build fails before it starts.

```sh
nix develop                                   # creates .venv, sets LD_LIBRARY_PATH
pip install -r requirements.txt
pip install pyinstaller==6.22.3 pillow
pyinstaller packaging/nixync.spec --noconfirm
```

NixOS cannot run the result directly — there is no
`/lib64/ld-linux-x86-64.so.2`, and the binary is a generic-Linux executable by
design. That is not a broken build; the artifact is for other distributions. To
exercise it locally:

```sh
nix-shell -p steam-run --run "steam-run ./dist/nixync/nixync --self-check"
```

To develop the app rather than package it, use `nix develop` and run it from
source.

### Linux (Ubuntu/Debian)

This is what the released Linux artifact is built on. CI uses Ubuntu 22.04
rather than the newest image, because the binary links against the build
machine's glibc and an older one still runs on newer distributions, not the
reverse — build on the oldest release you intend to support.

```sh
sudo apt-get install -y python3.13 python3.13-venv git
# Qt links against these at load time.
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libdbus-1-3

git clone https://github.com/sol1drat/nixync && cd nixync
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller==6.22.3 pillow
pyinstaller packaging/nixync.spec --noconfirm

./dist/nixync/nixync --self-check
tar -czf nixync-linux-x86_64.tar.gz -C dist nixync
```

### Windows

Install Python 3.13 from python.org with **Add python.exe to PATH** ticked, then
in PowerShell:

```powershell
git clone https://github.com/sol1drat/nixync
cd nixync
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller==6.22.3 pillow
pyinstaller packaging\nixync.spec --noconfirm
```

That produces `dist\nixync\nixync.exe`.

Checking it needs one extra step. The executable is built windowed
(`console=False` in the spec, so no terminal sits behind the app), which means
it has no console to print to and a shell will not reliably wait on it.
`Start-Process` does both:

```powershell
$p = Start-Process .\dist\nixync\nixync.exe -ArgumentList '--self-check' `
       -Wait -PassThru -NoNewWindow `
       -RedirectStandardOutput out.txt -RedirectStandardError err.txt
Get-Content out.txt, err.txt
$p.ExitCode        # 0 means the build is sound

Compress-Archive dist\nixync\* nixync-windows-x86_64.zip
```

### macOS

Apple Silicon and Intel binaries are not interchangeable, so each architecture
builds on its own machine; CI covers both.

```sh
brew install python@3.13
git clone https://github.com/sol1drat/nixync && cd nixync
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller==6.22.3 pillow
pyinstaller packaging/nixync.spec --noconfirm

./dist/Nixync.app/Contents/MacOS/nixync --self-check
# ditto, not zip: it preserves the bundle's symlinks and permissions.
ditto -c -k --keepParent dist/Nixync.app nixync-macos.zip
```

The app is unsigned and unnotarised, so Gatekeeper blocks the first launch.
Open it from the right-click menu once, or clear the quarantine flag:

```sh
xattr -dr com.apple.quarantine dist/Nixync.app
```

## Letting CI build everything

`.github/workflows/release.yml` builds all four targets on their own runners —
Linux, Windows, macOS arm64 and macOS x86_64 — runs `--self-check` on each and
attaches the archives to a GitHub release:

```sh
git tag v0.1.0 && git push origin v0.1.0
```

Triggering the workflow by hand from the Actions tab builds everything without
publishing anything and leaves the archives as artifacts, which is how to test a
change to the workflow without spending a version number.

## Checking a build

```sh
./dist/nixync/nixync --self-check
```

A bundle can build cleanly and still fail on startup, because PyInstaller works
out what to include by reading imports statically and anything reached only at
runtime can go missing. `--self-check` imports every such module, confirms the
icons were copied and opens the login window off-screen, then exits non-zero
with a `FAIL` line per problem. CI runs it on all four targets before packaging;
it is also the quickest way to tell whether a local build is sound.

## Pointing a build at a server

The app defaults to `http://127.0.0.1:8000`, and the sign-in screen lets you type
a different address. To ship a default instead, put a `config.toml` next to the
executable:

```toml
server_url = "http://fleet.example:8000"
```

(Running from the repository it reads `src/front/config.toml` instead, and
`NIXYNC_CONFIG` overrides both.)
