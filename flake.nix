{
  description = "Nixync development environment and native Linux package";

  inputs.nixpkgs.url = "https://flakehub.com/f/NixOS/nixpkgs/0.1";

  outputs =
    { self, ... }@inputs:
    let
      inherit (inputs.nixpkgs) lib;

      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      linuxSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forEachSupportedSystem =
        f:
        lib.genAttrs supportedSystems (
          system:
          f {
            inherit system;
            pkgs = import inputs.nixpkgs { inherit system; };
          }
        );

      concatMajorMinor =
        v:
        lib.pipe v [
          lib.versions.splitVersion
          (lib.sublist 0 2)
          lib.concatStrings
        ];

      # Change this when upgrading Python.
      # Delete .venv afterward to recreate it.
      version = "3.13";
    in
    {
      # Development environment.
      devShells = forEachSupportedSystem (
        { pkgs, system }:
        let
          python = pkgs."python${concatMajorMinor version}";

          # Native runtime libraries for pip-installed PySide6.
          qtRuntimeLibraries =
            if pkgs.stdenv.hostPlatform.isLinux then
              (with pkgs; [
                stdenv.cc.cc.lib
                glib
                zlib
                zstd
                libGL
                libxkbcommon
                wayland
                dbus
                fontconfig
                freetype
                krb5
                brotli

                # X11 libraries.
                libx11
                libxext
                libxrender
                libxi
                libxcursor
                libxrandr
                libxfixes
                libxinerama
                libxcomposite
                libxdamage
                libxcb

                # XCB utilities.
                libxcb-util
                libxcb-cursor
                libxcb-image
                libxcb-keysyms
                libxcb-render-util
                libxcb-wm
              ])
            else
              [ ];
        in
        {
          default = pkgs.mkShellNoCC {
            venvDir = ".venv";

            packages = [
              python
            ]
            ++ (with python.pkgs; [
              venvShellHook
              pip
            ])
            ++ [
              self.formatter.${system}
            ];

            # Do not scan the entire Nix store for libraries.
            LD_LIBRARY_PATH = lib.optionalString pkgs.stdenv.hostPlatform.isLinux (
              lib.makeLibraryPath qtRuntimeLibraries
            );

            postShellHook = ''
              venvVersionWarn() {
                local venvVersion
                venvVersion="$("$venvDir/bin/python" -c \
                  'import platform; print(platform.python_version())')"

                [[ "$venvVersion" == "${python.version}" ]] && return

                cat <<EOF
              Warning: Python version mismatch: [$venvVersion (venv)] != [${python.version}]
                       Delete '$venvDir' and reload to rebuild for version ${python.version}
              EOF
              }

              venvVersionWarn
            '';
          };
        }
      );

      # Native Nix package for Linux.
      packages = lib.genAttrs linuxSystems (
        system:
        let
          pkgs = import inputs.nixpkgs { inherit system; };

          python = pkgs."python${concatMajorMinor version}";

          # Runtime dependencies for the Nixync application.
          # These use Nixpkgs packages, not the development .venv.
          pythonEnv = python.withPackages (
            ps: with ps; [
              pyside6
              requests
              websockets
              pydantic
              fastapi
              uvicorn
              anthropic
            ]
          );

          nixync = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixync";
            version = "0.1.0";

            src = self;

            dontBuild = true;

            nativeBuildInputs = [
              pkgs.makeWrapper
              pkgs.qt6.wrapQtAppsHook
            ];

            buildInputs = [
              pythonEnv
              pkgs.qt6.qtbase
            ];

            # Generated theme SVGs must not be written to the
            # read-only Nix store alongside the bundled source.
            postPatch = ''
                            substituteInPlace src/shared/nixync_ui/style.py \
                              --replace-fail \
                                'from pathlib import Path' \
                                'from pathlib import Path
              import os' \
                              --replace-fail \
                                'ICONS = Path(__file__).resolve().parent / "icons"' \
                                'ICONS = Path(__file__).resolve().parent / "icons"
              GENERATED_ICONS = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "nixync" / "icons"
              GENERATED_ICONS.mkdir(parents=True, exist_ok=True)' \
                              --replace-fail \
                                'path = ICONS / f"chevron-down-' \
                                'path = GENERATED_ICONS / f"chevron-down-' \
                              --replace-fail \
                                'path = ICONS / f"check-' \
                                'path = GENERATED_ICONS / f"check-' \
                              --replace-fail \
                                'path = ICONS / f"dash-' \
                                'path = GENERATED_ICONS / f"dash-'
            '';

            installPhase = ''
              runHook preInstall

              mkdir -p \
                "$out/bin" \
                "$out/share/nixync" \
                "$out/share/applications"

              # Preserve the sibling Python package layout.
              cp -r src "$out/share/nixync/"

              # Launch the GUI through the Nix-managed Python environment.
              makeWrapper "${pythonEnv}/bin/python" "$out/bin/nixync" \
                --add-flags "-m nixync_front" \
                --set PYTHONPATH \
                  "$out/share/nixync/src/front:$out/share/nixync/src/shared:$out/share/nixync/src/back/client"

              # Desktop application launcher.
              cat > "$out/share/applications/nixync.desktop" <<EOF
              [Desktop Entry]
              Type=Application
              Name=Nixync
              Comment=Manage a fleet of NixOS machines
              Exec=$out/bin/nixync
              Icon=$out/share/nixync/src/shared/nixync_ui/icons/app-icon.png
              Terminal=false
              Categories=System;Network;
              EOF

              runHook postInstall
            '';

            meta = {
              description = "Nixync fleet management desktop application";
              mainProgram = "nixync";
              platforms = linuxSystems;
            };
          };
        in
        {
          default = nixync;
          nixync = nixync;
        }
      );

      # Formatter.
      formatter = forEachSupportedSystem (
        { pkgs, ... }:
        pkgs.nixfmt
      );
    };
}
