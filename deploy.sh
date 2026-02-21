#!/usr/bin/env bash
# deploy.sh — Deploy Continuwuity + 4 mautrix bridges to Raspberry Pi 4
#
# Usage:
#   ./deploy.sh              # Full deploy (copy files, start services)
#   ./deploy.sh configure    # Only configure bridges (after initial start)
#
# Prerequisites:
#   - SSH access to Pi as 'nick@raspberrypi'
#   - Docker + Compose on the Pi
#   - Tailscale on the Pi
set -euo pipefail

PI_HOST="nick@raspberrypi"
PI_DIR="~/matrix"
SERVER_NAME="imagineering.cc"
ADMIN_USER="nick"
ADMIN_PASSWORD=""  # Set interactively
HOMESERVER_URL="http://continuwuity:6167"

# --- Helpers ---

info()  { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
error() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*"; exit 1; }

ssh_pi() { ssh "$PI_HOST" "$@"; }
pi_compose() { ssh_pi "cd $PI_DIR && docker compose $*"; }

# --- Step 1: Copy files to Pi ---

copy_files() {
  info "Copying files to Pi ($PI_HOST:$PI_DIR)"

  ssh_pi "mkdir -p $PI_DIR"
  scp docker-compose.yml "$PI_HOST:$PI_DIR/docker-compose.yml"
  scp .env.example "$PI_HOST:$PI_DIR/.env.example"
  ok "Files copied"

  # Generate .env if it doesn't exist
  if ssh_pi "test -f $PI_DIR/.env"; then
    warn ".env already exists on Pi — skipping generation"
  else
    info "Generating .env on Pi"
    REGISTRATION_TOKEN=$(openssl rand -hex 24)
    ssh_pi "cat > $PI_DIR/.env" <<EOF
MATRIX_SERVER_NAME=$SERVER_NAME
REGISTRATION_TOKEN=$REGISTRATION_TOKEN
EOF
    ok ".env created (token: $REGISTRATION_TOKEN)"
    warn "Save this registration token — you'll need it to create accounts"
  fi
}

# --- Step 2: Start Continuwuity ---

start_continuwuity() {
  info "Pulling Continuwuity image"
  pi_compose "pull continuwuity"
  ok "Image pulled"

  info "Starting Continuwuity"
  pi_compose "up -d continuwuity"

  info "Waiting for health check..."
  for i in $(seq 1 30); do
    if ssh_pi "curl -sf http://localhost:8008/_matrix/client/versions" >/dev/null 2>&1; then
      ok "Continuwuity is healthy"
      return
    fi
    sleep 2
  done
  error "Continuwuity failed to start within 60 seconds"
}

# --- Step 3: Register admin user ---

register_admin() {
  info "Registering admin user: @$ADMIN_USER:$SERVER_NAME"

  # Read password securely
  if [[ -z "$ADMIN_PASSWORD" ]]; then
    printf "  Enter password for @%s:%s: " "$ADMIN_USER" "$SERVER_NAME"
    read -rs ADMIN_PASSWORD
    echo
  fi

  # Read registration token from Pi
  REG_TOKEN=$(ssh_pi "grep REGISTRATION_TOKEN $PI_DIR/.env | cut -d= -f2")

  # First call gets the session
  SESSION=$(ssh_pi "curl -s -X POST 'http://localhost:8008/_matrix/client/v3/register' \
    -H 'Content-Type: application/json' \
    -d '{\"username\": \"$ADMIN_USER\", \"password\": \"dummy\"}'" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('session',''))")

  # Second call with auth
  RESULT=$(ssh_pi "curl -s -X POST 'http://localhost:8008/_matrix/client/v3/register' \
    -H 'Content-Type: application/json' \
    -d '{
      \"username\": \"$ADMIN_USER\",
      \"password\": \"$ADMIN_PASSWORD\",
      \"auth\": {
        \"type\": \"m.login.registration_token\",
        \"token\": \"$REG_TOKEN\",
        \"session\": \"$SESSION\"
      }
    }'")

  if echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'user_id' in d" 2>/dev/null; then
    ok "Registered @$ADMIN_USER:$SERVER_NAME"
  else
    warn "Registration response: $RESULT"
    warn "User may already exist — continuing"
  fi
}

# --- Step 4: Configure bridges ---

