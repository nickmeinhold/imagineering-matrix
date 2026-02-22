# WhatsApp Relay Bot Deployment Summary

## What worked immediately
- **Relay bot code**: Built, deployed, connected to both rooms, relayed messages between WhatsApp portal ↔ hub room
- **Discord ↔ Telegram**: Already working via superbridge plumbing

## Issues encountered and fixes

### 1. Relay bot couldn't join WhatsApp portal room
- **Cause**: Portal rooms are invite-only, managed by the bridge
- **Fix**: Invited `@relaybot:imagineering.cc` from Element

### 2. WhatsApp bridge rejected relayed messages
- **Cause**: `relay.enabled: false` in mautrix-whatsapp config
- **Fix**: Set `enabled: true`, `admin_only: false` in config, restarted bridge, ran `!wa set-relay` in portal room

### 3. Relay bot password lost
- **Cause**: Random password generated inline on Pi, never captured
- **Fix**: Added `MATRIX_ACCESS_TOKEN` support to the bot as alternative to password auth

### 4. Telegram bridge rejected relay messages — "not allowed to send to portal"
- **Wrong paths tried**:
  - Upgrading bridge permissions to `full` (wasn't the issue — 60% certainty it would help, it didn't)
  - `!tg set-relay` (doesn't exist in Python bridge — 50% certainty, confirmed not available)
  - Inviting Telegram relay ghost to Matrix room (wasn't sufficient — 40% certainty)
  - Restarting bridge to re-sync (didn't help alone — 30% certainty)
- **Root cause**: `portal.has_bot` checks an in-memory `bot_chat` database table. The table was **empty** because the Telegram bot was added to the group *before* the bot_token was configured in the bridge, so the bridge never received the "bot joined" event.
- **Fix**: Inserted `(5274081035, 'chat')` into the `bot_chat` SQLite table, restarted bridge

## What to consider next

1. **Signal relay** — Same approach could work for Signal if plumbing isn't supported. Would need a second relay bot room pair or extend the bot to handle multiple portal rooms.

2. **Bot token privacy mode** — The Telegram bot should have privacy mode disabled via BotFather (`/setprivacy` → Disable). Currently it works for sending but may miss events. **80% certain this matters.**

3. **Persistence of bot_chat record** — If the bridge DB gets rebuilt, the `bot_chat` record will be lost. A more robust fix: remove and re-add the bot to the Telegram group *while the bridge is running* so it detects the join event naturally. **90% certain this would work.**

4. **Commit the deployment changes** — The access token auth support and updated docker-compose haven't been committed to git yet.

5. **Test all directions thoroughly**:
   - [x] WhatsApp → Telegram
   - [x] WhatsApp → Discord
   - [x] Discord → WhatsApp
   - [x] Telegram → WhatsApp
   - [x] Telegram → Discord
   - [x] Discord → Telegram
   - [ ] Matrix (Element) → all platforms
   - [ ] No message loops under sustained traffic
