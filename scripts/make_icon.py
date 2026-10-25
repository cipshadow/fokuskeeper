"""Render assets/FokusKeeper.icns from fokuskeeper_icon.draw_app_icon.

Run after changing the drawing:  python3 scripts/make_icon.py
The .icns is committed so release builds don't depend on this step.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import AppKit  # noqa: E402

from fokuskeeper_icon import draw_app_icon  # noqa: E402

# iconutil's required iconset members: (points, scale).
SIZES = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
         (256, 1), (256, 2), (512, 1), (512, 2)]


def write_png(image, pixels, path):
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, pixels, pixels, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0
    )
    rep.setSize_((pixels, pixels))
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(
        AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    )
    image.drawInRect_fromRect_operation_fraction_(
        AppKit.NSMakeRect(0, 0, pixels, pixels), AppKit.NSZeroRect,
        AppKit.NSCompositingOperationCopy, 1.0,
    )
    AppKit.NSGraphicsContext.restoreGraphicsState()
    data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    data.writeToFile_atomically_(str(path), True)


def main():
    out = ROOT / "assets" / "FokusKeeper.icns"
    out.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "FokusKeeper.iconset"
        iconset.mkdir()
        for points, scale in SIZES:
            pixels = points * scale
            suffix = "@2x" if scale == 2 else ""
            write_png(draw_app_icon(pixels), pixels, iconset / f"icon_{points}x{points}{suffix}.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
