# Build with: pyinstaller CopyCat.spec
import sys

sys.path.insert(0, SPECPATH)
from copycat import VERSION  # noqa: E402

a = Analysis(
    ["app.py"],
    pathex=[SPECPATH],
    datas=[("ui", "ui")],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CopyCat", console=False, icon="assets/CopyCat.icns")
    coll = COLLECT(exe, a.binaries, a.datas, name="CopyCat")
    app = BUNDLE(
        coll,
        name="CopyCat.app",
        icon="assets/CopyCat.icns",
        bundle_identifier="io.github.vhrcam.copycat",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "CopyCat",
            "CFBundleShortVersionString": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSLocalNetworkUsageDescription": "CopyCat looks for your other computer on this Wi-Fi so it can sync your clipboard.",
            "NSBonjourServices": ["_copycat._tcp"],
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="CopyCat",
        console=False,
        icon="assets/CopyCat.ico",
        upx=False,
    )
