# PyInstaller spec file — builds executables for Mac (.app) and Windows (.exe).
# Usage:
#   Mac:     pyinstaller dive_overlay.spec
#   Windows: pyinstaller dive_overlay.spec

import sys
from PyInstaller.building.build_main import Analysis, PYZ, EXE, BUNDLE, COLLECT

block_cipher = None

a = Analysis(
    ["gui.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["fitparse", "fitparse.processors", "fitparse.utils", "uddf_parser", "csv_parser", "xml.etree.ElementTree"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "darwin":
    # Mac: onedir mode + .app bundle (Apple security requirement)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="DiveOverlay",
        debug=False,
        strip=False,
        upx=True,
        console=False,
        windowed=True,
        icon="DiveOverlay.icns" if sys.platform == "darwin" else "DiveOverlay.ico",
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        name="DiveOverlay",
    )
    app = BUNDLE(
        coll,
        name="DiveOverlay.app",
        icon="DiveOverlay.icns" if sys.platform == "darwin" else "DiveOverlay.ico",
        bundle_identifier="kr.ocean.diveoverlay",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
        },
    )
else:
    # Windows: single .exe file
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="DiveOverlay",
        debug=False,
        strip=False,
        upx=True,
        runtime_tmpdir=None,
        console=False,
        windowed=True,
        icon="DiveOverlay.icns" if sys.platform == "darwin" else "DiveOverlay.ico",
    )
