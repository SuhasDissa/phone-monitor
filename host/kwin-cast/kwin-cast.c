// Creates a KWin virtual output, streams it via PipeWire, and injects touch events onto it.
// Usage: kwin-cast NAME W H SCALE
// stdout: "node <id>" once the stream exists.
// stdin: touch commands in coordinates normalized to the virtual output:
//   d ID X Y  (down)   m ID X Y  (motion)   u ID  (up)   f  (frame)
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include "zkde-screencast-unstable-v1-client-protocol.h"
#include "fake-input-client-protocol.h"
#include "xdg-output-unstable-v1-client-protocol.h"

static struct zkde_screencast_unstable_v1 *cast;
static struct org_kde_kwin_fake_input *fake;
static struct zxdg_output_manager_v1 *xdg_mgr;
static char out_name[256];
static double out_x, out_y, out_w, out_h;
static int out_found;

struct out { struct wl_output *wl; struct zxdg_output_v1 *xdg; double x, y, w, h; char *name; };
static struct out *outs[64];
static int n_outs;

static void xo_pos(void *d, struct zxdg_output_v1 *o, int32_t x, int32_t y) { struct out *s = d; s->x = x; s->y = y; }
static void xo_size(void *d, struct zxdg_output_v1 *o, int32_t w, int32_t h) { struct out *s = d; s->w = w; s->h = h; }
static void xo_done(void *d, struct zxdg_output_v1 *o) {}
static void xo_name(void *d, struct zxdg_output_v1 *o, const char *n) { struct out *s = d; free(s->name); s->name = strdup(n); }
static void xo_desc(void *d, struct zxdg_output_v1 *o, const char *n) {}
static const struct zxdg_output_v1_listener xo_listener = { xo_pos, xo_size, xo_done, xo_name, xo_desc };

static void wo_geometry(void *d, struct wl_output *o, int32_t x, int32_t y, int32_t pw, int32_t ph, int32_t sub, const char *make, const char *model, int32_t tr) {}
static void wo_mode(void *d, struct wl_output *o, uint32_t f, int32_t w, int32_t h, int32_t r) {}
static void wo_done(void *d, struct wl_output *o) {
    struct out *s = d;
    if (s->name && strcmp(s->name, out_name) == 0) {
        out_x = s->x; out_y = s->y; out_w = s->w; out_h = s->h; out_found = 1;
    }
}
static void wo_scale(void *d, struct wl_output *o, int32_t f) {}
static void wo_name(void *d, struct wl_output *o, const char *n) {}
static void wo_desc(void *d, struct wl_output *o, const char *n) {}
static const struct wl_output_listener wo_listener = { wo_geometry, wo_mode, wo_done, wo_scale, wo_name, wo_desc };

static void global(void *d, struct wl_registry *reg, uint32_t id, const char *iface, uint32_t ver) {
    if (strcmp(iface, zkde_screencast_unstable_v1_interface.name) == 0)
        cast = wl_registry_bind(reg, id, &zkde_screencast_unstable_v1_interface, ver < 5 ? ver : 5);
    else if (strcmp(iface, org_kde_kwin_fake_input_interface.name) == 0)
        fake = wl_registry_bind(reg, id, &org_kde_kwin_fake_input_interface, ver < 2 ? ver : 2);
    else if (strcmp(iface, zxdg_output_manager_v1_interface.name) == 0)
        xdg_mgr = wl_registry_bind(reg, id, &zxdg_output_manager_v1_interface, ver < 3 ? ver : 3);
    else if (strcmp(iface, wl_output_interface.name) == 0) {
        struct out *s = calloc(1, sizeof *s);
        s->wl = wl_registry_bind(reg, id, &wl_output_interface, ver < 4 ? ver : 4);
        wl_output_add_listener(s->wl, &wo_listener, s);
        if (n_outs < 64) outs[n_outs++] = s;
    }
}

// xdg_output_manager may be announced after some wl_outputs in the initial registry burst
static void attach_xdg_outputs(void) {
    for (int i = 0; i < n_outs; i++) {
        if (outs[i]->xdg || !xdg_mgr) continue;
        outs[i]->xdg = zxdg_output_manager_v1_get_xdg_output(xdg_mgr, outs[i]->wl);
        zxdg_output_v1_add_listener(outs[i]->xdg, &xo_listener, outs[i]);
    }
}
static void global_remove(void *d, struct wl_registry *reg, uint32_t id) {}
static const struct wl_registry_listener reg_listener = { global, global_remove };

