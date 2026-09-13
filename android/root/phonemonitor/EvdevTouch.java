package phonemonitor;

import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

// Grabs a multitouch (protocol B) evdev device exclusively and forwards its contacts.
// Needs root: /dev/input/* is not readable by the shell user.
public class EvdevTouch {
    static final int EVIOCGRAB = 0x40044590;
    static final int EV_SYN = 0, EV_ABS = 3;
    static final int ABS_MT_SLOT = 0x2f, ABS_MT_POSITION_X = 0x35, ABS_MT_POSITION_Y = 0x36, ABS_MT_TRACKING_ID = 0x39;
    static final int SLOTS = 10;

    public interface Mapper {
        // phone pixel coordinates -> virtual display pixel coordinates
        int[] map(float px, float py);
    }

    static void grab(FileDescriptor fd) throws Exception {
        // Os.ioctlInt is hidden; both known signatures pass a non-null pointer as the
        // ioctl argument, which is all EVIOCGRAB checks for.
        Class<?> os = Class.forName("android.system.Os");
        for (Method m : os.getMethods()) {
            if (!m.getName().equals("ioctlInt")) continue;
            Class<?>[] p = m.getParameterTypes();
            if (p.length == 3) {
                m.invoke(null, fd, EVIOCGRAB, p[2].getConstructor(int.class).newInstance(1));
                return;
            }
            if (p.length == 2) {
                m.invoke(null, fd, EVIOCGRAB);
                return;
            }
        }
        throw new NoSuchMethodException("Os.ioctlInt");
    }

    public static void run(String dev, int xmax, int ymax, int screenW, int screenH, Mapper mapper, TouchSender sender) throws Exception {
        FileInputStream in = new FileInputStream(dev);
        grab(in.getFD());
        int evSize = android.os.Process.is64Bit() ? 24 : 16;
        byte[] raw = new byte[evSize * 64];
        ByteBuffer ev = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);

        int[] x = new int[SLOTS], y = new int[SLOTS], id = new int[SLOTS], prevId = new int[SLOTS];
        boolean[] moved = new boolean[SLOTS];
        Arrays.fill(id, -1);
        Arrays.fill(prevId, -1);
        int slot = 0;

        while (true) {
            int n = in.read(raw, 0, raw.length);
            if (n < 0) return;
            for (int off = 0; off + evSize <= n; off += evSize) {
                int type = ev.getShort(off + evSize - 8) & 0xffff;
                int code = ev.getShort(off + evSize - 6) & 0xffff;
                int value = ev.getInt(off + evSize - 4);
                if (type == EV_ABS) {
                    if (code == ABS_MT_SLOT) { if (value >= 0 && value < SLOTS) slot = value; }
                    else if (code == ABS_MT_TRACKING_ID) id[slot] = value;
                    else if (code == ABS_MT_POSITION_X) { x[slot] = value; moved[slot] = true; }
                    else if (code == ABS_MT_POSITION_Y) { y[slot] = value; moved[slot] = true; }
                } else if (type == EV_SYN && code == 0) {
                    for (int s = 0; s < SLOTS; s++) {
                        int action;
                        if (id[s] >= 0 && prevId[s] < 0) action = TouchSender.DOWN;
                        else if (id[s] < 0 && prevId[s] >= 0) action = TouchSender.UP;
                        else if (id[s] >= 0 && moved[s]) action = TouchSender.MOVE;
                        else { moved[s] = false; prevId[s] = id[s]; continue; }
                        int[] d = mapper.map(x[s] * (float) screenW / xmax, y[s] * (float) screenH / ymax);
                        sender.add(action, s, d[0], d[1]);
                        moved[s] = false;
                        prevId[s] = id[s];
                    }
                    sender.frame();
                }
            }
        }
    }
}
