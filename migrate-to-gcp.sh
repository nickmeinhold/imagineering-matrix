#!/usr/bin/env bash
# migrate-to-gcp.sh — One-time migration of Matrix data from Pi to GCP
#
# Prerequisites:
#   - SSH access to Pi as 'pi' and GCP as 'gcp' (or the IP)
#   - Matrix stack deployed on GCP (volumes created but empty)
#   - Bridge configs backed up to bridge-configs/
#
# Usage:
#   ./migrate-to-gcp.sh backup-configs   # Step 0: Back up bridge configs from Pi
#   ./migrate-to-gcp.sh export           # Step 1: Stop Pi, export volumes
#   ./migrate-to-gcp.sh transfer <gcp>   # Step 2: Transfer tarballs to GCP
#   ./migrate-to-gcp.sh import <gcp>     # Step 3: Import volumes on GCP
#   ./migrate-to-gcp.sh patch <gcp>      # Step 4: Patch bridge configs for public URL
#   ./migrate-to-gcp.sh verify <gcp>     # Step 5: Verify the deployment
#   ./migrate-to-gcp.sh all <gcp>        # Run all steps (except backup-configs)

set -euo pipefail

PI_HOST="pi"
GCP_IP="${2:-34.40.229.206}"
GCP_HOST="nick@$GCP_IP"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VOLUMES=(continuwuity_data telegram_data discord_data signal_data whatsapp_data relay_data)

info()  { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
error() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*"; exit 1; }

backup_configs() {
    info "Backing up bridge configs from Pi"
    mkdir -p "$SCRIPT_DIR/bridge-configs"
    for svc in telegram discord signal whatsapp; do
        info "  Extracting $svc config..."
        ssh "$PI_HOST" "docker cp matrix-mautrix-${svc}-1:/data/config.yaml /tmp/${svc}-config.yaml" || {
            warn "  Could not extract $svc config (container may not exist)"
            continue
        }
        scp "$PI_HOST:/tmp/${svc}-config.yaml" "$SCRIPT_DIR/bridge-configs/"
        ok "  $svc config saved"
    done
    ok "Bridge configs backed up to bridge-configs/"
}

export_volumes() {
    info "Stopping Matrix stack on Pi"
    ssh "$PI_HOST" "cd ~/matrix && docker compose down"
    ok "Pi stack stopped"

    info "Exporting data volumes as tarballs"
    for vol in "${VOLUMES[@]}"; do
        info "  Exporting $vol..."
        ssh "$PI_HOST" "docker run --rm -v matrix_${vol}:/data -v /tmp:/backup alpine \
            tar czf /backup/${vol}.tar.gz -C /data ."
        ok "  $vol exported"
    done
    ok "All volumes exported to Pi:/tmp/"
}

transfer_volumes() {
    info "Transferring volume tarballs from Pi to GCP ($GCP_HOST)"
    for vol in "${VOLUMES[@]}"; do
        info "  Transferring $vol..."
        # Pi → local → GCP (two hops since Pi and GCP may not have direct SSH)
        scp "$PI_HOST:/tmp/${vol}.tar.gz" "/tmp/${vol}.tar.gz"
        scp "/tmp/${vol}.tar.gz" "$GCP_HOST:/tmp/${vol}.tar.gz"
        rm -f "/tmp/${vol}.tar.gz"
        ok "  $vol transferred"
    done
    ok "All volumes transferred to GCP"
}

import_volumes() {
    info "Creating containers (to initialize volumes) on GCP"
    ssh "$GCP_HOST" "cd ~/apps/matrix && docker compose up -d --no-start" || true

    info "Importing data volumes on GCP"
    for vol in "${VOLUMES[@]}"; do
        info "  Importing $vol..."
        ssh "$GCP_HOST" "docker run --rm -v matrix_${vol}:/data -v /tmp:/backup alpine \
            sh -c 'cd /data && tar xzf /backup/${vol}.tar.gz'"
        ok "  $vol imported"
    done

    # Clean up tarballs on GCP
    ssh "$GCP_HOST" "rm -f /tmp/*_data.tar.gz"
    ok "All volumes imported on GCP"
}

patch_configs() {
    info "Patching Discord bridge config for public URL"
    ssh "$GCP_HOST" "docker run --rm -v matrix_discord_data:/data alpine \
        sed -i 's|public_address:.*|public_address: https://matrix.imagineering.cc|' /data/config.yaml" && \
        ok "Discord public_address updated" || \
        warn "Could not patch Discord config (may need manual update)"
}

verify_deployment() {
    info "Starting Matrix stack on GCP"
    ssh "$GCP_HOST" "cd ~/apps/matrix && docker compose up -d"

    info "Waiting for homeserver..."
    for i in $(seq 1 30); do
        if ssh "$GCP_HOST" "curl -sf http://localhost:8008/_matrix/client/versions" >/dev/null 2>&1; then
            ok "Continuwuity is healthy"
            break
        fi
        if [ "$i" -eq 30 ]; then
            error "Continuwuity failed to start within 60 seconds"
        fi
        sleep 2
    done

    info "Container status:"
    ssh "$GCP_HOST" "cd ~/apps/matrix && docker compose ps --format 'table {{.Name}}\t{{.Status}}'"

    echo
    info "Verification checklist:"
    echo "  1. curl https://matrix.imagineering.cc/_matrix/client/versions"
    echo "  2. Connect Element client to matrix.imagineering.cc"
    echo "  3. Check bridge logs: ssh $GCP_HOST 'cd ~/apps/matrix && docker compose logs --tail 5'"
    echo "  4. Send test messages from each platform"
    echo "  5. Verify Discord avatars load correctly"
    echo
    warn "If everything works, the Pi can be decommissioned."
    warn "Pi data is untouched — restart with: ssh $PI_HOST 'cd ~/matrix && docker compose up -d'"
}

case "${1:-help}" in
    backup-configs)
        backup_configs
        ;;
    export)
        export_volumes
        ;;
    transfer)
        transfer_volumes
        ;;
    import)
        import_volumes
        ;;
    patch)
        patch_configs
        ;;
    verify)
        verify_deployment
        ;;
    all)
        export_volumes
        transfer_volumes
        import_volumes
        patch_configs
        verify_deployment
        ;;
    *)
        echo "Usage: $0 <command> [gcp-ip]"
        echo ""
        echo "Commands:"
        echo "  backup-configs   Back up bridge configs from Pi"
        echo "  export           Stop Pi and export volumes"
        echo "  transfer <gcp>   Transfer tarballs Pi → GCP"
        echo "  import <gcp>     Import volumes on GCP"
        echo "  patch <gcp>      Patch bridge configs for public URL"
        echo "  verify <gcp>     Start stack and verify"
        echo "  all <gcp>        Run export → transfer → import → patch → verify"
        echo ""
        echo "Default GCP IP: 34.40.229.206"
        exit 1
        ;;
esac
