# Packaging the desktop app

`nixync.spec` builds the Nixync host application (`src/front`) into a
self-contained directory, so someone can run it without Python, Qt or a checkout
of this repository.

## Building

```sh
pip install -r requirements.txt
pip install pyinstaller==6.22.3 pillow
pyinstaller packaging/nixync.spec --noconfirm
```

The result is `dist/nixync/` (plus `dist/Nixync.app` on macOS).

Pillow is only needed at build time: the app's icon is a PNG, and PyInstaller
converts it to the `.ico`/`.icns` that Windows and macOS want.

PyInstaller cannot cross-compile. A Windows build has to run on Windows, a macOS
build on macOS. `.github/workflows/release.yml` does all four on their own
runners and attaches the archives to a release when a `v*` tag is pushed:

```sh
git tag v0.1.0 && git push origin v0.1.0
```

Running that workflow manually builds everything without publishing anything,
which is how to test a change to it.

## Checking a build

```sh
./dist/nixync/nixync --self-check
```

A bundle can build cleanly and still fail on startup, because PyInstaller works
out what to include by reading imports statically and anything reached only at
runtime can go missing. `--self-check` imports every such module, confirms the
icons were copied and opens the login window off-screen, then exits. CI runs it
on all four targets; it is also the quickest way to tell whether a local build is
sound.

## Pointing a build at a server

The app defaults to `http://127.0.0.1:8000`, and the sign-in screen lets you type
a different address. To ship a default instead, put a `config.toml` next to the
executable:

```toml
server_url = "http://fleet.example:8000"
```

(Running from the repository it reads `src/front/config.toml` instead, and
`NIXYNC_CONFIG` overrides both.)

## Building on NixOS

The binary PyInstaller produces is a generic-Linux executable, so NixOS itself
cannot run it — there is no `/lib64/ld-linux-x86-64.so.2`. That is expected; the
artifact is for other distributions. To try it locally anyway:

```sh
nix-shell -p steam-run --run "steam-run ./dist/nixync/nixync"
```

For developing the app on NixOS, use `nix develop` and run it from source.
