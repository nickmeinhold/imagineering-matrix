#!/usr/bin/env bash
# superbridge.sh — Bridge multiple platforms into a single Matrix room
#
# Creates one "hub" room in Matrix and plumbs Discord, Telegram, WhatsApp,
# and Signal into it so messages flow across all platforms.
#
# Usage:
#   ./superbridge.sh create-room          # Step 1: Create the hub room
#   ./superbridge.sh invite-bots          # Step 2: Invite bridge bots + set power levels
#   ./superbridge.sh plumb-discord        # Step 3: Plumb Discord channel
#   ./superbridge.sh plumb-telegram       # Step 4: Plumb Telegram group
#   ./superbridge.sh plumb-whatsapp       # Step 5: Plumb WhatsApp group (experimental)
#   ./superbridge.sh status               # Show current state
#   ./superbridge.sh all                  # Run steps 1-2, then print plumbing instructions
#
# Architecture:
#   WhatsApp group ──► ┌─────────────────┐ ◄── Discord channel
#                      │  Single Matrix  │
#   Signal group  ──►  │     Room        │ ◄── Telegram group
#                      │   (the hub)     │
#                      └─────────────────┘
#                             ▲
#                        Element client
#
# Prerequisites:
#   - Continuwuity + all 4 bridges running (via docker-compose)
#   - Admin user logged in and bridges registered via #admins room
#   - Each bridge already connected to its respective platform account
set -euo pipefail

PI_HOST="nick@raspberrypi"
PI_DIR="~/matrix"
SERVER_NAME="imagineering.cc"
ADMIN_USER="nick"
ROOM_NAME="Imagineering with Claude Code (Superbridge)"
ROOM_ALIAS="superbridge"

# Bridge bot usernames (mautrix defaults)
WHATSAPP_BOT="@whatsappbot:${SERVER_NAME}"
DISCORD_BOT="@discordbot:${SERVER_NAME}"
SIGNAL_BOT="@signalbot:${SERVER_NAME}"
TELEGRAM_BOT="@telegrambot:${SERVER_NAME}"

# State file on the Pi to track superbridge room ID
STATE_FILE="$PI_DIR/.superbridge-state"

# --- Helpers ---

