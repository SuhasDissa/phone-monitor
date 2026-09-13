PREFIX ?= $(HOME)/.local

all: host android

host:
	$(MAKE) -C host/kwin-cast

android:
	android/build.sh

install: all
	mkdir -p $(PREFIX)/bin $(PREFIX)/share/applications
	ln -sf $(CURDIR)/host/phone-monitor $(PREFIX)/bin/phone-monitor
	sed 's|^Exec=.*|Exec=$(CURDIR)/host/phone-monitor|' host/phone-monitor.desktop > $(PREFIX)/share/applications/phone-monitor.desktop

uninstall:
	rm -f $(PREFIX)/bin/phone-monitor $(PREFIX)/share/applications/phone-monitor.desktop $(PREFIX)/share/applications/kwin-cast.desktop

clean:
	$(MAKE) -C host/kwin-cast clean
	rm -rf android/out host/phonemonitor/__pycache__

.PHONY: all host android install uninstall clean
