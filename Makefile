PREFIX ?= /usr/local
DESTDIR ?=
APP_ID := io.github.ardakorkmaz0.NitroPanel

BINDIR := $(DESTDIR)$(PREFIX)/bin
APPDIR := $(DESTDIR)$(PREFIX)/share/applications
TMPFILESDIR := $(DESTDIR)$(PREFIX)/lib/tmpfiles.d
USERUNITDIR := $(DESTDIR)$(PREFIX)/lib/systemd/user
PLASMOIDDIR := $(DESTDIR)$(PREFIX)/share/plasma/plasmoids/io.github.ardakorkmaz0.nitropanel

.PHONY: install uninstall

install:
	install -Dm755 nitro_panel.py $(BINDIR)/nitro-panel
	install -Dm644 data/$(APP_ID).desktop $(APPDIR)/$(APP_ID).desktop
	install -Dm644 data/nitro-panel.tmpfiles.conf $(TMPFILESDIR)/nitro-panel.conf
	install -d $(USERUNITDIR)
	sed 's|@BINDIR@|$(PREFIX)/bin|' data/nitro-panel-daemon.service.in > $(USERUNITDIR)/nitro-panel-daemon.service
	chmod 644 $(USERUNITDIR)/nitro-panel-daemon.service
	install -Dm644 plasmoid/metadata.json $(PLASMOIDDIR)/metadata.json
	install -Dm644 plasmoid/contents/ui/main.qml $(PLASMOIDDIR)/contents/ui/main.qml
# Apply the permission rule now instead of waiting for the next boot.
# Skipped for package builds, where DESTDIR is set.
ifeq ($(DESTDIR),)
	-systemd-tmpfiles --create $(TMPFILESDIR)/nitro-panel.conf
	-update-desktop-database $(APPDIR)
endif

uninstall:
	rm -f $(BINDIR)/nitro-panel
	rm -f $(APPDIR)/$(APP_ID).desktop
	rm -f $(TMPFILESDIR)/nitro-panel.conf
	rm -f $(USERUNITDIR)/nitro-panel-daemon.service
	rm -rf $(PLASMOIDDIR)
