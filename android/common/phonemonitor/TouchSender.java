package phonemonitor;

import java.nio.ByteBuffer;
import java.nio.channels.SocketChannel;

// Sends touch contacts to the host on the video socket as 12-byte packets:
// u8 action (0 down, 1 move, 2 up, 3 frame), u8 slot, u16 pad, i32 x, i32 y
// with x/y in virtual-display pixel coordinates.
public class TouchSender {
    public static final int DOWN = 0, MOVE = 1, UP = 2, FRAME = 3;

    private final SocketChannel ch;
    private final ByteBuffer pkt = ByteBuffer.allocate(12 * 32);

    public TouchSender(SocketChannel ch) {
        this.ch = ch;
    }

    public synchronized void add(int action, int slot, int x, int y) {
        if (pkt.remaining() < 24) flush();
        pkt.put((byte) action).put((byte) slot).putShort((short) 0).putInt(x).putInt(y);
    }

    public synchronized void frame() {
        if (pkt.position() == 0) return;
        pkt.put((byte) FRAME).put((byte) 0).putShort((short) 0).putInt(0).putInt(0);
        flush();
    }

    private void flush() {
        pkt.flip();
        try {
            while (pkt.hasRemaining()) ch.write(pkt);
        } catch (Exception e) {
            System.err.println("touch send: " + e);
        }
        pkt.clear();
    }
}
