<p align="center"><img src="assets/logo.png" width="128" alt="Mi Bulb logo"></p>

# Mi Bulb

Control a **Mi Smart LED Bulb Essential (White and Color)** from your Windows PC. You don't need a hub or any extra hardware, and nothing goes through the cloud. The app talks to the bulb directly over your Wi-Fi using Xiaomi's local miIO/MIoT protocol, the same one the Xiaomi Home app uses.

- Turn the light on or off, set brightness, white temperature (1700–6500 K) and RGB colour
- Use the system-tray icon: click it to toggle, right-click for brightness and white presets
- Press **Ctrl+Alt+L** anywhere to toggle the light
- Start it with Windows, quietly in the tray
- Get a notice in the window when a new version is released
- Control it from the command line, for scripts, shortcuts or Task Scheduler
- Scan the network to find the bulb's IP

Tested target: model `MJDPL01YL` / `yeelink.light.color5`. Other MIoT lights may work if you override the property ids (see [Other bulbs](#other-bulbs)).

## Requirements

- Your PC and the bulb are on the **same local network**
- The bulb has already been set up in the Xiaomi Home app
- Python 3.9+ (only if you're not using the released `.exe`)

## 1. Install

Get these from the [latest release](https://github.com/akanora/mibulb/releases/latest). GitHub Actions builds every release straight from the source in this repo; nobody uploads it by hand. See [Verifying a download](#verifying-a-download).

### Option A: installer (recommended)

Run **`MiBulb-Setup.exe`**. It doesn't need admin rights. It installs Mi Bulb for your Windows account and adds it to the Start menu. It can also:

- start Mi Bulb in the system tray when you sign in (on by default; you can change this later in settings)
- add a desktop shortcut

Uninstall it from **Settings → Apps**. To update, run the newer installer over the old one; your bulb settings are kept.

### Option B: portable

Run **`MiBulb-Portable.exe`** from anywhere, for example a USB stick. Nothing gets installed. It still saves your bulb settings to `%APPDATA%\mibulb`.

### Option C: run from source

```powershell
git clone https://github.com/akanora/mibulb.git
cd mibulb
python -m pip install -r requirements.txt
python -m mibulb
```

To build it yourself, run `.\build.ps1`. It creates `dist\MiBulb-Portable.exe`, and `dist\MiBulb-Setup.exe` too if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed.

Only one Mi Bulb runs at a time. Opening it again brings the existing window to the front.

## 2. Connect your bulb

Each Xiaomi device has a secret 32-character token that it needs before it accepts local commands. The Xiaomi Home app doesn't show it, but Mi Bulb fetches it for you:

1. Start Mi Bulb. The settings window opens on first run (or click ⚙).
2. Click **Sign in with Xiaomi**. A QR code appears.
3. In the Xiaomi Home app on your phone, tap the scan icon and scan the code.
4. Pick your bulb from the list and click **Save**.

Mi Bulb never sees your password, because you approve the sign-in on your phone. It checks every Xiaomi region server for your devices, saves only the bulb's IP, token and device id to `%APPDATA%\mibulb\config.json`, and then discards the login session. After that it talks to the bulb only over your local network.

From the command line, `python -m mibulb login` does the same thing. It prints a link to open in your browser, which shows the QR code.

If the router gives the bulb a new IP, Mi Bulb finds it again on the network by its device id. Reserving the IP in your router's DHCP settings still helps.

> Keep the token private. Anyone on your network who has it can control the bulb. If you reset the bulb or set it up again in the Xiaomi Home app, its token changes, so sign in again.

**Manual setup:** you can also type the IP and token in yourself, for example ones you got from [Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor).

To start Mi Bulb with Windows, turn on **Start with Windows** in settings → App. This works for the portable exe too.

## App settings

Open settings with ⚙ in the window, or **Settings…** in the tray menu. The **App** tab has:

| Option | What it does |
| --- | --- |
| Start with Windows | Starts Mi Bulb in the tray when you sign in. This is the same setting as the installer's checkbox. |
| Ctrl+Alt+L | Toggles the light from any app. If another app already uses this shortcut, Mi Bulb tells you. |
| Check for updates | Checks GitHub once at startup and shows a link in the window if a newer version exists. **Check now** checks right away. |
| Open folder | Opens `%APPDATA%\mibulb`, where your settings and the bulb's token live. |
| Forget this bulb | Removes the bulb's name, IP and token from this PC, but keeps your app options. |

App options are saved as soon as you change them.

## Command line

```powershell
python -m mibulb on
python -m mibulb off
python -m mibulb toggle
python -m mibulb brightness 40
python -m mibulb temp 2700
python -m mibulb color ff8800
python -m mibulb status
python -m mibulb discover
python -m mibulb login
```

`--ip` and `--token` override the config file for a single command.

## Configuration

The config file is looked up in this order:

1. the path in the `MIBULB_CONFIG` environment variable
2. `config.json` in the current folder
3. `%APPDATA%\mibulb\config.json`

See [`config.example.json`](config.example.json). `config.json` is listed in `.gitignore` so your token is never committed.

### Other bulbs

The default property ids come from the [MIoT spec for yeelink.light.color5](https://home.miot-spec.com/spec/yeelink.light.color5) (service 2: on=1, brightness=2, color-temperature=3, color=4, mode=5). If your light uses different ids, look it up on [home.miot-spec.com](https://home.miot-spec.com) and add them to your config:

```json
"properties": { "on": 1, "brightness": 2, "color_temperature": 3, "color": 4, "mode": 5 }
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No response from …` | Check the IP, make sure the bulb is powered and the PC is on the same network/VLAN, and allow Python/MiBulb through Windows Firewall (UDP port 54321). |
| `Checksum mismatch` | The token is wrong or out of date. Extract it again. |
| Sign-in finds no devices | Make sure you scanned with the account that owns the bulb in Xiaomi Home. Shared devices only show up if they're shared through a home. |
| `discover` finds nothing | Some routers block broadcast between Wi-Fi and wired clients. Enter the IP manually. |

## Development

The logo is drawn in code (`mibulb/icon.py`). After changing it, run `python tools/make_icon.py` to regenerate `assets/icon.ico` and `assets/logo.png`.


```powershell
python -m unittest discover -s tests
```

The tests run against a fake bulb on localhost, so you don't need a real device.

## Verifying a download

Every release is built by the [Release workflow](.github/workflows/release.yml) on a clean GitHub-hosted Windows machine, from the tagged commit. Each release includes:

- `MiBulb-Setup.exe`, `MiBulb-Portable.exe` and `SHA256SUMS.txt`. Compare a file's hash with the one listed:
  ```powershell
  (Get-FileHash .\MiBulb-Setup.exe -Algorithm SHA256).Hash
  ```
- A signed **build provenance attestation** for both exes that proves they came from this repo's workflow. You can check it with the [GitHub CLI](https://cli.github.com/):
  ```powershell
  gh attestation verify MiBulb-Setup.exe --repo akanora/mibulb
  ```

The exe isn't code-signed with a paid certificate, so Windows SmartScreen may warn the first time you run it. Click "More info" → "Run anyway".

## How it works

- `mibulb/miio.py` is a small implementation of the miIO LAN protocol. Commands go out as AES-128-CBC encrypted JSON over UDP port 54321, with a key derived from the token.
- `mibulb/bulb.py` maps on/brightness/colour onto bulb commands. It detects whether the bulb speaks the older Yeelight command set (`get_prop`, `set_power`, `set_bright`, …), which the Essential bulb uses on firmware 2.0.x, or MIoT `get_properties` / `set_properties`.
- `mibulb/cloud.py` handles the one-time Xiaomi QR sign-in and reads your device list (IP + token) from Xiaomi's API. It follows the same method as Xiaomi Cloud Tokens Extractor, rewritten from scratch.

## License

[MIT](LICENSE). This project is not affiliated with Xiaomi or Yeelight.
