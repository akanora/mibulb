<p align="center"><img src="assets/logo.png" width="128" alt="Mi Bulb logo"></p>

# Mi Bulb

Control a **Mi Smart LED Bulb Essential (White and Color)** from your Windows PC. You don't need a hub or any extra hardware, and nothing goes through the cloud. The app talks to the bulb directly over your Wi-Fi using Xiaomi's local miIO/MIoT protocol, the same one the Xiaomi Home app uses.

- Turn the light on or off, set brightness, white temperature (1700–6500 K) and RGB colour
- Use the system-tray icon: click it for a quick panel (power, brightness, white, colours, scenes), right-click for the full menu
- Keyboard shortcuts that work in any app: toggle, brighter/dimmer, on/off, white presets. You can change them all.
- Start it with Windows, quietly in the tray
- Several bulbs: control one, or all of them at once
- Screen sync: the light follows the main colour on your screen (pick which screen), great for games and films
- Music sync: the light pulses and changes colour with whatever your PC plays
- Effects the bulb plays by itself: Candle, Breathing, Rainbow, Party and more
- Pick a colour from anywhere on your screen
- Scenes: one-click favourites like Reading, Relax, Movie and Gaming. Save your own and give them shortcuts.
- Sleep timer that fades out (and also sets the bulb's own timer), sunrise wake-up, and schedules for one or all lights
- Evening warmth: white light gets warmer from sunset (or a time you choose) towards bedtime
- Follows your PC: off when you lock it or it sleeps, back on when you return
- Updates itself: new versions are downloaded, checked and installed automatically
- In English or Turkish (Türkçe): follows your Windows language, or pick one in settings
- Control it from the command line, or from a Stream Deck, script or Home Assistant through an optional local API
- Export your settings to move them to another PC
- Scan the network to find the bulb's IP

Tested target: model `MJDPL01YL` / `yeelink.light.color5`. Other MIoT lights may work if you override the property ids (see [Other bulbs](#other-bulbs)).

> **Türkçe:** Mi Bulb, Mi Smart LED Bulb Essential ampulünüzü bilgisayarınızdan, ek donanım olmadan ve yerel ağ üzerinden kontrol eder. Windows diliniz Türkçeyse uygulama otomatik olarak Türkçe açılır; dili Ayarlar → Uygulama → Dil bölümünden değiştirebilirsiniz. İndirmek için [son sürüm](https://github.com/akanora/mibulb/releases/latest) sayfasından `MiBulb-Setup.exe` dosyasını çalıştırın, ardından **Xiaomi ile giriş yap** düğmesine tıklayıp QR kodu Xiaomi Home uygulamasıyla okutun.

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

## Music sync

Pick **Music sync** in the Effects ▾ menu (or the tray menu, or give it a shortcut). Mi Bulb listens to the sound going to your speakers or headphones. That's Windows "loopback", so no microphone is used and nothing is recorded or saved. Loudness sets the brightness, and each beat moves the colour along the rainbow. Silence leaves the light as it is.

## Effects

**Effects ▾** in the Colour panel (or the tray menu) has Candle, Breathing, Rainbow, Party, Romance, Ocean, Police and Alarm. The bulb plays them by itself, so they're perfectly smooth and keep going with no traffic from the PC. Click **Stop effect**, change the light yourself, or give each effect a shortcut to switch it on and off. Effects need the Yeelight command set, which Mi Smart LED Bulb Essential has.

## Pick a colour from the screen

Click **⌖** in the Colour panel. Mi Bulb hides, shows a still image of your screens, and you click any pixel to set the light to that colour. Esc or right-click cancels. It works across several screens and with Windows display scaling.

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
- **Schedules for one light:** with several bulbs, each schedule can control the lights picked in the window, all lights, or one bulb ("Bedroom at 7:00").
- **Evening warmth** (Settings → Automation): from sunset (or a time you choose) until bedtime, white light fades from neutral to a warm 2200–3000 K and stays warm through the night. For "Sunset", enter your latitude and longitude; sunset is calculated on your PC. It only changes lights that are on and white. If you pick a white yourself, it leaves you alone until the next evening.
- **Follow the PC** (Settings → Automation): turn the light off when you lock the PC or it goes to sleep, and back on when you return. It only turns the light back on if Mi Bulb was the one that turned it off.

The sleep timer also sets the bulb's own off-timer, so the light still goes off if your PC sleeps or shuts down first. Changing the light yourself (a slider, a scene, a shortcut) stops a running timer, sunrise, effect or sync. Timers and schedules run inside Mi Bulb, so it needs to be running, which it can do quietly in the tray.

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

### Language

Mi Bulb is in English and Turkish. **Automatic** follows your Windows display language. You can also pick one under Settings → App → Language and click **Restart now**.

To add a language, add a table of translations to `mibulb/i18n.py`. The app's text is translated as it's shown, so nothing else needs to change.

### Keyboard shortcuts

*(Effects, scenes, music sync and the sleep timer can have shortcuts too.)*

The **Shortcuts** tab lists every action. Click a shortcut and press the keys you want. Esc cancels, and Backspace clears it. Shortcuts work in any app, including games, and you can turn them all off with one checkbox.

| Action | Default |
| --- | --- |
| Toggle light | Ctrl+Alt+L |
| Brighter (+10%) | Ctrl+Alt+PageUp |
| Dimmer (−10%) | Ctrl+Alt+PageDown |
| Turn on, Turn off, Warm white, Neutral white, Daylight, Show Mi Bulb window | not set |

A shortcut needs Ctrl, Alt or Win, so normal typing isn't blocked. F13–F24 also work on their own. If Windows or another app already uses a combination, the tab says so next to it.

On many keyboard layouts Ctrl+Alt+<key> is the same as AltGr+<key> and types a character: for example Ctrl+Alt+Q types @ on Turkish and German keyboards, and Ctrl+Alt+L types ł on Polish ones. That's why only a few defaults are set. The Shortcuts tab checks your keyboard layout and warns next to any shortcut that would block a character, for example "On your keyboard this also types ł".

## Local API (Stream Deck, scripts, Home Assistant)

Turn it on in Settings → App → **Local API**. Mi Bulb then answers web requests on port 8765, and shows an address with your key to copy:

```text
http://127.0.0.1:8765/api/toggle?key=YOUR-KEY
```

| Request | Does |
| --- | --- |
| `/api/status` | what the light is doing, plus your scenes, effects and lights (JSON) |
| `/api/on`, `/api/off`, `/api/toggle` | power |
| `/api/brightness?value=40` | brightness 1–100, or `value=up` / `value=down` |
| `/api/white?kelvin=2700` | white temperature |
| `/api/color?hex=ff8800` | colour |
| `/api/scene?name=Relax` | a scene |
| `/api/effect?name=candle` | an effect (`name=stop` stops it) |
| `/api/sleep?minutes=30` | sleep timer (`minutes=0` cancels) |
| `/api/screen-sync`, `/api/music-sync` | switch syncing on or off |
| `/api/light?name=Bed` | control one bulb, or `name=all` |

- **Requests:** GET or POST. The key can also go in an `X-API-Key` header.
- **Stream Deck:** use a "Website" or "API request" action with the address. Home Assistant can use a `rest_command`.
- **Security:** every request needs the key, so other programs, or a web page open in your browser, can't use it without it. **New key** replaces it. By default only this PC can connect. Tick "Also from other devices on my network" for Home Assistant or a phone; Windows may then ask whether to allow Mi Bulb through the firewall.

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

## Your data

Settings are in `%APPDATA%\mibulb\config.json`:

- **Encrypted tokens:** bulb tokens and the API key are encrypted with Windows DPAPI, so only your Windows account can read them. Copying the file to another PC or account doesn't reveal them.
- **Safe saving:** settings go to a temporary file first and then replace the old one, so a crash or power cut can't leave a half-written file. The previous version is kept as `config.json.bak`. If the file is ever damaged anyway, Mi Bulb starts from that backup, keeps the damaged copy as `config.broken-….json`, and tells you.
- **Moving PCs:** Settings → App → **Export settings…** writes a file you can **Import** on another PC. It contains the tokens in readable form, so keep it private.

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

## Publishing

[docs/PUBLISHING.md](docs/PUBLISHING.md) covers releasing, listing on winget (`winget install akanora.MiBulb`) and free code signing for open-source projects, which removes the SmartScreen warning.

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

The app is in `mibulb/`:

| Part | What it does |
| --- | --- |
| `miio.py` | the miIO LAN protocol: AES-encrypted JSON over UDP port 54321. The "hello" handshake is reused for a minute, which halves round trips (27 → 19 ms per command on a real bulb). |
| `bulb.py` | bulb commands for both command sets (Yeelight and MIoT), and `BulbGroup`, which sends to several bulbs at once. An offline bulb is skipped for a while (30 s, up to 5 min) instead of holding up the others. |
| `cloud.py` | the one-time Xiaomi QR sign-in that reads your bulbs' IPs and tokens |
| `config.py`, `secret.py` | settings, safe saving, DPAPI-encrypted tokens |
| `automation.py`, `effects.py` | schedules, fades, sunset and evening warmth; the effect list |
| `screensync.py`, `musicsync.py` | following the screen and the PC's sound |
| `api.py`, `hotkey.py`, `pcevents.py`, `startup.py`, `updates.py`, `i18n.py` | local API, shortcuts, lock/sleep, start with Windows, self-update, translations |
| `gui/` | the windows: `app.py` (main window and tray), `settings.py`, `quickpanel.py`, `dialogs.py`, `picker.py` |

## License

[MIT](LICENSE). This project is not affiliated with Xiaomi or Yeelight.