info()  { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
error() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*"; exit 1; }
step()  { printf '\033[1;35m--- %s ---\033[0m\n' "$*"; }

ssh_pi() { ssh "$PI_HOST" "$@"; }

# Get or prompt for admin access token
get_access_token() {
  if [[ -n "${MATRIX_ACCESS_TOKEN:-}" ]]; then
    echo "$MATRIX_ACCESS_TOKEN"
    return
  fi

  # Check if token is saved on Pi
  local saved_token
  saved_token=$(ssh_pi "grep ACCESS_TOKEN $STATE_FILE 2>/dev/null | cut -d= -f2" 2>/dev/null || echo "")
  if [[ -n "$saved_token" ]]; then
    echo "$saved_token"
    return
  fi

  warn "No access token found."
  echo "  Get one by logging in:" >&2
  echo "    curl -s -X POST 'http://localhost:8008/_matrix/client/v3/login' \\" >&2
  echo "      -H 'Content-Type: application/json' \\" >&2
  echo "      -d '{\"type\":\"m.login.password\",\"user\":\"$ADMIN_USER\",\"password\":\"YOUR_PASSWORD\"}'" >&2
  echo >&2
  printf "  Enter access token: " >&2
  read -r token
  echo "$token"

  # Save it for future use
  ssh_pi "echo 'ACCESS_TOKEN=$token' >> $STATE_FILE" 2>/dev/null || true
}

# Make an authenticated Matrix API call on the Pi
matrix_api() {
  local method="$1"
  local endpoint="$2"
  local data="${3:-}"
  local token
  token=$(get_access_token)

  local curl_cmd="curl -sf -X $method 'http://localhost:8008$endpoint' -H 'Authorization: Bearer $token' -H 'Content-Type: application/json'"
  if [[ -n "$data" ]]; then
    curl_cmd="$curl_cmd -d '$data'"
  fi

  ssh_pi "$curl_cmd"
}

# Get saved room ID
get_room_id() {
  ssh_pi "grep ROOM_ID $STATE_FILE 2>/dev/null | cut -d= -f2" 2>/dev/null || echo ""
}

# --- Step 1: Create the hub room ---

create_room() {
  step "Creating superbridge hub room"

  local existing_room
  existing_room=$(get_room_id)
  if [[ -n "$existing_room" ]]; then
    warn "Hub room already exists: $existing_room"
    warn "Delete $STATE_FILE on Pi to start over, or use 'invite-bots' to continue."
    return
  fi

  info "Creating unencrypted room: $ROOM_NAME"

  # Create an unencrypted room with a local alias
  # preset=public_chat makes it joinable; we disable encryption explicitly
  local create_data
  create_data=$(cat <<EOF
{
  "name": "$ROOM_NAME",
  "topic": "Cross-platform relay: Discord + Telegram + WhatsApp + Signal via Matrix",
  "room_alias_name": "$ROOM_ALIAS",
  "preset": "public_chat",
  "visibility": "private",
  "creation_content": {
    "m.federate": false
  },
  "initial_state": [
    {
      "type": "m.room.history_visibility",
      "content": { "history_visibility": "shared" }
    }
  ],
  "power_level_content_override": {
    "events_default": 0,
    "invite": 0,
    "state_default": 50,
    "users_default": 0,
    "users": {
      "@$ADMIN_USER:$SERVER_NAME": 100
    }
  }
}
EOF
)

  local result
  result=$(matrix_api POST "/_matrix/client/v3/createRoom" "$create_data")

  local room_id
  room_id=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['room_id'])")

  if [[ -z "$room_id" ]]; then
    error "Failed to create room. Response: $result"
  fi

  # Save state
  ssh_pi "mkdir -p \$(dirname $STATE_FILE) && echo 'ROOM_ID=$room_id' > $STATE_FILE"

  ok "Hub room created: $room_id"
  ok "Alias: #$ROOM_ALIAS:$SERVER_NAME"
  echo
  echo "  Join from Element: #$ROOM_ALIAS:$SERVER_NAME"
}

# --- Step 2: Invite bridge bots and set power levels ---

invite_bots() {
  step "Inviting bridge bots and setting power levels"

  local room_id
  room_id=$(get_room_id)
  if [[ -z "$room_id" ]]; then
    error "No hub room found. Run 'create-room' first."
  fi

  info "Hub room: $room_id"

  # Invite each bridge bot
  local bots=("$WHATSAPP_BOT" "$DISCORD_BOT" "$SIGNAL_BOT" "$TELEGRAM_BOT")
  for bot in "${bots[@]}"; do
    info "Inviting $bot"
    local invite_data="{\"user_id\": \"$bot\"}"
    if matrix_api POST "/_matrix/client/v3/rooms/$room_id/invite" "$invite_data" >/dev/null 2>&1; then
      ok "Invited $bot"
    else
      warn "Could not invite $bot (may already be in room, or bot user doesn't exist yet)"
    fi
  done

  # Set power levels — bots need PL 50+ to manage ghost users
  info "Setting power levels (bots=50, admin=100)"
  local power_data
  power_data=$(cat <<EOF
{
  "users": {
    "@$ADMIN_USER:$SERVER_NAME": 100,
    "$WHATSAPP_BOT": 50,
    "$DISCORD_BOT": 50,
    "$SIGNAL_BOT": 50,
    "$TELEGRAM_BOT": 50
  },
  "events_default": 0,
  "invite": 0,
  "state_default": 50,
  "users_default": 0,
  "kick": 50,
  "ban": 50,
  "redact": 50
}
EOF
)

  if matrix_api PUT "/_matrix/client/v3/rooms/$room_id/state/m.room.power_levels" "$power_data" >/dev/null 2>&1; then
    ok "Power levels set"
  else
    warn "Could not set power levels — you may need to do this manually from Element"
  fi

  echo
  ok "Bridge bots invited and power levels configured"
  echo "  Verify in Element that all bots have joined the room."
  echo "  If a bot hasn't joined, check that it's running and its appservice is registered."
}

