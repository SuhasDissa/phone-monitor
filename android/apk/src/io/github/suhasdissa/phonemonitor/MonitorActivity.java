package io.github.suhasdissa.phonemonitor;

import android.app.Activity;
import android.content.pm.ActivityInfo;
import android.os.Bundle;
import android.os.StrictMode;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import java.net.InetSocketAddress;
import java.nio.channels.SocketChannel;
import phonemonitor.AudioPlayer;
import phonemonitor.TouchSender;
import phonemonitor.VideoDecoder;

// Non-root client. Started by the host:
//   am start -n io.github.suhasdissa.phonemonitor/.MonitorActivity \
//       --ei port 27183 --ei width 2408 --ei height 1080 --es rot ccw --ez touch true --ei audio 27184
public class MonitorActivity extends Activity implements SurfaceHolder.Callback {
    private int port, width, height, audioPort;
    private boolean touch;
    private SurfaceView view;
    private SocketChannel ch;
    private TouchSender sender;
    private AudioPlayer audio;
    private Thread videoThread;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        port = getIntent().getIntExtra("port", 27183);
        width = getIntent().getIntExtra("width", 2408);
        height = getIntent().getIntExtra("height", 1080);
        audioPort = getIntent().getIntExtra("audio", 0);
        touch = getIntent().getBooleanExtra("touch", true);
        boolean cw = "cw".equals(getIntent().getStringExtra("rot"));
        // touch packets are written to the localhost socket straight from onTouchEvent
        StrictMode.setThreadPolicy(new StrictMode.ThreadPolicy.Builder().permitNetwork().build());

        setRequestedOrientation(cw ? ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE
                                   : ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().getAttributes().layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        getWindow().setDecorFitsSystemWindows(false);

        view = new SurfaceView(this);
        view.getHolder().addCallback(this);
        setContentView(view);

        WindowInsetsController ic = getWindow().getInsetsController();
        ic.hide(WindowInsets.Type.systemBars());
        ic.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
    }

    @Override
    public void surfaceCreated(final SurfaceHolder holder) {
        videoThread = new Thread() {
            public void run() {
                try {
                    VideoDecoder decoder = new VideoDecoder(holder.getSurface(), width, height);
                    ch = SocketChannel.open(new InetSocketAddress("127.0.0.1", port));
                    ch.socket().setTcpNoDelay(true);
                    sender = new TouchSender(ch);
                    if (audioPort > 0) {
                        audio = new AudioPlayer();
                        Thread a = new Thread() {
                            public void run() {
                                try {
                                    audio.run(audioPort);
                                } catch (Exception e) {
                                    System.err.println("audio: " + e);
                                }
                            }
                        };
                        a.setDaemon(true);
                        a.start();
                    }
                    decoder.run(ch);
                    decoder.release();
                } catch (Exception e) {
                    System.err.println("video: " + e);
                }
                runOnUiThread(new Runnable() {
                    public void run() {
                        finish();
                    }
                });
            }
        };
        videoThread.start();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) {
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        closeConnection();
    }

    @Override
    protected void onDestroy() {
        closeConnection();
        super.onDestroy();
    }

    private void closeConnection() {
        try {
            if (audio != null) audio.stop();
            if (ch != null) ch.close();
        } catch (Exception ignored) {
        }
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        if (!touch || sender == null) return false;
        int action = e.getActionMasked();
        int idx = e.getActionIndex();
        switch (action) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN:
                sender.add(TouchSender.DOWN, e.getPointerId(idx), mapX(e.getX(idx)), mapY(e.getY(idx)));
                break;
            case MotionEvent.ACTION_MOVE:
                for (int i = 0; i < e.getPointerCount(); i++)
                    sender.add(TouchSender.MOVE, e.getPointerId(i), mapX(e.getX(i)), mapY(e.getY(i)));
                break;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_POINTER_UP:
                sender.add(TouchSender.UP, e.getPointerId(idx), mapX(e.getX(idx)), mapY(e.getY(idx)));
                break;
            case MotionEvent.ACTION_CANCEL:
                for (int i = 0; i < e.getPointerCount(); i++)
                    sender.add(TouchSender.UP, e.getPointerId(i), mapX(e.getX(i)), mapY(e.getY(i)));
                break;
            default:
                return false;
        }
        sender.frame();
        return true;
    }

    private int mapX(float x) {
        return Math.round(x * width / view.getWidth());
    }

    private int mapY(float y) {
        return Math.round(y * height / view.getHeight());
    }
}
