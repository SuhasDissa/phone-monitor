# phone-monitor

Use an Android phone as a low-latency secondary monitor for a KDE Plasma (Wayland) desktop,
over USB only. The phone also acts as a touchscreen for that display and as an audio output
device, and its brightness and volume are controllable from the desktop.

No network stack is involved: video, audio and touch travel over `adb reverse` TCP sockets,
which adb tunnels through the USB bulk endpoint.

```
Host (Arch / Plasma 6 Wayland)                              Phone (Android 11+)
──────────────────────────────────────────────────          ─────────────────────────────────────────────
kwin-cast ── zkde_screencast.stream_virtual_output ──►      root client (app_process, no APK)
             creates "Virtual-phone" output                    MediaCodec H.264 → top-most SurfaceFlinger layer
             fake_input ◄── touch                              evdev grab → touch packets
PipeWire DMA-BUF ► vah264lpenc ► u32-len framed AUs ► USB ►  or
"Phone" null sink ► S16LE PCM ────────────────────► USB ►   APK client (no root, no launcher icon)
pactl volume ◄──────────────────── phone volume ◄─ adb        SurfaceView + onTouchEvent + AudioTrack
```

Measured on an RTX 3050 / Alder Lake laptop and a Galaxy A13 (MT6768): ~30–45 ms glass-to-glass
at 60 fps, ~30–50 ms audio.

## Requirements

Host:

- KDE Plasma 6 on Wayland (KWin ≥ 6.x; uses `zkde_screencast_unstable_v1`, `org_kde_kwin_fake_input`)
- PipeWire + WirePlumber, `pactl` (pipewire-pulse)
- GStreamer with `gst-plugin-pipewire` and an H.264 encoder:
  `gst-plugin-va` (Intel/AMD VA-API, zero-copy — recommended) or `gst-plugin-nvcodec` (NVENC)
- Python 3, `python-gobject`, GTK 3, `libayatana-appindicator` (tray)
- `adb`, `wayland` (`wayland-scanner`), a C compiler, `pkgconf`
- Android SDK: `build-tools` (d8, aapt2, zipalign, apksigner) and a `platforms/android-3x` for `android.jar`;
  `ANDROID_HOME` or `~/Android/Sdk`

Arch: `pacman -S gst-plugin-va gst-plugin-pipewire python-gobject gtk3 libayatana-appindicator android-tools wayland`

Phone:

- USB debugging enabled and authorized for this host
- Root (Magisk) for the root client, or nothing extra for the APK client
- Hardware H.264 decoder (any phone from the last decade)

## Build

```
make            # host/kwin-cast/kwin-cast, android/out/phone-monitor.{dex,apk}
make install    # symlink ~/.local/bin/phone-monitor and a .desktop launcher
```

`android/build.sh` builds both phone clients with `javac` + `d8` + `aapt2` + `apksigner`
directly; there is no Gradle. The APK is signed with `android/keystore.jks`
(password `phone-monitor`), a throwaway key committed to the repo so builds from any checkout
can upgrade each other on the phone.

## Use

```
phone-monitor              # GUI; close the window to keep it in the tray
phone-monitor --headless   # no GUI, stream until Ctrl-C
```

The app is single-instance. Running it again with options controls the running instance,
which makes them bindable to global shortcuts:

```
phone-monitor --toggle           # start/stop streaming
phone-monitor --start | --stop
phone-monitor --brightness 40    # phone backlight, 0-100
phone-monitor --quit
```

Once streaming:

- A new display `Virtual-phone` appears in System Settings → Display; arrange it like any monitor.
- A `Phone` audio sink appears in the audio applet. Its volume and mute are mirrored to the
  phone's media volume (and the phone's volume keys move the sink back), so Plasma's volume
  controls and media keys drive the phone's hardware volume.
- Touching the phone injects touch events on the virtual display.
- The phone's brightness is set to the configured level and restored when streaming stops.
  Plasma's brightness slider can't attach to a virtual output (it needs an EDID), so brightness
  lives in the app window, the tray menu, and `--brightness`.

Settings (saved in `~/.config/phone-monitor/config.json`):

