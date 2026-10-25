"""
Menu bar presence on macOS, so the app can keep running with no window.

Everything here is a no-op on other platforms, and every call is written to
fail soft: a menu bar extra is a convenience, and losing it should never stop
the app from working.

AppKit comes from pyobjc, which bleak already depends on for CoreBluetooth,
so this adds no new dependency. Tk's own event loop on macOS is Cocoa-based
and pumps NSApplication, which is why an NSStatusItem created here receives
its clicks without a second run loop.
"""
from __future__ import annotations

import sys

_AVAILABLE = False
if sys.platform == "darwin":
    try:
        import objc
        from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory,
                            NSApplicationActivationPolicyRegular, NSImage, NSMenu,
                            NSMenuItem, NSStatusBar, NSVariableStatusItemLength)
        from Foundation import NSObject
        _AVAILABLE = True
    except Exception:          # pragma: no cover - depends on the platform
        _AVAILABLE = False


def available() -> bool:
    return _AVAILABLE


if _AVAILABLE:

    class _Target(NSObject):
        """Receives the menu clicks and forwards them to Python callables."""

        def initWithActions_(self, actions):
            self = objc.super(_Target, self).init()
            if self is None:
                return None
            self._actions = actions          # tag -> callable
            return self

        def fire_(self, sender):
            action = self._actions.get(sender.tag())
            if action is not None:
                try:
                    action()
                except Exception:
                    import traceback
                    traceback.print_exc()


class MenuBar:
    """A status bar item with a menu.

    `items` is a list of (label, callback); None makes a separator.
    """

    def __init__(self, title="Nx", items=(), icon_path=None, tooltip=None):
        self.ok = False
        if not _AVAILABLE:
            return
        try:
            self._app = NSApplication.sharedApplication()
            bar = NSStatusBar.systemStatusBar()
            self._item = bar.statusItemWithLength_(NSVariableStatusItemLength)

            button = self._item.button()
            image = self._load_icon(icon_path)
            if button is not None and image is not None:
                button.setImage_(image)
            elif button is not None:
                button.setTitle_(title)
            else:                               # very old AppKit
                self._item.setTitle_(title)
            if tooltip and button is not None:
                button.setToolTip_(tooltip)

            actions = {}
            menu = NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)
            self._target = _Target.alloc().initWithActions_(actions)

            for tag, entry in enumerate(items):
                if entry is None:
                    menu.addItem_(NSMenuItem.separatorItem())
                    continue
                label, callback = entry
                menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    label, objc.selector(self._target.fire_, signature=b"v@:@"), "")
                menu_item.setTarget_(self._target)
                menu_item.setTag_(tag)
                menu_item.setEnabled_(True)
                actions[tag] = callback
                menu.addItem_(menu_item)

            self._item.setMenu_(menu)
            self._menu = menu
            self.ok = True
        except Exception:
            import traceback
            traceback.print_exc()
            self.ok = False

    @staticmethod
    def _load_icon(path):
        """A small template image, so it follows light and dark menu bars."""
        if not path:
            return None
        try:
            image = NSImage.alloc().initWithContentsOfFile_(path)
            if image is None:
                return None
            image.setSize_((18, 18))
            image.setTemplate_(True)
            return image
        except Exception:
            return None

    def set_item_title(self, index, title):
        if not self.ok:
            return
        try:
            self._menu.itemAtIndex_(index).setTitle_(title)
        except Exception:
            pass

    def set_dock_visible(self, visible: bool):
        """Show or hide the Dock icon.

        Accessory policy removes the Dock tile and the menu bar name, which
        is what makes a window-less background app feel right.
        """
        if not _AVAILABLE:
            return
        try:
            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(
                NSApplicationActivationPolicyRegular if visible
                else NSApplicationActivationPolicyAccessory)
            if visible:
                app.activateIgnoringOtherApps_(True)
        except Exception:
            pass

    def remove(self):
        if not self.ok:
            return
        try:
            NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
        except Exception:
            pass
        self.ok = False
