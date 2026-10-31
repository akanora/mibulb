<p align="center"><img src="assets/logo.png" width="128" alt="Mi Bulb logo"></p>

# Mi Bulb

Control a **Mi Smart LED Bulb Essential (White and Color)** from your Windows PC. You don't need a hub or any extra hardware, and nothing goes through the cloud. The app talks to the bulb directly over your Wi-Fi using Xiaomi's local miIO/MIoT protocol, the same one the Xiaomi Home app uses.

- Turn the light on or off, set brightness, white temperature (1700–6500 K) and RGB colour
- Use the system-tray icon: click it for a quick panel (power, brightness, white, colours, scenes), right-click for the full menu
- Keyboard shortcuts that work in any app: toggle, brighter/dimmer, on/off, white presets. You can change them all.
- Start it with Windows, quietly in the tray
- Several bulbs: control one, or all of them at once
- Screen sync: the light follows the main colour on your screen, great for games and films
- Scenes: one-click favourites like Reading, Relax, Movie and Gaming. Save your own and give them shortcuts.
- Sleep timer that fades out, sunrise wake-up, and schedules (on/off/scene at set times)
- Follows your PC: off when you lock it or it sleeps, back on when you return
- Updates itself: new versions are downloaded, checked and installed automatically
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

## Several bulbs

Click **Sign in with Xiaomi** in Settings → Bulbs, then **Add all lights from my account** to add every light at once. You can also add bulbs one by one, or type them in yourself.

With more than one bulb, the name at the top of the window gets a ▾. Click it to control **All lights** or just one bulb. The same choice is in the tray menu under **Light**. Scenes, shortcuts, timers and schedules act on whatever is picked there. If one bulb doesn't answer, the others still change, and the status line names the one that didn't.

## Screen sync

Click **Screen sync** in the Colour panel (or in the tray menu, or give it a shortcut). The light then follows the main colour on your main screen. Colourful areas count more than grey or dark UI, so a sunset or a red warning wins over the menu bars. It can also follow how bright the screen is (Settings → App → Screen sync).

- It updates about 3 times a second with a short fade. A Mi Smart LED Bulb Essential handled 4 commands a second for 30 seconds without refusing any.
- It uses about 10% of one CPU core, which is under 2% of a typical 8-core CPU.
- Windowed and borderless games work. Exclusive fullscreen games may not be captured, and then the light keeps its last colour.
- Changing the light yourself, or locking the PC, stops it.

## Tray quick panel

Left-click the tray icon to open a small panel above the taskbar, like the Windows volume pop-up. It has power, brightness and white sliders, colour swatches, your first six scenes and a 30-minute sleep timer. Click anywhere else or press Esc to close it. If you'd rather left-click just toggle the light, change that in Settings → App → Tray icon.

## Scenes

The **Scenes** panel in the window has one-click favourites. It starts with Reading, Relax, Movie, Gaming and Night light.

- **Click** a scene to apply it. It turns the light on and sets colour and brightness in one step.
- **+ Save current** saves what the bulb is doing right now as a new scene.
- **Right-click** a scene to update it to the current light, rename it, give it a shortcut or delete it.
- Scenes also appear in the tray menu, and each one can have its own keyboard shortcut (Settings → Shortcuts).

## Timers and automation

- **Sleep timer** (⏾ in the window, or the tray menu): slowly dims the light over 15–90 minutes, then turns it off. You can also give it a keyboard shortcut.
- **Sunrise wake-up:** starts as a faint deep-orange glow and brightens to full neutral white over 10, 15 or 30 minutes. Start one now from ⏾, or schedule it.
- **Schedules** (Settings → Automation): run Turn on, Turn off, a scene or a sunrise at a time of day, on the days you choose.
- **Follow the PC** (Settings → Automation): turn the light off when you lock the PC or it goes to sleep, and back on when you return. It only turns the light back on if Mi Bulb was the one that turned it off.

Changing the light yourself (a slider, a scene, a shortcut) stops a running timer or sunrise. Timers and schedules run inside Mi Bulb, so it needs to be running, which it can do quietly in the tray.

## Updates

The installed version keeps itself up to date. When Mi Bulb starts, or when you click Settings → App → **Check now**, it:

1. looks for a newer release on GitHub
2. downloads `MiBulb-Setup.exe` and checks it against the SHA-256 that GitHub publishes for it. A file that doesn't match is deleted, never run.
3. runs the installer silently. Mi Bulb closes, updates, and opens again. Your settings, scenes and start-with-Windows choice are kept.

If you installed for all users (in `C:\Program Files`), Windows asks for permission first. If you cancel, Mi Bulb won't ask again at startup for that version, but **Check now** still offers it. You can turn automatic updates off in Settings → App.

The portable exe can't replace itself while it runs, so it shows a download link instead.

## App settings

Open settings with ⚙ in the window, or **Settings…** in the tray menu. The **App** tab has:

| Option | What it does |
| --- | --- |
| Start with Windows | Starts Mi Bulb in the tray when you sign in. This is the same setting as the installer's checkbox. |
| Install new versions automatically | Checks GitHub when Mi Bulb starts. If there's a new version, it downloads the installer, checks it against the SHA-256 published on GitHub, installs it and reopens Mi Bulb. **Check now** does the same right away. |
| Open folder | Opens `%APPDATA%\mibulb`, where your settings and the bulb's token live. |
| Forget this bulb | Removes the bulb's name, IP and token from this PC, but keeps your app options. |

App options are saved as soon as you change them.

### Keyboard shortcuts

The **Shortcuts** tab lists every action. Click a shortcut and press the keys you want. Esc cancels, and Backspace clears it. Shortcuts work in any app, including games, and you can turn them all off with one checkbox.

| Action | Default |
| --- | --- |
| Toggle light | Ctrl+Alt+L |
| Brighter (+10%) | Ctrl+Alt+PageUp |
| Dimmer (−10%) | Ctrl+Alt+PageDown |
| Turn on, Turn off, Warm white, Neutral white, Daylight, Show Mi Bulb window | not set |

A shortcut needs Ctrl, Alt or Win, so normal typing isn't blocked. F13–F24 also work on their own. If Windows or another app already uses a combination, the tab says so next to it.

On some keyboard layouts (for example Turkish, German or Polish), Ctrl+Alt+<key> is the same as AltGr+<key> and types a special character. That's why only a few defaults are set. If a character stops working, give that action a different shortcut.

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
python -m mibulb --bulb all off
```

`--bulb NAME` picks a bulb by name (or `--bulb all`). `--ip` and `--token` control a bulb that isn't in your settings.

## Configuration

The config file is looked up in this order:

1. the path in the `MIBULB_CONFIG` environment variable
2. `config.json` in the current folder
3. `%APPDATA%\mibulb\config.json`

See [`config.example.json`](config.example.json). `config.json` is listed in `.gitignore` so your token is never committed.

### Other bulbs

The default property ids come from the [MIoT spec for yeelink.light.color5](https://home.miot-spec.com/spec/yeelink.light.color5) (service 2: on=1, brightness=2, color-temperature=3, color=4, mode=5). If your light uses different ids, look it up on [home.miot-spec.com](https://home.miot-spec.com) and add them to that bulb's entry in your config:

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