| Option | Meaning |
|---|---|
| Client | `root`: pushes a dex and runs it with `app_process` as root, no install. `apk`: installs the APK once and starts its activity. |
| Encoder | `va` (VA-API low-power, zero-copy from the compositor's DMA-BUF) or `nv` (NVENC, copies through system memory). |
| Resolution | `auto` = phone panel in landscape (e.g. 2408x1080), or `WxH`. |
| Display scale | Plasma scale factor for the virtual output; 2 is readable on a 6.5" phone. |
| Bitrate | CBR kbit/s. USB 2.0 comfortably carries 20–40 Mbit/s. |
| Orientation | Which way the phone is rotated: top edge on the left (USB on the right) or on the right. |
| Touch / Audio / Volume sync | Feature toggles. |
| Port | Video port; audio uses port+1. |

Set `PM_DEBUG=1` to log every touch event on the host.

## Root client vs APK client

| | Root (`app_process`) | APK |
|---|---|---|
| Install on phone | none (dex pushed to `/data/local/tmp`) | one APK, no launcher icon |
| Display | top-most SurfaceFlinger layer, above lock screen, notifications, everything | a fullscreen Activity; can be covered by calls/notifications |
| Touch | evdev grabbed exclusively; Android never sees the touches | Activity `onTouchEvent` |
| Latency | identical: same decoder, same BufferQueue path | |

Both talk the same protocol to the host, so switching is a config change.

## Protocol

- **Video** (`port`, host → phone): `u32 big-endian length` + one H.264 access unit (Annex B, SPS/PPS repeated before each IDR).
- **Touch** (`port`, phone → host): 12-byte packets `u8 action (0 down, 1 move, 2 up, 3 frame)`,
  `u8 slot`, `u16 pad`, `i32 x`, `i32 y` in virtual-display pixels. A `frame` packet ends a group.
- **Audio** (`port+1`, host → phone): raw S16LE 48 kHz stereo PCM, no framing.

## How the host side works

- `host/kwin-cast` is a small Wayland client. `stream_virtual_output` makes KWin create the
  virtual output and hand back a PipeWire node; `org_kde_kwin_fake_input` injects touches;
  `xdg_output` tracks where the output is so touches follow if you rearrange displays.
  KWin only exposes those two interfaces to executables listed in a `.desktop` file with
  `X-KDE-Wayland-Interfaces`; `phone-monitor` writes `~/.local/share/applications/kwin-cast.desktop`
  pointing at the built binary and refreshes the service cache.
- `host/phonemonitor/session.py` builds the GStreamer pipelines:
  `pipewiresrc (DMA-BUF) → vapostproc → vah264lpenc (CBR, no B-frames, 1 ref) → h264parse → appsink`
  and `pipewiresrc (sink monitor, 5 ms quantum) → S16LE → appsink`, frames the buffers and
  writes them to the sockets. `pipewiresrc` needs `media.class=Stream/Input/Video` and the
  target's `object.serial`, otherwise WirePlumber links it to the default camera instead.
- The audio sink is `module-null-sink` named `phone`; its monitor is what gets streamed.
  Sink volume is not applied to the monitor, so the phone's hardware volume is used instead
  (`cmd media_session volume`), mirrored both ways by `controls.py`.
- Everything the phone needs is set through `adb shell` from the `shell` user: `svc power stayon`,
  `settings put system screen_brightness`, `am start`, `adb reverse`.

## Layout

```
Makefile, android/build.sh       build everything, no Gradle
host/kwin-cast/                  Wayland helper (C) + protocol XMLs
host/phonemonitor/               Python package: session, adb, controls, gui, tray, app
host/phone-monitor               entry point
android/common/phonemonitor/     VideoDecoder, AudioPlayer, TouchSender (shared by both clients)
android/root/phonemonitor/       Main (SurfaceControl layer), EvdevTouch (EVIOCGRAB)
android/apk/                     AndroidManifest.xml, MonitorActivity
android/keystore.jks             APK signing key
```

## Troubleshooting

- *`zkde_screencast_unstable_v1 not available`*: the grant file doesn't match the binary path.
  Delete `~/.local/share/applications/kwin-cast.desktop` and start again.
- *Black phone screen in root mode*: `dumpsys SurfaceFlinger` should list a `phone-monitor` layer
  with a non-empty `VisibleRegion`. If the region is empty, the phone's panel size differs from
  what `wm size` reports; set Resolution explicitly.
- *`target not found` from GStreamer*: WirePlumber couldn't link to the KWin node; check
  `wpctl status` shows it under Video → Streams.
- *Audio clicks*: raise `PRIME_FRAMES` / `MAX_QUEUED` in `android/common/phonemonitor/AudioPlayer.java`.
- *Phone reboots*: never `pkill -f` on the phone through nested quoting; the host only kills the
  exact pid the client reports.
