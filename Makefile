PREFIX ?= /usr/local
DESTDIR ?=
APP_ID := io.github.ardakorkmaz0.NitroPanel

BINDIR := $(DESTDIR)$(PREFIX)/bin
APPDIR := $(DESTDIR)$(PREFIX)/share/applications
TMPFILESDIR := $(DESTDIR)$(PREFIX)/lib/tmpfiles.d

.PHONY: install uninstall

install:
	install -Dm755 nitro_panel.py $(BINDIR)/nitro-panel
	install -Dm644 data/$(APP_ID).desktop $(APPDIR)/$(APP_ID).desktop
	install -Dm644 data/nitro-panel.tmpfiles.conf $(TMPFILESDIR)/nitro-panel.conf
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
