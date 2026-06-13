# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()
FRONTEND_DIST = ROOT / "frontend" / "dist"
APP_HIDDEN_IMPORTS = collect_submodules("app")

if not (FRONTEND_DIST / "index.html").exists():
    raise SystemExit(
        "Missing frontend/dist/index.html. Run scripts/build-windows-exe.ps1 first."
    )

a = Analysis(
    [str(ROOT / "backend" / "desktop_launcher.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=[
        (str(FRONTEND_DIST), "frontend_dist"),
        (str(ROOT / "backend" / ".env.example"), "."),
    ],
    hiddenimports=APP_HIDDEN_IMPORTS
    + [
        "aiosqlite",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NarrativeForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
