import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .session import ENCODERS, encoder_available

ROTATIONS = [("ccw", "Phone top on the left (USB on the right)"),
             ("cw", "Phone top on the right (USB on the left)")]
MODES = [("root", "Root (app_process, no APK)"), ("apk", "APK (no root)")]


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Phone Monitor", default_width=520, default_height=560)
        self.app = app
        self.cfg = app.cfg
        self._loading = True

        header = Gtk.HeaderBar(title="Phone Monitor", show_close_button=True)
        self.set_titlebar(header)
        self.toggle_btn = Gtk.Button(label="Start")
        self.toggle_btn.get_style_context().add_class("suggested-action")
        self.toggle_btn.connect("clicked", lambda *_: app.toggle())
        header.pack_start(self.toggle_btn)
        self.status = Gtk.Label(label="stopped")
        header.pack_end(self.status)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=12)
        self.add(box)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        box.pack_start(grid, False, False, 0)
        self.option_widgets = []
        row = 0

        def add(label, widget, hexpand=True):
            nonlocal row
            grid.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
            widget.set_hexpand(hexpand)
            grid.attach(widget, 1, row, 1, 1)
            self.option_widgets.append(widget)
            row += 1
            return widget

        self.mode = Gtk.ComboBoxText()
        for key, label in MODES:
            self.mode.append(key, label)
        self.mode.set_active_id(self.cfg.mode)
        self.mode.connect("changed", lambda w: self._set("mode", w.get_active_id()))
        mode_box = Gtk.Box(spacing=6)
        mode_box.pack_start(self.mode, True, True, 0)
        reinstall = Gtk.Button(label="Reinstall APK")
        reinstall.connect("clicked", lambda *_: app.reinstall_apk())
        mode_box.pack_start(reinstall, False, False, 0)
        add("Client", mode_box)

        self.encoder = Gtk.ComboBoxText()
        for key, (label, element, _) in ENCODERS.items():
            self.encoder.append(key, label if encoder_available(key) else f"{label} (missing {element})")
        self.encoder.set_active_id(self.cfg.encoder)
        self.encoder.connect("changed", lambda w: self._set("encoder", w.get_active_id()))
        add("Encoder", self.encoder)

        self.size = Gtk.Entry(text=self.cfg.size, placeholder_text="auto or WIDTHxHEIGHT")
        self.size.connect("changed", lambda w: self._set("size", w.get_text().strip() or "auto"))
        add("Resolution", self.size)

        self.scale = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.25)
        self.scale.set_digits(2)
        self.scale.set_value(self.cfg.scale)
        self.scale.connect("value-changed", lambda w: self._set("scale", w.get_value()))
        add("Display scale", self.scale)

        self.bitrate = Gtk.SpinButton.new_with_range(2000, 100000, 1000)
        self.bitrate.set_value(self.cfg.bitrate)
        self.bitrate.connect("value-changed", lambda w: self._set("bitrate", int(w.get_value())))
        add("Bitrate (kbit/s)", self.bitrate)

        self.rotation = Gtk.ComboBoxText()
        for key, label in ROTATIONS:
            self.rotation.append(key, label)
        self.rotation.set_active_id(self.cfg.rotation)
        self.rotation.connect("changed", lambda w: self._set("rotation", w.get_active_id()))
        add("Orientation", self.rotation)

        self.port = Gtk.SpinButton.new_with_range(1024, 65534, 1)
        self.port.set_value(self.cfg.port)
        self.port.connect("value-changed", lambda w: self._set("port", int(w.get_value())))
        add("Port (video; audio uses port+1)", self.port)

        self.touch = self._switch("touch")
        add("Touch input", self.touch, hexpand=False)
        self.audio = self._switch("audio")
        add("Audio output (\"Phone\" sink)", self.audio, hexpand=False)
        self.volume_sync = self._switch("volume_sync")
        add("Sync sink volume with phone volume", self.volume_sync, hexpand=False)

        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.brightness.set_value(self.cfg.brightness)
        self.brightness.set_value_pos(Gtk.PositionType.RIGHT)
        self.brightness.connect("value-changed", self._on_brightness)
        grid.attach(Gtk.Label(label="Phone brightness", xalign=1), 0, row, 1, 1)
        grid.attach(self.brightness, 1, row, 1, 1)
        row += 1

        self.start_minimized = self._check("start_minimized", "Start minimized to tray")
        grid.attach(self.start_minimized, 1, row, 1, 1)
        row += 1
        self.autostart = self._check("autostart", "Start streaming when launched")
        grid.attach(self.autostart, 1, row, 1, 1)

        self.log_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
        scroll = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN)
        scroll.add(self.log_view)
        box.pack_start(scroll, True, True, 0)

        self.connect("delete-event", self._on_close)
        self._loading = False
        self.show_all()

    def _switch(self, key):
        s = Gtk.Switch(active=getattr(self.cfg, key), halign=Gtk.Align.START)
        s.connect("notify::active", lambda w, _: self._set(key, w.get_active()))
        return s

    def _check(self, key, label):
        c = Gtk.CheckButton(label=label, active=getattr(self.cfg, key))
        c.connect("toggled", lambda w: self._set(key, w.get_active()))
        return c

    def _set(self, key, value):
        if self._loading:
            return
        setattr(self.cfg, key, value)
        self.cfg.save()

    def _on_brightness(self, scale):
        value = int(scale.get_value())
        self._set("brightness", value)
        self.app.session.set_brightness(value)

    def _on_close(self, *_):
        if self.app.tray:
            self.hide()
            return True
        self.app.quit_app()
        return True

    def set_state(self, state):
        self.status.set_text(state)
        running = state != "stopped"
        self.toggle_btn.set_label("Stop" if running else "Start")
        ctx = self.toggle_btn.get_style_context()
        ctx.remove_class("suggested-action" if running else "destructive-action")
        ctx.add_class("destructive-action" if running else "suggested-action")
        for w in self.option_widgets:
            w.set_sensitive(not running)

    def append_log(self, line):
        buf = self.log_view.get_buffer()
        buf.insert(buf.get_end_iter(), line + "\n")
        self.log_view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
