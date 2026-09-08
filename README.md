# Bot Hosting Platform

Three pieces:

- **server/** — FastAPI backend. Runs on your Ubuntu box. Owns the database,
  Docker orchestration, quotas, and auth.
- **admin_app/** — tkinter admin app. Create users, mint login tokens, set
  quotas.
- **client_app/** — tkinter client app. Log in with a token, write bot code
  (multiple files per bot), set the Discord token, deploy, watch logs.

## 1. Server setup (on the Ubuntu box)

```bash
sudo apt update && sudo apt install -y python3-venv docker.io
sudo usermod -aG docker $USER   # log out/in after this
cd server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # -> ADMIN_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # -> JWT_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> FERNET_KEY
```

Paste those three values into `.env`, then run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For a real deployment, put this behind a systemd service and a reverse proxy
(nginx/caddy) with HTTPS — the apps below talk to whatever URL you give them,
plain `http://` is only fine for local testing.

## 2. Admin app (on your Windows machine)

```
cd admin_app
build_exe.bat
```

Run the resulting `dist\AdminApp.exe`, point it at your server URL, log in
with `ADMIN_PASSWORD`. From there: add users, set their RAM/CPU/storage/bot
quotas, and you'll be shown a one-time login token to hand to that client —
it's never stored or shown again, only its bcrypt hash lives in the database.

## 3. Client app (on the client's machine)

```
cd client_app
build_exe.bat
```

Run `dist\BotClient.exe`, paste in the login token, create a bot, paste in
its Discord bot token (encrypted at rest with Fernet, decrypted only in
memory right before it's injected into the container as an env var), write
code across as many files as needed (`main.py` is the required entrypoint),
hit Deploy, watch the log console.

## How a deploy actually works

Each bot's folder becomes its own Docker build context (`docker build` runs
per bot — you said you won't have more than ~10, so per-client images are
fine here). The container is started with `--memory`, `--cpus`, and a
`pids-limit` matching that user's quota, `restart_policy: no` (a crashed bot
stays stopped, not silently restarting a bad deploy), and the Discord token
is passed as the `DISCORD_TOKEN` env var — client code should read it via
`os.environ["DISCORD_TOKEN"]`, never hardcode it.

## Token security, summarized

- **Client login tokens**: 256-bit random, shown once, only a bcrypt hash is
  stored. Sessions after login are short-lived JWTs.
- **Discord bot tokens**: encrypted at rest (Fernet/AES), decrypted only
  in-process at deploy time.
- **Admin password**: compared with a constant-time check; only used to mint
  an admin JWT, never stored anywhere else.
- File paths are resolved and checked against each bot's own folder before
  every read/write/delete, so one client can't reach another's files (or
  yours) via `../`.

## Known limits / things to harden further if this grows

- Login-token verification loops over all users doing a bcrypt check each —
  fine at your scale (~10 users), would need a lookup-prefix index at scale.
- No rate limiting on `/auth/login` or `/admin/login` — worth adding
  (e.g. `slowapi`) if this is ever reachable from the open internet.
- Docker gives process/resource isolation, not a full security sandbox —
  a determined malicious user could still try to abuse the container (e.g.
  outbound network abuse). Consider `network_mode` restrictions or an
  egress firewall rule per container if that's a concern for your bots.
