"""The one shield-with-K drawing, shared by every place FokusKeeper shows an
icon: the menu bar item, the Settings window's Dock icon, and the app icon
(scripts/make_icon.py renders assets/FokusKeeper.icns from it). Keeping a
single drawing is what keeps them identical.

AppKit only, no rumps, so the daemon's Settings panel can import it too.
"""

import AppKit

SHIELD_SYMBOLS = ("shield.fill", "shield.lefthalf.filled", "shield")


def _shield_symbol():
    for name in SHIELD_SYMBOLS:
        image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            name, "FokusKeeper"
        )
        if image is not None:
            return image
    return None


def _draw_shield_path(rect):
    """Hand-drawn shield for the (unexpected) case that no SF Symbol
    resolves, so the icon never degrades to text or emoji."""
    x, y, w, h = rect.origin.x, rect.origin.y, rect.size.width, rect.size.height
    path = AppKit.NSBezierPath.bezierPath()
    path.moveToPoint_((x + w * 0.5, y + h * 0.04))
    path.curveToPoint_controlPoint1_controlPoint2_(
        (x + w * 0.9, y + h * 0.78), (x + w * 0.82, y + h * 0.2), (x + w * 0.9, y + h * 0.45)
    )
    path.lineToPoint_((x + w * 0.5, y + h * 0.96))
    path.lineToPoint_((x + w * 0.1, y + h * 0.78))
    path.curveToPoint_controlPoint1_controlPoint2_(
        (x + w * 0.5, y + h * 0.04), (x + w * 0.1, y + h * 0.45), (x + w * 0.18, y + h * 0.2)
    )
    path.closePath()
    AppKit.NSColor.blackColor().setFill()
    path.fill()


def draw_shield_k(size, fraction=1.0):
    """A size x size NSImage: a black shield with a 'K' cut out of it.

    No SF Symbol combines a shield with an arbitrary letter, so this
    composites one: draw the shield solid, then punch the K through it with a
    destination-out blend -- the same cutout technique Apple's own compound
    shield symbols use. `fraction` dims the shield (the menu bar's stopped
    state); the cutout stays crisp either way. Never returns None.
    """
    image = AppKit.NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()

    rect = AppKit.NSMakeRect(0, 0, size, size)
    symbol = _shield_symbol()
    if symbol is not None:
        symbol.drawInRect_fromRect_operation_fraction_(
            rect, AppKit.NSZeroRect, AppKit.NSCompositingOperationSourceOver, fraction,
        )
    else:
        AppKit.NSGraphicsContext.currentContext().saveGraphicsState()
        _draw_shield_path(rect)
        AppKit.NSGraphicsContext.currentContext().restoreGraphicsState()

    font = AppKit.NSFont.boldSystemFontOfSize_(size * 0.62)
    attrs = {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.blackColor(),
    }
    text = AppKit.NSAttributedString.alloc().initWithString_attributes_("K", attrs)
    text_size = text.size()
    x = (size - text_size.width) / 2.0 - size * 0.03  # slight nudge left: the K's open right side reads as off-center otherwise
    y = (size - text_size.height) / 2.0 + size * 0.02  # nudge up: the shield's pointed tip reads as dead weight below center

    ctx = AppKit.NSGraphicsContext.currentContext()
    ctx.saveGraphicsState()
    ctx.setCompositingOperation_(AppKit.NSCompositingOperationDestinationOut)
    text.drawAtPoint_((x, y))
    ctx.restoreGraphicsState()

    image.unlockFocus()
    return image


def draw_app_icon(size):
    """The app icon: the same shield-K centred on a white rounded square, so
    it reads in Finder, the Dock and the app switcher on light or dark."""
    image = AppKit.NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()

    inset = size * 0.1  # Apple's icon grid leaves a margin around the tile
    tile = AppKit.NSMakeRect(inset, inset, size - 2 * inset, size - 2 * inset)
    radius = tile.size.width * 0.225
    AppKit.NSColor.whiteColor().setFill()
    AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(tile, radius, radius).fill()

    glyph_size = tile.size.width * 0.85
    glyph = draw_shield_k(glyph_size)
    origin = (size - glyph_size) / 2.0
    glyph.drawInRect_fromRect_operation_fraction_(
        AppKit.NSMakeRect(origin, origin, glyph_size, glyph_size),
        AppKit.NSZeroRect, AppKit.NSCompositingOperationSourceOver, 1.0,
    )

    image.unlockFocus()
    return image
