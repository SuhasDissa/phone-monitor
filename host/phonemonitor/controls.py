import re
import subprocess
import threading

from . import adb


class VolumeSync(threading.Thread):
    """Mirrors the PipeWire sink's volume/mute to the phone's media volume and back.

    Host -> phone: pactl subscribe events on the sink.
    Phone -> host: the phone's volume is polled, so its hardware volume keys move the sink too.
    """

    def __init__(self, sink, log):
        super().__init__(daemon=True)
        self.sink = sink
        self.log = log
        self.proc = None
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.phone_index, self.phone_max = adb.get_volume()
        self.sink_id = None

    def run(self):
        self.push_to_phone()
        self.proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True)
        poller = threading.Thread(target=self.poll_phone, daemon=True)
        poller.start()
        for line in self.proc.stdout:
            if self.stopped.is_set():
                break
            m = re.match(r"Event 'change' on sink #(\d+)", line)
            if m and (self.sink_id is None or m.group(1) == self.sink_id):
                self.push_to_phone()

    def stop(self):
        self.stopped.set()
        if self.proc:
            self.proc.terminate()

    def sink_state(self):
        vol = subprocess.run(["pactl", "get-sink-volume", self.sink], capture_output=True, text=True).stdout
        mute = subprocess.run(["pactl", "get-sink-mute", self.sink], capture_output=True, text=True).stdout
        m = re.search(r"(\d+)%", vol)
        if not m:
            return None
        return int(m.group(1)), "yes" in mute

    def resolve_sink_id(self):
        for line in subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, text=True).stdout.splitlines():
            parts = line.split()
            if len(parts) > 1 and parts[1] == self.sink:
                self.sink_id = parts[0]

    def push_to_phone(self):
        if self.sink_id is None:
            self.resolve_sink_id()
        state = self.sink_state()
        if not state:
            return
        percent, muted = state
        index = 0 if muted else max(0, min(self.phone_max, round(percent * self.phone_max / 100)))
        with self.lock:
            if index == self.phone_index:
                return
            self.phone_index = index
        adb.set_volume(index)

    def poll_phone(self):
        while not self.stopped.wait(2):
            try:
                index, _ = adb.get_volume()
            except adb.AdbError:
                continue
            with self.lock:
                if index == self.phone_index:
                    continue
                self.phone_index = index
            subprocess.run(["pactl", "set-sink-volume", self.sink, f"{round(index * 100 / self.phone_max)}%"])