configure_bridges() {
  local bridges=("whatsapp" "discord" "signal" "telegram")

  for bridge in "${bridges[@]}"; do
    info "Configuring mautrix-$bridge"
    local volume="${bridge}_data"
    local service="mautrix-$bridge"

    # Generate default config by running the bridge once
    # The bridge will exit after generating config if no valid config exists
    info "  Generating default config for $bridge..."
    pi_compose "run --rm $service" 2>/dev/null || true
    sleep 2

    # Get the volume mount path
    local volume_path
    volume_path=$(ssh_pi "docker volume inspect matrix_${volume} --format '{{.Mountpoint}}'" 2>/dev/null || echo "")
    if [[ -z "$volume_path" ]]; then
      volume_path=$(ssh_pi "docker volume inspect ${volume} --format '{{.Mountpoint}}'" 2>/dev/null || echo "")
    fi

    if [[ -z "$volume_path" ]]; then
      warn "  Could not find volume for $bridge — skipping config"
      continue
    fi

    # Patch config.yaml: homeserver address and server name
    info "  Patching config.yaml..."
    ssh_pi "sudo python3 -c \"
import yaml, sys
config_path = '$volume_path/config.yaml'
with open(config_path) as f:
    config = yaml.safe_load(f)

# Set homeserver
config.setdefault('homeserver', {})
config['homeserver']['address'] = '$HOMESERVER_URL'
config['homeserver']['domain'] = '$SERVER_NAME'

# Set bridge permissions — allow admin user full control
if 'bridge' in config:
    config['bridge']['permissions'] = {
        '@$ADMIN_USER:$SERVER_NAME': 'admin',
        '$SERVER_NAME': 'user'
    }

with open(config_path, 'w') as f:
    yaml.dump(config, f, default_flow_style=False)

print('Config patched')
\"" || {
      warn "  python3+yaml not available on Pi — patching with sed"
      ssh_pi "sudo sed -i \
        -e 's|address:.*|address: $HOMESERVER_URL|' \
        -e 's|domain:.*|domain: $SERVER_NAME|' \
        '$volume_path/config.yaml'"
    }

    # Handle Telegram-specific config
    if [[ "$bridge" == "telegram" ]]; then
      warn "  Telegram requires API credentials from https://my.telegram.org"
      warn "  Edit $volume_path/config.yaml on the Pi to set:"
      warn "    telegram.api_id and telegram.api_hash"
    fi

    ok "  $bridge configured"
  done
}

# --- Step 5: Start bridges ---

start_bridges() {
  info "Starting all bridge services"
  pi_compose "up -d"

  info "Waiting for services..."
  sleep 10

  pi_compose "ps"
  ok "All services started"
  echo
  warn "Next steps to complete bridge setup:"
  echo "  1. Join #admins:$SERVER_NAME from your Matrix client"
  echo "  2. For each bridge, register its appservice:"
  echo "     !admin appservices register"
  echo "     <paste contents of registration.yaml from each bridge's data volume>"
  echo
  echo "  Bridge registration files:"
  for bridge in whatsapp discord signal telegram; do
    echo "     ssh $PI_HOST \"sudo cat \$(docker volume inspect matrix_${bridge}_data --format '{{.Mountpoint}}')/registration.yaml\""
  done
  echo
  echo "  3. Telegram: Set API ID/hash, then register the bridge bot:"
  echo "     ssh $PI_HOST \"cd $PI_DIR && docker compose exec mautrix-telegram python -m mautrix_telegram -r\""
}

# --- Step 6: Set up Tailscale Serve ---

setup_tailscale() {
  info "Setting up Tailscale Serve on port 8008"
  ssh_pi "sudo tailscale serve --bg 8008"
  ok "Tailscale Serve active"

  local ts_url
  ts_url=$(ssh_pi "tailscale status --json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
dns = data.get('Self', {}).get('DNSName', '').rstrip('.')
print(f'https://{dns}')
")
  echo
  ok "Matrix homeserver available at: $ts_url"
  echo "  Use this as your homeserver URL in Element/FluffyChat"
}

# --- Step 7: Verify ---

verify() {
  info "Verifying deployment"

  # Check Matrix versions endpoint
  if ssh_pi "curl -sf http://localhost:8008/_matrix/client/versions" | python3 -c "import sys,json; v=json.load(sys.stdin); print(f'  Matrix versions: {v[\"versions\"]}')" 2>/dev/null; then
    ok "Matrix API responding"
  else
    error "Matrix API not responding"
  fi

  # Check containers
  echo
  ssh_pi "cd $PI_DIR && docker compose ps --format 'table {{.Name}}\t{{.Status}}'"
  echo
  ok "Deployment verification complete"
}

# --- Main ---

main() {
  local cmd="${1:-deploy}"

  case "$cmd" in
    deploy)
      copy_files
      start_continuwuity
      register_admin
      configure_bridges
      start_bridges
      setup_tailscale
      verify
      ;;
    configure)
      configure_bridges
      start_bridges
      ;;
    verify)
      verify
      ;;
    tailscale)
      setup_tailscale
      ;;
    superbridge)
      info "Running superbridge setup"
      local script_dir
      script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
      "${script_dir}/superbridge.sh" "${@:2}"
      ;;
    *)
      echo "Usage: $0 [deploy|configure|verify|tailscale|superbridge]"
      exit 1
      ;;
  esac
}

main "$@"