# --- Step 3: Plumb Discord ---

plumb_discord() {
  step "Plumbing Discord into the hub"

  local room_id
  room_id=$(get_room_id)
  if [[ -z "$room_id" ]]; then
    error "No hub room found. Run 'create-room' first."
  fi

  echo
  info "To plumb Discord, run these commands IN THE HUB ROOM from Element:"
  echo
  echo "  Step A — Find the Discord channel ID:"
  echo "    In Discord, enable Developer Mode (Settings > App Settings > Advanced)"
  echo "    Right-click the #imagineering-with-claude-code channel > Copy Channel ID"
  echo
  echo "  Step B — Bridge the channel into this room:"
  echo "    !discord bridge <channel-id>"
  echo
  echo "  Step C — Enable relay mode (so non-Discord users appear with names):"
  echo "    !discord set-relay"
  echo
  echo "  Step D — Verify:"
  echo "    Send a test message from Discord — it should appear in the hub room."
  echo "    Send a message from Element — it should appear in Discord via the relay webhook."
  echo
  warn "Note: If you get 'room not found' errors, the Discord bot may need higher power levels."
}

# --- Step 4: Plumb Telegram ---

plumb_telegram() {
  step "Plumbing Telegram into the hub"

  local room_id
  room_id=$(get_room_id)
  if [[ -z "$room_id" ]]; then
    error "No hub room found. Run 'create-room' first."
  fi

  echo
  info "To plumb Telegram, run these commands IN THE HUB ROOM from Element:"
  echo
  echo "  Step A — Find the Telegram chat ID:"
  echo "    DM @telegrambot with: list"
  echo "    Find 'Imagineering with Claude Code' in the list."
  echo "    Note the chat ID (usually a negative number like -100XXXXXXXXXX for supergroups)."
  echo
  echo "  Step B — Bridge the chat into this room:"
  echo "    !tg bridge <chat-id>"
  echo "    (Include the minus sign, e.g.: !tg bridge -1001234567890)"
  echo
  echo "  Step C — Verify:"
  echo "    Send a message from Telegram — it should appear in the hub room."
  echo "    Send a message from Element — it should appear in the Telegram group."
  echo
  warn "Note: The Telegram bot must be an admin in the Telegram group for relay to work."
}

# --- Step 5: Plumb WhatsApp (experimental) ---

plumb_whatsapp() {
  step "Plumbing WhatsApp into the hub (experimental)"

  local room_id
  room_id=$(get_room_id)
  if [[ -z "$room_id" ]]; then
    error "No hub room found. Run 'create-room' first."
  fi

  echo
  warn "WhatsApp plumbing is experimental and may not work with all mautrix-whatsapp versions."
  echo
  info "To attempt WhatsApp plumbing:"
  echo
  echo "  Step A — Find the WhatsApp group JID:"
  echo "    DM @whatsappbot with: list groups"
  echo "    Find 'Imagineering with Claude Code' and note the JID"
  echo "    (format: XXXXXXXXXXX@g.us)"
  echo
  echo "  Step B — From within the HUB ROOM, tell the bot to bridge here:"
  echo "    !wa open <group-jid>"
  echo "    or (depending on bridge version):"
  echo "    !wa create --room <group-jid>"
  echo
  echo "  Alternative — DM @whatsappbot:"
  echo "    open --here <group-jid>"
  echo "    (You may need to specify the room ID: open --room $room_id <group-jid>)"
  echo
  echo "  Step C — Verify:"
  echo "    Send a message from WhatsApp — it should appear in the hub room."
  echo
  warn "If plumbing fails, WhatsApp will remain as a separate portal room in the Space."
  warn "This is a known limitation of the newer megabridge architecture."
}

# --- Step 6: Signal note ---

