package phonemonitor;

import android.media.MediaCodec;
import android.media.MediaFormat;
import android.view.Surface;
import java.nio.ByteBuffer;
import java.nio.channels.SocketChannel;

// Reads length-prefixed (u32 big-endian) H.264 access units from a socket and renders
// them to a Surface through the hardware decoder in low-latency mode.
public class VideoDecoder {
    private final MediaCodec codec;

    public VideoDecoder(Surface surface, int w, int h) throws Exception {
        MediaFormat fmt = MediaFormat.createVideoFormat("video/avc", w, h);
        fmt.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
        fmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 1 << 21);
        fmt.setInteger(MediaFormat.KEY_PRIORITY, 0);
        codec = MediaCodec.createDecoderByType("video/avc");
        codec.configure(fmt, surface, null, 0);
        codec.start();
        System.err.println("decoder: " + codec.getName());

        Thread out = new Thread() {
            public void run() {
                MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
                try {
                    while (true) {
                        int idx = codec.dequeueOutputBuffer(info, -1);
                        if (idx >= 0) codec.releaseOutputBuffer(idx, true);
                    }
                } catch (IllegalStateException e) {
                    // codec released
                }
            }
        };
        out.setDaemon(true);
        out.start();
    }

    // Blocks until the socket closes.
    public void run(SocketChannel ch) throws Exception {
        ByteBuffer hdr = ByteBuffer.allocate(4);
        long pts = 0;
        while (true) {
            hdr.clear();
            while (hdr.hasRemaining()) if (ch.read(hdr) < 0) return;
            int len = hdr.getInt(0);
            int idx = codec.dequeueInputBuffer(-1);
            ByteBuffer buf = codec.getInputBuffer(idx);
            buf.clear();
            buf.limit(len);
            while (buf.hasRemaining()) if (ch.read(buf) < 0) return;
            codec.queueInputBuffer(idx, 0, len, pts, 0);
            pts += 16667;
        }
    }

    public void release() {
        try {
            codec.stop();
        } catch (IllegalStateException ignored) {
        }
        codec.release();
    }
}
