# 🌐 StarChat CLI (Beta)

A terminal-based peer-to-peer chat application using `prompt_toolkit`, `rich`, and `ngrok` to enable both **LAN** and **Public (no port forwarding)** communication between users.

---

## 🚀 Features

- Terminal-style chat interface with output/input split view
- Works over LAN and public internet (via ngrok)
- Timestamped, tagged messages for clarity
- Access code display for easy identification
- No port forwarding or UPnP required
- Supports multiple clients

---

## 🧰 Requirements

- Python 3.7 or higher
- Dependencies in `requirements.txt`

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 📦 Installation

Clone or download this repository:

```bash
git clone https://github.com/yourusername/starchat.git
cd starchat
```

Or just place the `starchat_cli.Beta.py` file somewhere locally.

---

## 🌐 Setup ngrok (for public hosting)

1. Download ngrok: [https://ngrok.com/download](https://ngrok.com/download)

2. Authenticate ngrok:

```bash
ngrok config add-authtoken <your_token_here>
```

3. The app will automatically start `ngrok` when you select **Public Host** mode.

---

## 💽 Running StarChat

### Start in Host Mode

```bash
python starchat_cli.Beta.py
```

1. Choose `1` for LAN Host or `2` for Public Host (via ngrok).
2. Share the **Access Code** and **IP**\*\*:PORT\*\* with clients.
3. Wait for clients to connect and chat!

### Start in Client Mode

```bash
python starchat_cli.Beta.py
```

1. Choose `3` for Client Mode.
2. Enter the host's IP (or ngrok hostname) and port.
3. Chat with others in real-time.

---

## 🧪 Example

**Host Output:**

```
Access Code: 3028 | [Varconstint] | Public IP: 1.tcp.ngrok.io:13307
```

**Client Input:**

```
Host IP: 1.tcp.ngrok.io
Port: 13307
Auth Code: 3028
```

---

## 👍 Exiting the Chat

- Type `/exit` to leave the session.

---

## 🛠️ Troubleshooting

- ❌ If ngrok fails to start, ensure it’s in your system path or set `NGROK_PATH` in the script.
- 🔐 Ensure your firewall allows Python/port access.
- 🌍 Ngrok free tier limits concurrent tunnels.

---

## 📜 License

MIT License © 2025 Javen Beck

