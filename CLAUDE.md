# Matrix Homeserver (Continuwuity)

Self-hosted Matrix homeserver using Continuwuity (Rust-based, conduwuit fork) with optional mautrix bridges.

Continuwuity is a Rust-based Matrix homeserver, community fork of conduwuit (archived April 2025). Uses embedded RocksDB — no separate database needed. https://forgejo.ellis.link/continuwuation/continuwuity

## Target Deployment

Raspberry Pi 4 (8 GB).

## Requirements

- Domain pointing to server (server name is permanent — cannot migrate later)
- Ports: 443 (client via reverse proxy), 8448 (federation)
- USB SSD recommended (RocksDB compaction is I/O-heavy, avoid microSD)

## Setup

### 1. Create .env file

```bash
cp .env.example .env
# Edit with your values:
#   MATRIX_SERVER_NAME - your domain (CANNOT be changed after first start)
#   REGISTRATION_TOKEN - secret token for account registration
```

### 2. Start the server

```bash
docker compose up -d
```

No config generation step needed — Continuwuity configures via environment variables.

### 3. Create admin user

Register the first user via the API:

```bash
# From the host
curl -X POST "http://localhost:8008/_matrix/client/v3/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "your-password",
    "auth": {"type": "m.login.registration_token", "token": "your-registration-token"}
  }'
```

Then grant admin via the admin room (join `#admins:yourdomain.com` from Element):

```
!admin users grant-admin @admin:yourdomain.com
```

### 4. Disable registration (optional)

After creating accounts, set in `.env` or docker-compose:

```
CONTINUWUITY_ALLOW_REGISTRATION=false
```

Then `docker compose up -d` to apply.

## Caddy Config

```
matrix.yourdomain.com {
    reverse_proxy /_matrix/* localhost:8008
}

# Federation (optional — can also use .well-known)
yourdomain.com:8448 {
    reverse_proxy localhost:8008
}
```

Or use .well-known delegation (add to main domain):

```
yourdomain.com {
    handle /.well-known/matrix/server {
        respond `{"m.server": "matrix.yourdomain.com:443"}`
    }
    handle /.well-known/matrix/client {
        respond `{"m.homeserver": {"base_url": "https://matrix.yourdomain.com"}}`
    }
}
```

## Bridges

### Enable a bridge

1. Uncomment the bridge in `docker-compose.yml`
2. Generate bridge config:

```bash
# Example for Telegram
docker run --rm -v $(pwd)/telegram_data:/data dock.mau.dev/mautrix/telegram:latest
```

3. Edit config in `telegram_data/config.yaml`:
   - Set homeserver URL to `http://continuwuity:6167`
   - Set bridge permissions
   - Add platform-specific credentials

4. Register the bridge appservice via the admin room (join `#admins:yourdomain.com`):

```
!admin appservices register
<paste contents of registration.yaml>
```

No server restart required.

5. Start the bridge: `docker compose up -d`

### Python vs Go bridges

| Bridge | Language | Extra step needed? |
|--------|----------|--------------------|
| Telegram | Python | Yes — manually register bridge bot account |
| Discord | Go | No |
| Signal | Go | No |
| WhatsApp | Go | No |

### Bridge credentials

- **Telegram**: Requires API ID/hash from https://my.telegram.org
- **Discord**: Login via bot
- **Signal**: Requires linked device
- **WhatsApp**: Requires QR code scan

## Configuration Reference

All config is via `CONTINUWUITY_` environment variables in docker-compose.yml. Key options:

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTINUWUITY_SERVER_NAME` | — | Domain name (permanent, required) |
| `CONTINUWUITY_ALLOW_REGISTRATION` | `false` | Open registration |
| `CONTINUWUITY_REGISTRATION_TOKEN` | — | Token required to register |
| `CONTINUWUITY_ALLOW_FEDERATION` | `true` | Federate with other servers |
| `CONTINUWUITY_TRUSTED_SERVERS` | `[]` | Servers to fetch keys from |
| `CONTINUWUITY_MAX_REQUEST_SIZE` | `20971520` | Max upload size (bytes) |
| `CONTINUWUITY_LOG` | `info` | Log level |

Full reference: https://continuwuity.org/reference/config

## Admin Commands

Administration is done via the `#admins` room, not an HTTP API:

```
!admin users list                          # List users
!admin users grant-admin @user:domain      # Grant admin
!admin appservices list                    # List registered bridges
!admin appservices register                # Register a bridge
!admin rooms list                          # List rooms
```

## Clients

- **Element Web**: Self-host or use app.element.io
- **Element X**: Next-gen client (Sliding Sync built into Continuwuity)
- **FluffyChat**: Good mobile alternative

## RAM Usage (typical)

| Component | RAM |
|-----------|-----|
| Continuwuity | 50-150 MB |
| Each mautrix bridge | 50-100 MB |
| Relay bot | ~30 MB |
| **Total (4 bridges + relay)** | ~330-580 MB |

## Backup

```bash
# Stop the server first for a clean backup
docker compose stop continuwuity

# Copy the data volume
docker run --rm -v matrix_continuwuity_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/continuwuity_backup.tar.gz -C /data .

docker compose start continuwuity
```

## Superbridge (Cross-Platform Relay)

Bridges all platforms into a **single Matrix room** so messages flow everywhere.

```
WhatsApp group ──► ┌─────────────────┐ ◄── Discord channel
                   │  Single Matrix  │
Signal group  ──►  │     Room        │ ◄── Telegram group
                   │   (the hub)     │
                   └─────────────────┘
                          ▲
                     Element client
```

