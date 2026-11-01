# Changelog

Each release on GitHub is published from its entry here. To release, raise
`__version__` in `nitro_panel.py`, add an entry for it below and push to `main`.

## 0.3.0 - 2026-11-01

- Plasma 6 system tray widget, laid out like Plasma's Power and Battery popup: a five-step power mode slider, profiles, keyboard light, the 80% charge limit and sensors. The tray icon shows the current power mode.
- Command line options: `--status` (JSON), `--mode`, `--profile`, `--kb-brightness`, `--battery-limit` and `--kb-fine`. They run without loading GTK, so they return in about 30 ms.
- Keyboard brightness in NitroSense's steps (off, 25, 50, 75, 100%) or in steps of 1, shared between the panel and the widget.

## 0.2.0 - 2026-11-01

- Sensors on the Power tab: CPU and GPU temperature and fan RPM, read without waking a sleeping NVIDIA GPU.
- Battery health on the Battery tab.
- Profiles tab with Gaming, Quiet and Battery saver to start with.
- Optional background service: apply a profile when the charger is plugged in or out, and show the new power mode when the NitroSense key is pressed.

## 0.1.0 - 2026-11-01

- First release: four-zone keyboard RGB, power modes, fan control, 80% charge limit and USB charging while off, on top of Linuwu-Sense.
