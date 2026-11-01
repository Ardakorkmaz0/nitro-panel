# Nitro Panel

A small GTK control panel for Acer Nitro and Predator laptops on Linux: keyboard RGB, power modes, fans and battery settings in one window.

Nitro Panel is only the front end. The hardware access comes from the [Linuwu-Sense](https://github.com/0x7375646F/Linuwu-Sense) kernel module, which has to be installed first.

> Not affiliated with or endorsed by Acer.

| Keyboard | Power | Battery |
|---|---|---|
| ![Keyboard tab](docs/screenshots/keyboard.png) | ![Power tab](docs/screenshots/power.png) | ![Battery tab](docs/screenshots/battery.png) |

## Features

- **Keyboard** (four-zone RGB keyboards): a color per zone, or one of seven effects (breathing, neon, wave, shifting, zoom, meteor, twinkling) with speed and direction. Brightness slider and quick colors.
- **Power mode**: Eco, Quiet, Balanced, Performance and Turbo. Modes your laptop does not offer right now (Turbo on battery, for example) are greyed out.
- **Fans**: auto, max, or a custom CPU/GPU percentage, with live fan RPM.
- **Battery**: stop charging at 80%, and USB charging while the laptop is off.

The panel only shows the controls your model exposes. Changes apply immediately; there is no Apply button.

## Tested models

| Model | Result |
|---|---|
| Acer Nitro AN16-41 (Ryzen 7040, RTX 4070) | Everything works |

Other models supported by Linuwu-Sense should work too. If you try one, please open an issue with your model name and what worked.

## Requirements

- The Linuwu-Sense kernel module, loaded (`lsmod | grep linuwu_sense`). On Arch it is in the AUR as `linuwu-sense-dkms-git`, or build it from [source](https://github.com/0x7375646F/Linuwu-Sense).
- Python 3, PyGObject and GTK 3. On Arch: `sudo pacman -S python-gobject gtk3`.
- Your user in the `linuwu_sense` group, which Linuwu-Sense creates.

## Install

```bash
git clone https://github.com/Ardakorkmaz0/nitro-panel
cd nitro-panel
sudo make install
```

Then add yourself to the group and log out and back in:

```bash
sudo usermod -aG linuwu_sense $USER
```

Open **Nitro Panel** from your application menu, or run `nitro-panel`.

To remove it, run `sudo make uninstall` in the same folder.

On Arch you can also build a package with the PKGBUILD in [`packaging/aur`](packaging/aur):

```bash
cd packaging/aur && makepkg -si
```

## How permissions work

Nitro Panel runs as your normal user and never as root.

- Linuwu-Sense makes its keyboard, fan and battery files writable by the `linuwu_sense` group.
- `make install` adds a tmpfiles rule (`data/nitro-panel.tmpfiles.conf`) that does the same for `/sys/firmware/acpi/platform_profile`, so the group can change the power mode too.
- Without that rule, changing the power mode asks for your password through polkit.

## Good to know

- Other tools can change the power mode as well: power-profiles-daemon, tuned, or the power widget in your desktop. The panel always shows the mode that is currently active.
- Linuwu-Sense saves your keyboard settings and restores them at boot.
- On some models the two wave directions may be swapped.

## Troubleshooting

| Message or problem | What to check |
|---|---|
| "The linuwu_sense kernel module is not loaded" | `lsmod \| grep linuwu_sense` and `dkms status`. After a kernel update, DKMS should rebuild the module. |
| "No write access yet" | Run `id -nG` and look for `linuwu_sense`. If it is missing, add yourself and log in again. |
| No Keyboard tab | Your model does not expose a four-zone keyboard through Linuwu-Sense. |
| Power mode asks for a password every time | The tmpfiles rule is not installed. Run `sudo make install` again. |

## Credits

- [Linuwu-Sense](https://github.com/0x7375646F/Linuwu-Sense) for the kernel module.
- [acer-predator-turbo-and-rgb-keyboard-linux-module](https://github.com/JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module), where much of the Acer WMI research started.

## License

[GPL-3.0-or-later](LICENSE)
