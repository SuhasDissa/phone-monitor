package phonemonitor;

import android.view.Surface;
import android.view.SurfaceControl;
import java.net.InetSocketAddress;
import java.nio.channels.SocketChannel;
import java.util.HashMap;
import java.util.Map;

// Root client, run without an APK:
//   CLASSPATH=phone-monitor.dex app_process / phonemonitor.Main port=27183 size=2408x1080 \
//       screen=1080x2408 rot=ccw [touch=/dev/input/event3:1080:2408] [audio=27184]
//
// Renders the stream on a top-most SurfaceFlinger layer (needs ACCESS_SURFACE_FLINGER, i.e. root),
// rotated so the landscape desktop fills the portrait panel:
//   rot=ccw  phone's top edge is on the left   (USB connector on the right)
//   rot=cw   phone's top edge is on the right  (USB connector on the left)
public class Main {
    public static void main(String[] argv) throws Exception {
        Map<String, String> args = new HashMap<>();
        for (String a : argv) {
            int eq = a.indexOf('=');
            args.put(a.substring(0, eq), a.substring(eq + 1));
        }
        int port = Integer.parseInt(args.get("port"));
        String[] sz = args.get("size").split("x"), sc = args.get("screen").split("x");
        final int w = Integer.parseInt(sz[0]), h = Integer.parseInt(sz[1]);
        final int screenW = Integer.parseInt(sc[0]), screenH = Integer.parseInt(sc[1]);
        final boolean cw = "cw".equals(args.get("rot"));
        System.out.println("pid " + android.os.Process.myPid());
        System.out.flush();

        SurfaceControl layer = new SurfaceControl.Builder()
                .setName("phone-monitor")
                .setBufferSize(w, h)
                .build();
        SurfaceControl.Transaction t = new SurfaceControl.Transaction();
        t.setLayer(layer, Integer.MAX_VALUE);
        // SurfaceFlinger applies x' = dsdx*x + dtdy*y, y' = dtdx*x + dsdy*y (setMatrix is hidden).
        // ccw: x' = y,          y' = screenH - x
        // cw:  x' = screenW - y, y' = x
        SurfaceControl.Transaction.class
                .getMethod("setMatrix", SurfaceControl.class, float.class, float.class, float.class, float.class)
                .invoke(t, layer, 0f, cw ? 1f : -1f, cw ? -1f : 1f, 0f);
        t.setPosition(layer, cw ? screenW : 0, cw ? 0 : screenH);
        t.setVisibility(layer, true);
        t.apply();

        final VideoDecoder decoder = new VideoDecoder(new Surface(layer), w, h);
        final SocketChannel ch = SocketChannel.open(new InetSocketAddress("127.0.0.1", port));
        ch.socket().setTcpNoDelay(true);

        if (args.containsKey("touch")) {
            final String[] td = args.get("touch").split(":");
            final TouchSender sender = new TouchSender(ch);
            Thread touch = new Thread() {
                public void run() {
                    try {
                        EvdevTouch.run(td[0], Integer.parseInt(td[1]), Integer.parseInt(td[2]), screenW, screenH,
                                new EvdevTouch.Mapper() {
                                    public int[] map(float px, float py) {
                                        // inverse of the layer transform, scaled to the stream size
                                        if (cw) return new int[]{Math.round(py * w / screenH), Math.round((screenW - px) * h / screenW)};
                                        return new int[]{Math.round((screenH - py) * w / screenH), Math.round(px * h / screenW)};
                                    }
                                }, sender);
                    } catch (Exception e) {
                        System.err.println("touch: " + e);
                    }
                }
            };
            touch.setDaemon(true);
            touch.start();
        }

        if (args.containsKey("audio")) {
            final int audioPort = Integer.parseInt(args.get("audio"));
            Thread audio = new Thread() {
                public void run() {
                    try {
                        new AudioPlayer().run(audioPort);
                    } catch (Exception e) {
                        System.err.println("audio: " + e);
                    }
                }
            };
            audio.setDaemon(true);
            audio.start();
        }

        decoder.run(ch);
        decoder.release();
    }
}
