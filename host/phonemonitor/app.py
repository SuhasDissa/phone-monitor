import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from . import APP_ID
from .config import Config
from .session import Session


class App(Gtk.Application):
    """Single-instance app. A second invocation forwards its options to the running one,
    so `phone-monitor --brightness 40` or `--toggle` work from shortcuts."""

    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = Config.load()
        self.session = Session(self.cfg, self.log, self._on_state)
        self.window = None
        self.tray = None
        self.headless = False
        self.log_lines = []
        for name, kind, desc in [
            ("headless", GLib.OptionArg.NONE, "no window or tray; stream until Ctrl-C"),
            ("start", GLib.OptionArg.NONE, "start streaming"),
            ("stop", GLib.OptionArg.NONE, "stop streaming"),
            ("toggle", GLib.OptionArg.NONE, "start or stop streaming"),
            ("brightness", GLib.OptionArg.INT, "set phone brightness (0-100)"),
            ("quit", GLib.OptionArg.NONE, "quit the running instance"),
        ]:
            self.add_main_option(name, 0, GLib.OptionFlags.NONE, kind, desc, None)

    # ------------------------------------------------------------ lifecycle
    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.quit_app)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit_app)

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        first = not self.get_windows() and not self.headless and not self.session.running
        if first:
            self.headless = opts.get("headless", False)
            if self.headless:
                self.hold()
            else:
                from .gui import MainWindow
                from .tray import Tray
                if Tray.available:
                    self.tray = Tray(self)
                else:
                    self.log("tray unavailable (install libayatana-appindicator)")
                self.window = MainWindow(self)
                for line in self.log_lines:
                    self.window.append_log(line)
                if self.cfg.start_minimized and self.tray:
                    self.window.hide()
            if self.headless or self.cfg.autostart:
                GLib.idle_add(self.start)
        if opts.get("start"):
            self.start()
        if opts.get("stop"):
            self.session.stop()
        if opts.get("toggle"):
            self.toggle()
        if "brightness" in opts:
            self.set_brightness(opts["brightness"])
        if opts.get("quit"):
            self.quit_app()
        if not first and self.window and not any(opts.get(k) for k in ("start", "stop", "toggle", "quit")) and "brightness" not in opts:
            self.show_window()
        return 0

    def do_activate(self):
        self.show_window()

    # -------------------------------------------------------------- actions
    def start(self):
        try:
            self.session.start()
        except Exception as e:
            self.log(f"error: {e}")
            if self.headless:
                self.quit_app()

    def toggle(self):
        if self.session.running:
            self.session.stop()
        else:
            self.start()

    def set_brightness(self, percent):
        percent = max(0, min(100, int(percent)))
        self.cfg.brightness = percent
        self.cfg.save()
        self.session.set_brightness(percent)
        if self.window:
            self.window.brightness.set_value(percent)

    def reinstall_apk(self):
        try:
            self.session.reinstall_apk()
        except Exception as e:
            self.log(f"error: {e}")

    def show_window(self):
        if self.window:
            self.window.present()

    def quit_app(self, *_):
        if self.session.running:
            self.session.stop()
        self.quit()
        return False

    # ------------------------------------------------------------ callbacks
    def log(self, line):
        line = time.strftime("%H:%M:%S ") + line
        self.log_lines = self.log_lines[-500:] + [line]
        print(line, file=sys.stderr, flush=True)
        if self.window:
            GLib.idle_add(self.window.append_log, line)

    def _on_state(self, state):
        def apply():
            if self.window:
                self.window.set_state(state)
            if self.tray:
                self.tray.set_state(state)
        GLib.idle_add(apply)


def main(argv=None):
    return App().run(sys.argv if argv is None else argv)
