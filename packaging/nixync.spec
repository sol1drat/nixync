# PyInstaller spec for the Nixync host application.
#
#   pyinstaller packaging/nixync.spec --noconfirm
#
# Building for Windows or macOS also needs Pillow installed: the icon below is a
# PNG, and PyInstaller converts it to .ico/.icns only when Pillow is available.
#
# PyInstaller cannot cross-compile, so each platform's build runs on its own
# machine — see .github/workflows/release.yml for the matrix that does it.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

# The app lives in three sibling packages that the repository puts on sys.path at
# runtime. PyInstaller analyses imports statically, so it needs them spelled out.
SEARCH_PATHS = [str(SRC / "front"), str(SRC / "shared"), str(SRC / "back" / "client")]

# style.py resolves its icons relative to its own file, so they have to land beside
# the module inside the bundle, not in some flat resources directory.
DATA = [(str(SRC / "shared" / "nixync_ui" / "icons"), "nixync_ui/icons")]

# nixync_client is reached through the adapter rather than imported by name
# everywhere, and websockets is only pulled in by the agent transport.
HIDDEN = (
    collect_submodules("nixync_client")
    + collect_submodules("nixync_ui")
    + collect_submodules("nixync_front")
)

analysis = Analysis(
    [str(SRC / "front" / "nixync_front" / "__main__.py")],
    pathex=SEARCH_PATHS,
    binaries=[],
    datas=DATA,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    # Qt ships far more than this app uses; dropping the big unused modules keeps
    # the download reasonable.
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtQuick3D",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "tkinter", "unittest", "pytest",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="nixync",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # a desktop app: no terminal window behind it on Windows
    icon=str(SRC / "shared" / "nixync_ui" / "icons" / "app-icon.png"),
)

collected = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="nixync",
)

# macOS expects an .app bundle; building one on other platforms is meaningless.
import sys

if sys.platform == "darwin":
    app = BUNDLE(
        collected,
        name="Nixync.app",
        icon=str(SRC / "shared" / "nixync_ui" / "icons" / "app-icon.png"),
        bundle_identifier="org.nixync.host",
        info_plist={"NSHighResolutionCapable": True},
    )
