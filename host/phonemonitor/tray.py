import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    AppIndicator = None


class Tray:
    """StatusNotifier tray icon; `available` is False when libayatana-appindicator is missing."""

    available = AppIndicator is not None

    def __init__(self, app):
        self.app = app
        self.menu = Gtk.Menu()

        self.toggle_item = Gtk.MenuItem(label="Start")
        self.toggle_item.connect("activate", lambda *_: app.toggle())
        self.menu.append(self.toggle_item)

        show = Gtk.MenuItem(label="Show window")
        show.connect("activate", lambda *_: app.show_window())
        self.menu.append(show)

        brightness = Gtk.MenuItem(label="Phone brightness")
        sub = Gtk.Menu()
        for pct in (10, 25, 50, 75, 100):
            item = Gtk.MenuItem(label=f"{pct}%")
            item.connect("activate", lambda _, p=pct: app.set_brightness(p))
            sub.append(item)
        brightness.set_submenu(sub)
        self.menu.append(brightness)

        self.menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: app.quit_app())
        self.menu.append(quit_item)
        self.menu.show_all()

        self.indicator = AppIndicator.Indicator.new(
            "phone-monitor", "smartphone-symbolic", AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Phone Monitor")
        self.indicator.set_menu(self.menu)
        self.indicator.set_secondary_activate_target(self.toggle_item)

    def set_state(self, state):
        running = state != "stopped"
        self.toggle_item.set_label("Stop" if running else "Start")
        self.indicator.set_icon_full("smartphone" if running else "smartphone-symbolic", state)
        self.indicator.set_title(f"Phone Monitor: {state}")
