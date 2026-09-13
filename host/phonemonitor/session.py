import json
import os
import socket
import struct
import subprocess
import threading

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstVideo

from . import adb
from .controls import VolumeSync

HERE = os.path.dirname(os.path.abspath(__file__))
KWIN_CAST = os.path.normpath(os.path.join(HERE, "..", "kwin-cast", "kwin-cast"))
GRANT_FILE = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                          "applications", "kwin-cast.desktop")
OUTPUT_NAME = "phone"
SINK_NAME = "phone"

ENCODERS = {
    "va": ("Intel VA-API (zero-copy)", "vah264lpenc",
           "vapostproc ! video/x-raw(memory:VAMemory),format=NV12 "
           "! vah264lpenc name=enc rate-control=cbr bitrate={bitrate} target-usage=7 b-frames=0 ref-frames=1 key-int-max=600"),
    "nv": ("NVIDIA NVENC", "nvh264enc",
           "videoconvert ! video/x-raw,format=NV12 "
           "! nvh264enc name=enc preset=p1 tune=low-latency rc-mode=cbr bitrate={bitrate} bframes=0 zerolatency=true gop-size=600"),
}

TOUCH_ACTION = {0: "d", 1: "m", 2: "u"}
DEBUG = bool(os.environ.get("PM_DEBUG"))


def encoder_available(key):
    Gst.init(None)
    return Gst.ElementFactory.find(ENCODERS[key][1]) is not None


def ensure_kwin_grant():
    """KWin only exposes screencast/fake-input to binaries listed in a .desktop file."""
    content = ("[Desktop Entry]\nType=Application\nName=kwin-cast (phone-monitor)\n"
               f"Exec={KWIN_CAST}\nNoDisplay=true\n"
               "X-KDE-Wayland-Interfaces=zkde_screencast_unstable_v1,org_kde_kwin_fake_input\n")
    try:
        with open(GRANT_FILE) as f:
            if f.read() == content:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(GRANT_FILE), exist_ok=True)
    with open(GRANT_FILE, "w") as f:
        f.write(content)
    subprocess.run(["kbuildsycoca6"], capture_output=True)


