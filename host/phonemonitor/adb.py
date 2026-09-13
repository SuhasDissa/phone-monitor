import os
import re
import subprocess

from . import APK_PACKAGE

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID_OUT = os.path.normpath(os.path.join(HERE, "..", "..", "android", "out"))
DEX_LOCAL = os.path.join(ANDROID_OUT, "phone-monitor.dex")
APK_LOCAL = os.path.join(ANDROID_OUT, "phone-monitor.apk")
DEX_REMOTE = "/data/local/tmp/phone-monitor.dex"


class AdbError(Exception):
    pass


def run(*args, check=True):
    p = subprocess.run(["adb", *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AdbError((p.stderr or p.stdout).strip() or f"adb {' '.join(args)} failed")
    return p.stdout


def shell(cmd, root=False, check=True):
    if root:
        cmd = "su -c " + _quote(cmd)
    return run("shell", cmd, check=check)


def _quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def device():
    """Returns the serial of the single connected device, or raises."""
    lines = [l.split() for l in run("devices").splitlines()[1:] if l.strip()]
    devs = [l[0] for l in lines if len(l) > 1 and l[1] == "device"]
    if not devs:
        raise AdbError("no device connected (or not authorized)")
    if len(devs) > 1:
        raise AdbError("more than one device connected")
    return devs[0]


def has_root():
    return "uid=0" in shell("id", root=True, check=False)


def screen_size():
    m = re.search(r"Physical size: (\d+)x(\d+)", shell("wm size"))
    return int(m.group(1)), int(m.group(2))


def model():
    return shell("getprop ro.product.model").strip()


def find_touch_device():
    """(path, xmax, ymax) of the first evdev device with ABS_MT_POSITION_X/Y, or None."""
    cur = xmax = None
    for line in shell("getevent -p", root=True).splitlines():
        if line.startswith("add device"):
            cur, xmax = line.split()[-1], None
        elif "0035  :" in line:
            xmax = int(line.split("max")[1].split(",")[0])
        elif "0036  :" in line and xmax:
            return cur, xmax, int(line.split("max")[1].split(",")[0])
    return None


def reverse(port):
    run("reverse", f"tcp:{port}", f"tcp:{port}")


def unreverse(port):
    run("reverse", "--remove", f"tcp:{port}", check=False)


def keep_awake(on):
    shell(f"svc power stayon {'usb' if on else 'false'}", check=False)
    if on:
        shell("input keyevent KEYCODE_WAKEUP", check=False)


# --- brightness / volume (both work from the shell user, no root needed) ---

def get_brightness():
    """(mode, level): mode 1 = automatic, level 0-255."""
    mode = shell("settings get system screen_brightness_mode").strip()
    level = shell("settings get system screen_brightness").strip()
    return int(mode) if mode.isdigit() else 0, int(level) if level.isdigit() else 128


def set_brightness(percent):
    level = max(0, min(255, round(percent * 255 / 100)))
    shell(f"settings put system screen_brightness_mode 0; settings put system screen_brightness {level}", check=False)


def restore_brightness(mode, level):
    shell(f"settings put system screen_brightness {level}; settings put system screen_brightness_mode {mode}", check=False)


def get_volume():
    """(index, max) of the media stream."""
    m = re.search(r"volume is (\d+) in range \[(\d+)\.\.(\d+)\]", shell("cmd media_session volume --stream 3 --get"))
    return (int(m.group(1)), int(m.group(3))) if m else (0, 15)


def set_volume(index):
    shell(f"cmd media_session volume --stream 3 --set {index}", check=False)


# --- clients ---

def push_dex():
    run("push", DEX_LOCAL, DEX_REMOTE)


def start_root_client(port, size, screen, rotation, touch, audio_port):
    """Launches the app_process client; returns the Popen (its stdout carries 'pid N')."""
    args = f"port={port} size={size[0]}x{size[1]} screen={screen[0]}x{screen[1]} rot={rotation}"
    if touch:
        args += " touch=%s:%d:%d" % touch
    if audio_port:
        args += f" audio={audio_port}"
    cmd = f"CLASSPATH={DEX_REMOTE} app_process / phonemonitor.Main {args}"
    return subprocess.Popen(["adb", "shell", "su -c " + _quote(cmd)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def kill_pid(pid):
    shell(f"kill {pid}", root=True, check=False)


def apk_installed():
    return APK_PACKAGE in shell(f"pm path {APK_PACKAGE}", check=False)


def install_apk():
    run("install", "-r", "-g", APK_LOCAL)


def start_apk_client(port, size, rotation, touch, audio_port):
    # otherwise Android shows a "swipe down to exit full screen" overlay that eats touches
    shell("settings put secure immersive_mode_confirmations confirmed", check=False)
    shell(f"am start -n {APK_PACKAGE}/.MonitorActivity --ei port {port} --ei width {size[0]} "
          f"--ei height {size[1]} --es rot {rotation} --ez touch {'true' if touch else 'false'} "
          f"--ei audio {audio_port or 0}")


def stop_apk_client():
    shell(f"am force-stop {APK_PACKAGE}", check=False)