### Setup

```bash
# Step 1-2: Create hub room + invite bots (automated)
./superbridge.sh all

# Step 3-5: Plumb each bridge (interactive, from Element)
./superbridge.sh plumb-discord       # !discord bridge <channel-id>
./superbridge.sh plumb-telegram      # !tg bridge <chat-id>
./superbridge.sh plumb-whatsapp      # Experimental
```

### How plumbing works

- **Discord**: `!discord bridge <channel-id>` in the hub room, then `!discord set-relay` for webhook-based name/avatar relay.
- **Telegram**: `!tg bridge -<chat-id>` in the hub room. Bot must be admin in the Telegram group.
- **WhatsApp**: Cannot be plumbed (megabridge limitation). Uses the relay bot instead — see [Multi-Portal Relay Bot](#multi-portal-relay-bot) below.
- **Signal**: Cannot be plumbed (megabridge limitation). Uses the relay bot instead — see [Multi-Portal Relay Bot](#multi-portal-relay-bot) below.

### Relay mode

Users who've logged into a bridge get full puppeting (messages appear as them). Non-puppeted users' messages go through the bridge bot as `"Name: message"` via relay mode.

### Troubleshooting

- **Bot won't join**: Check appservice registration (`!admin appservices list`) and that the bot user exists.
- **Message loops**: Each bridge only relays messages from non-native users. If you see echoes, check that relay mode is configured correctly.
- **Power levels**: Bridge bots need PL 50+ in the hub room. Use `./superbridge.sh invite-bots` or set manually in Element room settings.
- **Continuwuity bug**: Original Conduit had a bug where puppet users couldn't join rooms. Continuwuity may have fixed this — if plumbing fails, check Continuwuity issue tracker.
- **State file**: Superbridge state (room ID, access token) stored on Pi at `~/matrix/.superbridge-state`.

### Multi-Portal Relay Bot

Megabridge-based mautrix bridges (WhatsApp, Signal) can't plumb a group into an existing room. The relay bot (`relay/`) bridges the gap by copying messages between one or more portal rooms and the hub room with sender attribution.

```
WhatsApp portal room ◄──┐
                         ├──relay bot──► Hub room (Discord + Telegram + Matrix)
Signal portal room  ◄───┘
```

#### Configuration

Two formats are supported:

```bash
# Multi-portal (recommended): relay multiple megabridge rooms
PORTAL_ROOMS=!whatsapp-room:yourdomain.com=WhatsApp,!signal-room:yourdomain.com=Signal

# Legacy single-portal: still works for backward compatibility
WHATSAPP_ROOM_ID=!whatsapp-room:yourdomain.com
```

`PORTAL_ROOMS` takes precedence when set. Each entry is `!room_id:domain=Label` separated by commas. The label (e.g. `WhatsApp`, `Signal`) is required and appears in relay attribution.

#### Setup

1. Register a dedicated Matrix account for the bot:

```bash
curl -X POST "http://localhost:8008/_matrix/client/v3/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "relaybot",
    "password": "your-password",
    "auth": {"type": "m.login.registration_token", "token": "your-token"}
  }'
```

2. Add the relay bot env vars to `.env`:

```bash
RELAY_BOT_USER=@relaybot:yourdomain.com
RELAY_BOT_PASSWORD=your-relay-bot-password
PORTAL_ROOMS=!whatsapp-portal-room-id:yourdomain.com=WhatsApp,!signal-portal-room-id:yourdomain.com=Signal
HUB_ROOM_ID=!superbridge-hub-room-id:yourdomain.com
```

Portal room IDs are the portal rooms created by mautrix bridges (find via Element devtools). The hub room ID is stored in `.superbridge-state` on the Pi.

3. Start the bot:

```bash
docker compose up -d relay-bot
```

#### How it works

- Listens for messages in all portal rooms and the hub room via `matrix-nio` (async Matrix client)
- Portal room → hub: prefixed with `**Name (Label):**` using the portal's configured label
- Hub → all portal rooms: fans out to every portal, prefixed with `**Name (Platform):**` where platform is inferred from the sender's MXID (e.g. Discord, Telegram, or Matrix)
- Fan-out is resilient: failure to send to one portal does not block delivery to others
- Loop prevention (three layers):
  1. Ignores its own messages
  2. Ignores bridge bots and puppet users (`@whatsappbot:`, `@_discord_*:`, etc.)
  3. Ignores messages that already have relay attribution (`**Name (Platform):**` or `Name: message`)

#### Files

| File | Purpose |
|------|---------|
| `relay/relay_bot.py` | Bot logic (~250 lines) |
| `relay/requirements.txt` | `matrix-nio` dependency |
| `relay/Dockerfile` | `python:3.12-slim` container |

### Verification

1. Send from Discord — appears in Matrix, Telegram, WhatsApp, Signal
2. Send from Telegram — appears in Discord, Matrix, WhatsApp, Signal
3. Send from WhatsApp — appears in hub room, Discord, Telegram, Signal
4. Send from Signal — appears in hub room, Discord, Telegram, WhatsApp
5. Send from Element — appears on all bridged platforms
6. Messages show sender attribution on all platforms
7. No message loops or duplicate messages

## Limitations vs Synapse

- No SSO/OIDC support
- No Synapse Admin API (uses admin room commands instead)
- No migration from existing Synapse database (start fresh; federation recovers room history)
- Cannot use matrix-docker-ansible-deploy
- Less third-party tooling and management UIs
