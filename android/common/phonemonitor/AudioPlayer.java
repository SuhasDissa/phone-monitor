package phonemonitor;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.SocketChannel;

// Plays raw S16LE 48kHz stereo PCM received from a socket.
public class AudioPlayer {
    static final int RATE = 48000, CHUNK_FRAMES = 240, MAX_QUEUED = 1920, PRIME_FRAMES = 480;

    private volatile boolean stopped;

    public void stop() {
        stopped = true;
    }

    // Blocks until the socket closes or stop() is called.
    public void run(int port) throws Exception {
        SocketChannel ch = SocketChannel.open(new InetSocketAddress("127.0.0.1", port));
        ch.socket().setTcpNoDelay(true);
        int minBuf = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_STEREO, AudioFormat.ENCODING_PCM_16BIT);
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                        .setFlags(AudioAttributes.FLAG_LOW_LATENCY)
                        .build())
                .setAudioFormat(new AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                        .build())
                .setBufferSizeInBytes(minBuf)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .build();
        System.err.println("audio: buffer " + track.getBufferSizeInFrames() + " frames");
        track.play();
        try {
            ByteBuffer chunk = ByteBuffer.allocateDirect(CHUNK_FRAMES * 4);
            byte[] silence = new byte[PRIME_FRAMES * 4];
            long written = track.write(silence, 0, silence.length) / 4;
            int underruns = track.getUnderrunCount();
            while (!stopped) {
                chunk.clear();
                while (chunk.hasRemaining()) if (ch.read(chunk) < 0) return;
                chunk.flip();
                // Keep the queue between ~10ms and 40ms: drop when the host clock runs
                // ahead, re-prime after an underrun when it runs behind.
                long queued = written - (track.getPlaybackHeadPosition() & 0xffffffffL);
                if (queued > MAX_QUEUED) continue;
                int u = track.getUnderrunCount();
                if (u != underruns) {
                    underruns = u;
                    written += track.write(silence, 0, silence.length) / 4;
                }
                int n = track.write(chunk, chunk.remaining(), AudioTrack.WRITE_BLOCKING);
                if (n > 0) written += n / 4;
            }
        } finally {
            track.release();
            ch.close();
        }
    }
}