static void closed(void *d, struct zkde_screencast_stream_unstable_v1 *s) { fprintf(stderr, "stream closed\n"); exit(0); }
static void created(void *d, struct zkde_screencast_stream_unstable_v1 *s, uint32_t node) { printf("node %u\n", node); fflush(stdout); }
static void failed(void *d, struct zkde_screencast_stream_unstable_v1 *s, const char *err) { fprintf(stderr, "failed: %s\n", err); exit(1); }
static const struct zkde_screencast_stream_unstable_v1_listener stream_listener = { closed, created, failed };

static void handle_line(char *line) {
    char op; unsigned id; double nx = 0, ny = 0;
    int n = sscanf(line, "%c %u %lf %lf", &op, &id, &nx, &ny);
    if (!fake || n < 1) return;
    if (op == 'f') { org_kde_kwin_fake_input_touch_frame(fake); return; }
    if (!out_found) return;
    wl_fixed_t x = wl_fixed_from_double(out_x + nx * out_w), y = wl_fixed_from_double(out_y + ny * out_h);
    if (op == 'd' && n == 4) org_kde_kwin_fake_input_touch_down(fake, id, x, y);
    else if (op == 'm' && n == 4) org_kde_kwin_fake_input_touch_motion(fake, id, x, y);
    else if (op == 'u' && n >= 2) org_kde_kwin_fake_input_touch_up(fake, id);
}

int main(int argc, char **argv) {
    if (argc != 5) { fprintf(stderr, "usage: %s NAME W H SCALE\n", argv[0]); return 2; }
    snprintf(out_name, sizeof out_name, "Virtual-%s", argv[1]);
    struct wl_display *dpy = wl_display_connect(NULL);
    if (!dpy) { fprintf(stderr, "no wayland display\n"); return 1; }
    struct wl_registry *reg = wl_display_get_registry(dpy);
    wl_registry_add_listener(reg, &reg_listener, NULL);
    wl_display_roundtrip(dpy);
    attach_xdg_outputs();
    if (!cast) { fprintf(stderr, "zkde_screencast_unstable_v1 not available\n"); return 1; }
    if (!fake) fprintf(stderr, "org_kde_kwin_fake_input not available, touch disabled\n");
    else org_kde_kwin_fake_input_authenticate(fake, "phone-monitor", "touch input from phone");

    struct zkde_screencast_stream_unstable_v1 *stream = zkde_screencast_unstable_v1_stream_virtual_output(
        cast, argv[1], atoi(argv[2]), atoi(argv[3]), wl_fixed_from_double(atof(argv[4])),
        ZKDE_SCREENCAST_UNSTABLE_V1_POINTER_EMBEDDED);
    zkde_screencast_stream_unstable_v1_add_listener(stream, &stream_listener, NULL);

    struct pollfd fds[2] = { { wl_display_get_fd(dpy), POLLIN, 0 }, { STDIN_FILENO, POLLIN, 0 } };
    char buf[4096]; size_t len = 0;
    for (;;) {
        while (wl_display_prepare_read(dpy) != 0) wl_display_dispatch_pending(dpy);
        wl_display_flush(dpy);
        if (poll(fds, 2, -1) < 0) { wl_display_cancel_read(dpy); continue; }
        if (fds[0].revents & POLLIN) { wl_display_read_events(dpy); wl_display_dispatch_pending(dpy); attach_xdg_outputs(); }
        else wl_display_cancel_read(dpy);
        if (fds[0].revents & (POLLHUP | POLLERR)) return 0;
        if (fds[1].revents & POLLIN) {
            ssize_t r = read(STDIN_FILENO, buf + len, sizeof buf - len - 1);
            if (r <= 0) return 0;
            len += r; buf[len] = 0;
            char *start = buf, *nl;
            while ((nl = strchr(start, '\n'))) { *nl = 0; handle_line(start); start = nl + 1; }
            len = strlen(start); memmove(buf, start, len + 1);
            wl_display_flush(dpy);
        } else if (fds[1].revents & POLLHUP) return 0;
    }
}
