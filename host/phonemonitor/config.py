import json
import os
from dataclasses import asdict, dataclass, fields

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "phone-monitor")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class Config:
    mode: str = "root"          # root | apk
    encoder: str = "va"         # va | nv
    size: str = "auto"          # WxH pixels of the virtual output, or auto (phone panel, landscape)
    scale: float = 2.0
    bitrate: int = 20000        # kbit/s
    rotation: str = "ccw"       # ccw: phone top on the left, cw: phone top on the right
    touch: bool = True
    audio: bool = True
    volume_sync: bool = True
    port: int = 27183
    brightness: int = 60        # 0-100, applied to the phone while streaming
    start_minimized: bool = False
    autostart: bool = False

    @classmethod
    def load(cls):
        cfg = cls()
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cfg
        names = {f.name for f in fields(cls)}
        for k, v in data.items():
            if k in names:
                setattr(cfg, k, v)
        return cfg

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(asdict(self), f, indent=2)
