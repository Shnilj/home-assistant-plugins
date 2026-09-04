# 🐱 CatWatch

Motion-triggered snapshots of the food bowls with **local, on-device AI** that
recognises **which cat is eating** — and publishes it all to Home Assistant over
MQTT so you can automate on it.

Think MotionEye (watch an RTSP camera, capture on motion) plus per-cat
recognition. Everything runs on your own hardware; no images leave your network.

- 📷 Watches any RTSP/ONVIF camera, with auto-reconnect
- 🎯 Motion detection limited to a food-bowl region you draw in the UI
- 🧠 Recognises your individual cats with a lightweight local model (no cloud, no GPU)
- 🏠 MQTT discovery: activity, current cat, live snapshot, and per-cat *eating* /
  *last eaten* / *meals today* entities
- 🖼️ Built-in web UI to set the region, label captures, and retrain

See **[DOCS.md](./DOCS.md)** for full setup and example automations.