signal_note() {
  step "Signal bridge status"

  echo
  warn "mautrix-signal does NOT currently support plumbing into existing rooms."
  echo "  Signal will remain as a separate portal room alongside the superbridge hub."
  echo
  echo "  Workaround options:"
  echo "    1. Keep Signal in the same Space — users see it alongside the hub room"
  echo "    2. Use a Matrix bot to manually relay messages between the Signal portal"
  echo "       room and the hub room (requires custom code)"
  echo "    3. Check for future mautrix-signal updates that may add plumbing support"
  echo
  info "For now, the superbridge covers: Discord + Telegram + Matrix"
  info "WhatsApp is experimental. Signal stays separate."
}

# --- Status ---

show_status() {
  step "Superbridge status"

  local room_id
  room_id=$(get_room_id)

  if [[ -z "$room_id" ]]; then
    warn "No superbridge hub room created yet."
    echo "  Run: ./superbridge.sh create-room"
    return
  fi

  ok "Hub room: $room_id"
  ok "Alias: #$ROOM_ALIAS:$SERVER_NAME"

  echo
  info "Checking room members..."
  local members
  members=$(matrix_api GET "/_matrix/client/v3/rooms/$room_id/joined_members" 2>/dev/null || echo "{}")

  for bot_name in whatsappbot discordbot signalbot telegrambot; do
    local bot_id="@${bot_name}:${SERVER_NAME}"
    if echo "$members" | python3 -c "import sys,json; d=json.load(sys.stdin); assert '$bot_id' in d.get('joined',{})" 2>/dev/null; then
      ok "$bot_id — joined"
    else
      warn "$bot_id — NOT in room"
    fi
  done

  echo
  info "Plumbing status must be checked from Element (room state events)."
  echo "  Look for bridge-specific state events in the room settings."
}

# --- Run all automated steps ---

run_all() {
  create_room
  echo
  invite_bots
  echo
  step "Plumbing instructions"
  echo
  echo "The hub room is ready. Now plumb each bridge from Element."
  echo "Run each command below for step-by-step instructions:"
  echo
  echo "  ./superbridge.sh plumb-discord      # Recommended first"
  echo "  ./superbridge.sh plumb-telegram"
  echo "  ./superbridge.sh plumb-whatsapp      # Experimental"
  echo "  ./superbridge.sh signal-note         # Not supported yet"
  echo
  info "After plumbing, test by sending messages from each platform."
}

# --- Main ---

main() {
  local cmd="${1:-help}"

  case "$cmd" in
    create-room)   create_room ;;
    invite-bots)   invite_bots ;;
    plumb-discord) plumb_discord ;;
    plumb-telegram) plumb_telegram ;;
    plumb-whatsapp) plumb_whatsapp ;;
    signal-note)   signal_note ;;
    status)        show_status ;;
    all)           run_all ;;
    help|--help|-h)
      echo "Usage: $0 <command>"
      echo
      echo "Commands:"
      echo "  create-room       Create the unencrypted hub room on Matrix"
      echo "  invite-bots       Invite all 4 bridge bots and set power levels"
      echo "  plumb-discord     Instructions to bridge Discord channel"
      echo "  plumb-telegram    Instructions to bridge Telegram group"
      echo "  plumb-whatsapp    Instructions to bridge WhatsApp group (experimental)"
      echo "  signal-note       Signal bridge status (not supported for plumbing)"
      echo "  status            Show current superbridge state"
      echo "  all               Create room + invite bots + print plumbing instructions"
      echo
      echo "Environment variables:"
      echo "  MATRIX_ACCESS_TOKEN   Admin access token (prompted if not set)"
      echo
      echo "Architecture:"
      echo "  WhatsApp group ──► ┌─────────────────┐ ◄── Discord channel"
      echo "                     │  Single Matrix  │"
      echo "  Signal group  ──►  │     Room        │ ◄── Telegram group"
      echo "                     │   (the hub)     │"
      echo "                     └─────────────────┘"
      ;;
    *)
      echo "Unknown command: $cmd"
      echo "Run '$0 help' for usage."
      exit 1
      ;;
  esac
}

main "$@"
