# Jens' Home Assistant Add-ons

A personal add-on repository for Home Assistant (Supervised / HA OS).

## Add-ons in this repository

### 🐱 [CatWatch](./catwatch)

Motion-triggered snapshots of the food bowls with **local, on-device AI** that
recognises **which cat is eating**. Works a bit like MotionEye (watch an RTSP
camera, record on motion) but adds per-cat recognition and publishes everything
to Home Assistant over MQTT so you can build automations — e.g. get notified if
a particular cat hasn't eaten in a while.

Everything runs on your own hardware. No images leave your network.

### 💊 [MedTracker](./medtracker)

Track which medicines each **person or animal** needs to take per day — fixed
times (e.g. ½ a pill twice a day) or every N hours, whole or fractional pills.
Exposes Home Assistant entities and **Take / Skip / Undo** buttons (one device
per subject, plus a hub) so you can build reminders and notifications, with an
optional inventory / low-stock warning and a phone-friendly web UI.

## Installing this repository

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**.
2. Open the **⋮** menu (top-right) → **Repositories**.
3. Add this repository's URL:
   `https://github.com/jensdescamps/home-assistant-plugins`
4. The add-ons above appear in the store. Click one to install.

> Developing locally? You can also drop this folder into the Supervisor's
> `addons` share (via the Samba or "Studio Code Server" add-on) and it shows up
> under **Local add-ons** without needing a Git remote.

See each add-on's `DOCS.md` for full setup instructions.
