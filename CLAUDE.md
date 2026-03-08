# Matrix Homeserver (Continuwuity)

Self-hosted Matrix homeserver using Continuwuity (Rust-based, conduwuit fork) with optional mautrix bridges.

Continuwuity is a Rust-based Matrix homeserver, community fork of conduwuit (archived April 2025). Uses embedded RocksDB — no separate database needed. https://forgejo.ellis.link/continuwuation/continuwuity

## Target Deployment

GCP e2-medium (`34.40.229.206`) — colocated with other imagineering.cc services.
Previously ran on Raspberry Pi 4 (8 GB), migrated to GCP for public HTTPS and reliability.

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

## Deployment

Deployed via the `imagineering-infra` repo's deploy script. Secrets are SOPS-encrypted in `imagineering-infra/matrix/secrets.yaml`.

**GCP instance:** `34.40.229.206` (nick@)
**Remote path:** `~/apps/matrix/`
**Public URL:** `https://matrix.imagineering.cc`

### Deploy a config or code change

```bash
# From imagineering-infra repo
./scripts/deploy-to.sh 34.40.229.206 matrix
```

This decrypts secrets, generates `.env`, rsyncs files (including relay bot source from this repo), builds the relay bot container, and restarts services.

### Deploy with volume reset (e.g. relay puppet cleanup)

When relay puppets need re-creation (stale profiles, corrupt DB), clear the data volume:

```bash
ssh nick@34.40.229.206 "cd ~/apps/matrix && docker compose rm -f relay-bot && docker volume rm matrix_relay_data && docker compose up -d"
```

The `rm -f` is required before `volume rm` — Docker won't remove a volume still attached to a stopped container.

## Caddy Config

Managed in `imagineering-infra/caddy/Caddyfile`:

```
matrix.imagineering.cc {
    reverse_proxy localhost:8008
}
```

Caddy provides automatic HTTPS via Let's Encrypt. Federation is currently disabled (`CONTINUWUITY_ALLOW_FEDERATION=false`).

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
| `CONTINUWUITY_NEW_USER_DISPLAYNAME_SUFFIX` | `🏳️‍⚧️` | Text appended to display name on registration (set `""` to disable) |
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
- **State file**: Superbridge state (room ID, access token) stored on GCP at `~/apps/matrix/.superbridge-state`.

### Relay Appservice (Puppet-Based)

Megabridge-based mautrix bridges (WhatsApp, Signal) can't plumb a group into an existing room. The relay appservice (`relay/`) bridges the gap using **puppet users** — messages appear as the actual sender with their name and avatar, instead of a single bot with text attribution.

```
WhatsApp portal room ◄──┐
                         ├──relay appservice──► Hub room (Discord + Telegram + Matrix)
Signal portal room  ◄───┘
                    (puppet users relay with sender identity)
```

Features:
- **Puppet users**: Each sender gets a dedicated Matrix identity (`@_relay_{platform}_{hash}:domain`)
- **Display names**: Just the sender's name (no platform suffix)
- **Reply threading**: `m.in_reply_to` references preserved across rooms via SQLite event map
- **Reaction relay**: Emoji reactions forwarded to the correct message in all rooms
- **Cross-relay**: Portal rooms can see each other (WhatsApp ↔ Signal)

#### Configuration

```bash
# In .env:
RELAY_AS_TOKEN=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
RELAY_HS_TOKEN=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
PORTAL_ROOMS=!whatsapp-room:yourdomain.com=WhatsApp,!signal-room:yourdomain.com=Signal
HUB_ROOM_ID=!superbridge-hub-room-id:yourdomain.com
```

Each `PORTAL_ROOMS` entry is `!room_id:domain=Label` separated by commas.

#### Setup

1. Generate tokens:

```bash
python -c "import secrets; print(secrets.token_hex(32))"  # run twice: AS + HS
```

2. Edit `relay/registration.yaml` — replace `CHANGE_ME_*` placeholders with real domain and tokens.

3. Register the appservice via the admin room:

```
!admin appservices register
<paste contents of relay/registration.yaml>
```

4. Add tokens and room IDs to `.env` (see `.env.example`).

5. Start:

```bash
docker compose up -d relay-bot
```

#### How it works

- Runs as a Matrix **appservice** receiving events via HTTP push (port 8009)
- Uses `mautrix-python` `IntentAPI` to send messages as puppet users
- Portal → hub + other portals: puppet sends with sender's display name
- Hub → all portals: fan-out with per-sender puppet identity
- Replies: source→target event ID mappings stored in SQLite (WAL mode); `m.in_reply_to` references translated to target room's event IDs
- Reactions: `m.reaction` events relayed via puppet intents to the mapped event in each target room
- Loop prevention (three layers):
  1. Ignores bot's own messages and relay puppet users (`@_relay_*:`)
  2. Portal rooms: ignores bridge bots; hub room: ignores bridge bots + puppets
  3. Ignores messages with existing attribution patterns