class Session:
    def __init__(self, cfg, log, on_state):
        self.cfg = cfg
        self.log = log
        self.on_state = on_state        # called with "stopped" | "starting" | "running" | "connected"
        self.running = False
        self.lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.cast = None
        self.pipeline = None
        self.audio_pipeline = None
        self.audio_module = None
        self.srv = None
        self.audio_srv = None
        self.client = None
        self.audio_client = None
        self.phone_proc = None
        self.phone_pid = None
        self.volume_sync = None
        self.saved_brightness = None
        self.size = None

    # ------------------------------------------------------------------ start
    def start(self):
        if self.running:
            return
        self.on_state("starting")
        try:
            self._start()
        except Exception:
            self.stop()
            raise
        self.running = True
        self.on_state("running")

    def _start(self):
        cfg = self.cfg
        Gst.init(None)
        if not encoder_available(cfg.encoder):
            raise RuntimeError(f"encoder {ENCODERS[cfg.encoder][1]} not available (install gst-plugin-va / gst-plugin-nvcodec)")
        ensure_kwin_grant()

        serial = adb.device()
        self.log(f"phone: {adb.model()} ({serial})")
        if cfg.mode == "root" and not adb.has_root():
            raise RuntimeError("phone is not rooted (or su denied); switch to APK mode")
        screen = adb.screen_size()
        if cfg.size == "auto":
            self.size = (max(screen), min(screen))
        else:
            self.size = tuple(int(v) for v in cfg.size.lower().split("x"))
        w, h = self.size

        # virtual output
        self.cast = subprocess.Popen([KWIN_CAST, OUTPUT_NAME, str(w), str(h), str(cfg.scale)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1)
        line = self.cast.stdout.readline().strip()
        if not line.startswith("node "):
            raise RuntimeError("kwin-cast failed: " + (self.cast.stderr.read().strip() or line or "no output"))
        node = int(line.split()[1])
        pw_serial = json.loads(subprocess.check_output(["pw-dump", str(node)]))[0]["info"]["props"]["object.serial"]
        subprocess.run(["kscreen-doctor", f"output.Virtual-{OUTPUT_NAME}.scale.{cfg.scale:g}"], capture_output=True)
        self.log(f"virtual output Virtual-{OUTPUT_NAME}: {w}x{h} @ {cfg.scale:g}x")

        # video pipeline
        desc = (f"pipewiresrc target-object={pw_serial} do-timestamp=true "
                "stream-properties=\"props,media.class=Stream/Input/Video,node.dont-fallback=true\" "
                "! video/x-raw(memory:DMABuf) ! queue max-size-buffers=1 leaky=downstream ! "
                + ENCODERS[cfg.encoder][2].format(bitrate=cfg.bitrate) +
                " ! h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au "
                "! appsink name=sink sync=false drop=true max-buffers=1 emit-signals=true")
        self.pipeline = Gst.parse_launch(desc)
        self.pipeline.get_by_name("sink").connect("new-sample", self._on_video_sample)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        self.srv = self._listen(cfg.port)
        threading.Thread(target=self._accept_video, daemon=True).start()

        # audio
        audio_port = 0
        if cfg.audio:
            self._remove_stale_sinks()
            self.audio_module = subprocess.check_output(
                ["pactl", "load-module", "module-null-sink", f"sink_name={SINK_NAME}",
                 "sink_properties=device.description=Phone", "rate=48000", "channels=2"], text=True).strip()
            nodes = json.loads(subprocess.check_output(["pw-dump"]))
            sink_serial = next(n["info"]["props"]["object.serial"] for n in nodes
                               if n.get("info", {}).get("props", {}).get("node.name") == SINK_NAME)
            self.audio_pipeline = Gst.parse_launch(
                f"pipewiresrc target-object={sink_serial} stream-properties=\"props,media.class=Stream/Input/Audio,"
                "stream.capture.sink=true,node.dont-fallback=true,node.latency=240/48000\" "
                "! audioconvert ! audioresample ! audio/x-raw,format=S16LE,rate=48000,channels=2,layout=interleaved "
                "! appsink name=asink sync=false drop=true max-buffers=4 emit-signals=true")
            self.audio_pipeline.get_by_name("asink").connect("new-sample", self._on_audio_sample)
            audio_port = cfg.port + 1
            self.audio_srv = self._listen(audio_port)
            threading.Thread(target=self._accept_audio, daemon=True).start()
            self.audio_pipeline.set_state(Gst.State.PLAYING)
            self.log("audio sink 'Phone' created")

        self.pipeline.set_state(Gst.State.PLAYING)

        # phone side
        adb.keep_awake(True)
        adb.reverse(cfg.port)
        if audio_port:
            adb.reverse(audio_port)
        touch = None
        if cfg.touch and cfg.mode == "root":
            touch = adb.find_touch_device()
            if touch:
                self.log(f"touch device: {touch[0]}")
            else:
                self.log("no touch device found")

        if cfg.mode == "root":
            adb.push_dex()
            self.phone_proc = adb.start_root_client(cfg.port, self.size, screen, cfg.rotation, touch, audio_port)
            threading.Thread(target=self._read_phone_output, daemon=True).start()
        else:
            if not adb.apk_installed():
                self.log("installing APK")
                adb.install_apk()
            adb.start_apk_client(cfg.port, self.size, cfg.rotation, cfg.touch, audio_port)

        self.saved_brightness = adb.get_brightness()
        adb.set_brightness(cfg.brightness)
        if cfg.audio and cfg.volume_sync:
            self.volume_sync = VolumeSync(SINK_NAME, self.log)
            self.volume_sync.start()

    # ------------------------------------------------------------------- stop
    def stop(self):
        was_running = self.running
        self.running = False
        if self.volume_sync:
            self.volume_sync.stop()
        for s in (self.client, self.audio_client, self.srv, self.audio_srv):
            if s:
                try:
                    s.close()
                except OSError:
                    pass
        for p in (self.pipeline, self.audio_pipeline):
            if p:
                p.set_state(Gst.State.NULL)
        if self.audio_module:
            subprocess.run(["pactl", "unload-module", self.audio_module], capture_output=True)
        if self.cast:
            self.cast.terminate()
        try:
            if self.cfg.mode == "root":
                if self.phone_pid:
                    adb.kill_pid(self.phone_pid)
            else:
                adb.stop_apk_client()
            if self.phone_proc:
                self.phone_proc.terminate()
            if self.saved_brightness:
                adb.restore_brightness(*self.saved_brightness)
            adb.keep_awake(False)
            adb.unreverse(self.cfg.port)
            adb.unreverse(self.cfg.port + 1)
        except adb.AdbError as e:
            self.log(f"adb cleanup: {e}")
        self._reset()
        if was_running:
            self.log("stopped")
        self.on_state("stopped")

    # ---------------------------------------------------------------- runtime
    def set_brightness(self, percent):
        if self.running:
            adb.set_brightness(percent)

    def reinstall_apk(self):
        self.log("installing APK")
        adb.install_apk()

    # --------------------------------------------------------------- internals
    @staticmethod
    def _listen(port):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)
        return s

    @staticmethod
    def _remove_stale_sinks():
        for line in subprocess.run(["pactl", "list", "modules", "short"], capture_output=True, text=True).stdout.splitlines():
            if "module-null-sink" in line and f"sink_name={SINK_NAME}" in line:
                subprocess.run(["pactl", "unload-module", line.split()[0]], capture_output=True)

    def _accept_video(self):
        srv = self.srv
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self.lock:
                self.client = c
            self.log("phone connected")
            self.on_state("connected")
            self.pipeline.get_by_name("enc").send_event(
                GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, 0))
            threading.Thread(target=self._touch_loop, args=(c,), daemon=True).start()

    def _accept_audio(self):
        srv = self.audio_srv
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.audio_client = c

    def _touch_loop(self, c):
        buf = b""
        while True:
            try:
                chunk = c.recv(4096)
            except OSError:
                chunk = b""
            if not chunk:
                if self.running and self.client is c:
                    self.log("phone disconnected")
                    self.on_state("running")
                return
            buf += chunk
            w, h = self.size
            while len(buf) >= 12:
                action, slot, _, x, y = struct.unpack(">BBHii", buf[:12])
                buf = buf[12:]
                if action == 3:
                    cmd = "f\n"
                else:
                    cmd = "%s %d %.5f %.5f\n" % (TOUCH_ACTION[action], slot, x / w, y / h)
                if DEBUG:
                    self.log("touch " + cmd.strip())
                try:
                    self.cast.stdin.write(cmd)
                except (OSError, AttributeError):
                    return
            try:
                self.cast.stdin.flush()
            except (OSError, AttributeError):
                return

    def _on_video_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        ok, m = buf.map(Gst.MapFlags.READ)
        data = bytes(m.data)
        buf.unmap(m)
        with self.lock:
            c = self.client
        if c:
            try:
                c.sendall(struct.pack(">I", len(data)) + data)
            except OSError:
                pass
        return Gst.FlowReturn.OK

    def _on_audio_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        ok, m = buf.map(Gst.MapFlags.READ)
        data = bytes(m.data)
        buf.unmap(m)
        c = self.audio_client
        if c:
            try:
                c.sendall(data)
            except OSError:
                pass
        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            self.log(f"gstreamer error: {err.message}")
            GLib.idle_add(self.stop)
        elif msg.type == Gst.MessageType.EOS:
            self.log("gstreamer: end of stream")
            GLib.idle_add(self.stop)

    def _read_phone_output(self):
        proc = self.phone_proc
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("pid "):
                self.phone_pid = int(line.split()[1])
            elif line:
                self.log("phone: " + line)
        if self.running and proc is self.phone_proc:
            self.log(f"phone client exited ({proc.wait()})")
