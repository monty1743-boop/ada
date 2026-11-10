# ADA

A Discord voice assistant. She sits in a voice channel, hears only you, and speaks back when you start the sentence with her name. Speech recognition and the voice stay on your machine. The answers come from Cursor through an OpenAI-compatible proxy.

This is the stack behind one working assistant, packaged so someone else can bring up their own. It is not a homelab installer. You bring a Linux host, a Discord application, and a Cursor account.

## What she does

- Joins a Discord voice channel and speaks with [Edge TTS](https://github.com/rany2/edge-tts), voice `en-US-AriaNeural`.
- Transcribes with local Faster-Whisper (`small`, English).
- Ignores every Discord user except the id in `DISCORD_ALLOWED_USERS`.
- Answers only when that person's sentence starts with **Ada**. `Hey Ada` and `okay Ada` count. The name is removed before the request is sent. Other sentences are dropped.
- Posts the transcript and the written reply in the voice channel's own text chat, not in the public text channel where `/voice join` was typed.
- If a reply is still out after 8 seconds, speaks one short hold line, pauses, then the answer. A faster reply skips the hold line.
- Waits 0.8 seconds of silence before treating a sentence as finished. A warm short reply then starts speaking in about 5 seconds. A first call after startup, or a reply that uses tools, takes longer.
- Uses [Hermes Agent](https://github.com/NousResearch/hermes-agent) and [cursor-openai-api](https://github.com/Randomblock1/cursor-openai-api). Model `auto` rejects a `reasoning_effort` field. The patch omits that field.

The sample personality is `personalities/watch-officer.md`. Change the commanding officer's name before you install it. It is a manner, not a requirement of the voice path.

## Requirements

- Linux with Python 3.11 or newer, ffmpeg, and a working Hermes install
- Docker, for the Cursor proxy
- A Discord bot with the Message Content and Server Members intents
- A Cursor user API key

Tested on Hermes Agent v0.22.2, commit `d923a5eb`, discord.py 2.7.1, davey 0.1.7, faster-whisper 1.2.1, PyAV 19, and Edge TTS. The patch will not apply on a different Hermes commit.

## 1. Install Hermes

Follow the Hermes install for a Linux user, then check out the tested commit:

```bash
cd ~/.hermes/hermes-agent
git checkout d923a5eb
```

If your checkout lives somewhere else, set `HERMES_AGENT` when you run the installer below.

## 2. Run the Cursor proxy

```bash
git clone https://github.com/Randomblock1/cursor-openai-api.git
cd cursor-openai-api
printf 'CURSOR_API_KEY=%s\n' 'paste-your-key' > .env
docker compose up -d --build
```

`docker restart` does not reload `.env`. Recreate the container after a key change. Do not publish port 8080 on the public internet. Hermes talks to `http://127.0.0.1:8080/v1` on the same machine, or to the proxy's LAN address if they are on different hosts.

Confirm it answers:

```bash
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"Reply with exactly: ready"}]}'
```

## 3. Create the Discord bot

1. Create an application at https://discord.com/developers/applications and add a bot.
2. Turn on Message Content Intent and Server Members Intent.
3. Invite the bot to your server with View Channels, Send Messages, Connect, Speak, and Use Voice Activity.
4. Make a voice channel only you and the bot can see. Grant the bot those same rights on that channel. The bot cannot grant them to itself.
5. Copy your Discord user id (User Settings → Advanced → Developer Mode, then right-click your name).

Put the secrets in `~/.hermes/.env`:

```bash
DISCORD_BOT_TOKEN=...
DISCORD_ALLOWED_USERS=your_user_id
```

Merge `config/assistant.yaml.example` into `~/.hermes/config.yaml`. Change `model.base_url` if the proxy is not on this machine.

## 4. Apply this repository

```bash
git clone https://github.com/monty1743-boop/ada.git
cd ada
chmod +x scripts/install.sh
HERMES_HOME=$HOME/.hermes ./scripts/install.sh
python3 -m unittest discover -s tests
```

The installer copies the hold-line module, applies `patches/hermes-watch.patch`, installs `davey==0.1.7` and `edge-tts`, and removes a PyAV argument that faster-whisper 1.2.1 still passes. Do not upgrade davey to 0.2. Discord's library never calls the handshake that 0.2 requires, and voice decrypt then fails.

Copy the personality if the installer did not:

```bash
cp personalities/watch-officer.md ~/.hermes/SOUL.md
```

A systemd unit is in `deploy/hermes-gateway.service`. Change the user and paths, then:

```bash
sudo systemctl enable --now hermes-gateway
```

`hermes update` replaces the agent tree and can replace the virtualenv. Re-run `scripts/install.sh` afterward.

## 5. Talk to her

1. Join the voice channel.
2. In a text channel, run `/voice join`. The "joined" note stays in that text channel. A restart of the gateway drops her out of voice, and this command is how she comes back.
3. Say `Ada, can you hear me?`

She will not answer `can you hear me?` without her name. She will not answer anyone else in the channel.

## Layout

| Path | Purpose |
| --- | --- |
| `patches/hermes-watch.patch` | Wake word, voice-channel text, end-of-speech pause, Cursor `auto` fix, Discord audio quirks, hold-line hooks |
| `assistant/house_hold.py` | The 8 second hold line |
| `personalities/watch-officer.md` | Sample soul |
| `config/assistant.yaml.example` | Hermes settings to merge |
| `scripts/install.sh` | Apply the patch and the speech pins |

## License

MIT. Hermes and the Cursor proxy keep their own licenses.
