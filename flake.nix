{
  description = "A Nix-flake-based Python development environment";

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

      forEachSupportedSystem =
        f:
        lib.genAttrs supportedSystems (
          system:
          f {
            inherit system;
            pkgs = import inputs.nixpkgs { inherit system; };
          }
        );

      # Change this when upgrading Python.
      # Delete .venv afterward to recreate it.
      version = "3.13";
    in
    {
      devShells = forEachSupportedSystem (
        { pkgs, system }:
        let
          concatMajorMinor =
            v:
            lib.pipe v [
              lib.versions.splitVersion
              (lib.sublist 0 2)
              lib.concatStrings
            ];

          python = pkgs."python${concatMajorMinor version}";

          # Native runtime dependencies for pip-installed PySide6.
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

                # X11 libraries
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

                # XCB utilities
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

            # Use libraries from this flake's Nixpkgs revision.
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

      formatter = forEachSupportedSystem ({ pkgs, ... }: pkgs.nixfmt);
    };
}