- Fan-out is resilient: failure to one target does not block others
- Background cleanup: event mappings older than 30 days are pruned every 6 hours

#### Files

| File | Purpose |
|------|---------|
| `relay/appservice/__main__.py` | Entry point: creates AppService, wires handler, starts HTTP server |
| `relay/appservice/config.py` | `RelayConfig` dataclass from env vars |
| `relay/appservice/handler.py` | Core relay logic: message routing, reply/reaction relay |
| `relay/appservice/puppet.py` | Puppet user management: deterministic MXIDs, profile sync |
| `relay/appservice/event_map.py` | SQLite event ID mapping for replies and reactions |
| `relay/appservice/loop_prevention.py` | Three-layer loop prevention (pure functions) |
| `relay/registration.yaml` | Appservice registration template for Continuwuity |
| `relay/requirements.txt` | `mautrix`, `aiosqlite` |
| `relay/Dockerfile` | `python:3.12-slim` container with `/data` volume |

#### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `RELAY_AS_TOKEN` | Yes | Appservice token (matches `registration.yaml`) |
| `RELAY_HS_TOKEN` | Yes | Homeserver token (matches `registration.yaml`) |
| `PORTAL_ROOMS` | Yes | Portal rooms: `!room:domain=Label,...` |
| `HUB_ROOM_ID` | Yes | Hub room ID |
| `RELAY_BOT_LOCALPART` | No | Bot localpart (default: `relay-bot`) |
| `RELAY_DB_PATH` | No | SQLite path (default: `/data/relay.db`) |
| `RELAY_DOUBLE_PUPPETS` | No | Double puppet mapping (see below) |
| `RELAY_LOG_LEVEL` | No | Log level (default: `INFO`, set `DEBUG` to troubleshoot) |

`RELAY_HOMESERVER_URL` and `RELAY_DOMAIN` are set in `docker-compose.yml` from `MATRIX_SERVER_NAME`.

#### Double puppet mapping

When a bridge-logged-in user sends from a bridged platform (e.g. Signal), the bridge delivers
the message as their real Matrix account (`@nick:domain`), not a bridge puppet. The relay bot
would then use their Matrix profile (wrong name/avatar) instead of their platform-specific identity.

`RELAY_DOUBLE_PUPPETS` maps these users to their platform puppet MXIDs so the relay bot
looks up the correct name and avatar per platform:

```bash
# Format: user=puppet1,puppet2;user2=puppet3  (localparts, semicolon-separated per user)
RELAY_DOUBLE_PUPPETS=nick=signal_66eda24c-...,whatsapp_61447591141
```

Find puppet IDs from bridge databases:
- Signal: `SELECT mxid, signal_id FROM user_login;` → `signal_<uuid>`
- WhatsApp: `SELECT mxid, phone FROM user_login;` → `whatsapp_<phone>`

### Verification

1. Send from Discord — appears in Matrix, Telegram, WhatsApp, Signal
2. Send from Telegram — appears in Discord, Matrix, WhatsApp, Signal
3. Send from WhatsApp — appears in hub as puppet user "Alice" (with name), not `**Alice (WhatsApp):**`
4. Reply to a message from Element — reply thread preserved in WhatsApp/Signal portals
5. React with emoji from Discord — reaction appears on correct message in all rooms
6. Send from Element — appears on all bridged platforms
7. No message loops or duplicate messages

## Next Steps

Superbridge is fully operational (2026-03-06). All 5 platforms connected bidirectionally. Remaining work:

- [x] **Test more scenarios** — replies across platforms, reactions, media (images/files/voice)
  - [x] Replies: WhatsApp ✅, Discord ✅, Signal (source) ✅, Telegram ❌ (bridge limitation)
  - [x] Reactions: Discord→Telegram ✅ (direct), Discord→Signal/WhatsApp ❌ (needs appservice re-registration)
  - [ ] Media: images, files, voice messages (untested)
- [ ] **Fix reactions to Signal/WhatsApp** — re-register relay appservice with `@nick` in namespace (paste in `#admins` room)
- [ ] **Invite real users** — test with multiple people, verify display names and avatars look right for everyone
- [x] **Polish** — display names, avatars, formatting quirks
  - [x] Telegram relaybot: removed distinguisher squares, bot name set to `•`, avatar set via BotFather
  - [x] Discord relay avatars: exposed bridge port 29334, added Caddy `/mautrix-discord/*` route for avatar proxy
- [x] **Document the working setup** — `JOINING.md` for Meetup members (fill in invite links before sharing)

## Limitations vs Synapse

- No SSO/OIDC support
- No Synapse Admin API (uses admin room commands instead)
- No migration from existing Synapse database (start fresh; federation recovers room history)
- Cannot use matrix-docker-ansible-deploy
- Less third-party tooling and management UIs
