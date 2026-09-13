PROTOCOLS = zkde-screencast-unstable-v1 fake-input xdg-output-unstable-v1
GEN_C = $(PROTOCOLS:%=gen/%-protocol.c)
GEN_H = $(PROTOCOLS:%=gen/%-client-protocol.h)
CFLAGS += -O2 -Wall -Igen $(shell pkg-config --cflags wayland-client)
LDLIBS += $(shell pkg-config --libs wayland-client)

kwin-cast: kwin-cast.c $(GEN_C) $(GEN_H)
	$(CC) $(CFLAGS) -o $@ kwin-cast.c $(GEN_C) $(LDLIBS)

gen/%-protocol.c: protocols/%.xml
	@mkdir -p gen
	wayland-scanner private-code $< $@

gen/%-client-protocol.h: protocols/%.xml
	@mkdir -p gen
	wayland-scanner client-header $< $@

clean:
	rm -rf gen kwin-cast

.PHONY: clean
