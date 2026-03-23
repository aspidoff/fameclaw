#!/bin/bash
# FameClaw Gmail Setup — Store credentials in ~/.config/fameclaw/gmail.json
# Same pattern as OpenClaw: plain JSON, chmod 600
#
# Usage:
#   ./gmail_auth.sh setup    — Interactive Gmail setup
#   ./gmail_auth.sh test     — Test stored credentials
#   ./gmail_auth.sh status   — Show connection status
#   ./gmail_auth.sh remove   — Remove stored credentials

set -euo pipefail

CREDS_DIR="${HOME}/.config/fameclaw"
CREDS_FILE="$CREDS_DIR/gmail.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

case "${1:-help}" in
  setup)
    echo "=== FameClaw Gmail Setup ==="
    echo ""
    echo "You need a Gmail App Password:"
    echo "  1. myaccount.google.com → Security → 2-Step Verification → ON"
    echo "  2. Security → App passwords → Generate"
    echo "  3. Copy the 16-character password"
    echo ""

    printf "Gmail login (the account you sign in with): "
    read -r EMAIL
    printf "App password: "
    read -rs PASSWORD
    echo ""
    printf "Send-as email (alias, or Enter to use login): "
    read -r FROM_EMAIL
    FROM_EMAIL="${FROM_EMAIL:-$EMAIL}"
    printf "Display name (e.g. 'Alex from MyBrand'): "
    read -r DISPLAY_NAME
    printf "Provider (gmail/outlook/icloud/yahoo/zoho/fastmail, or Enter for auto-detect): "
    read -r PROVIDER

    PASSWORD=$(echo "$PASSWORD" | tr -d ' ')

    mkdir -p "$CREDS_DIR"
    if [ -n "$PROVIDER" ]; then
      cat > "$CREDS_FILE" << EOF
{
  "email": "$EMAIL",
  "app_password": "$PASSWORD",
  "from_email": "$FROM_EMAIL",
  "display_name": "$DISPLAY_NAME",
  "provider": "$PROVIDER"
}
EOF
    else
      cat > "$CREDS_FILE" << EOF
{
  "email": "$EMAIL",
  "app_password": "$PASSWORD",
  "from_email": "$FROM_EMAIL",
  "display_name": "$DISPLAY_NAME"
}
EOF
    fi
    chmod 600 "$CREDS_FILE"
    echo ""
    echo "✅ Saved to $CREDS_FILE (mode 600)"
    echo ""
    echo "Testing connection..."
    python3 "$SCRIPT_DIR/gmail.py" test --creds "$CREDS_FILE"
    ;;

  test)
    if [ ! -f "$CREDS_FILE" ]; then
      echo "❌ No credentials found. Run: $0 setup"
      exit 1
    fi
    echo "Testing Gmail connection..."
    python3 "$SCRIPT_DIR/gmail.py" test --creds "$CREDS_FILE"
    ;;

  status)
    if [ ! -f "$CREDS_FILE" ]; then
      echo "Gmail: not configured"
      echo "Run: $0 setup"
    else
      EMAIL=$(python3 -c "import json; print(json.load(open('$CREDS_FILE'))['email'])" 2>/dev/null)
      echo "Gmail: $EMAIL"
      echo "Creds: $CREDS_FILE"
      echo "Perms: $(stat -f %Sp "$CREDS_FILE" 2>/dev/null || stat -c %a "$CREDS_FILE" 2>/dev/null)"
    fi
    ;;

  remove)
    rm -f "$CREDS_FILE"
    echo "✅ Credentials removed"
    ;;

  path)
    # Output creds path for other scripts
    echo "$CREDS_FILE"
    ;;

  help|*)
    echo "FameClaw Gmail Auth"
    echo ""
    echo "Usage:"
    echo "  $0 setup   — Connect your Gmail"
    echo "  $0 test    — Test connection"
    echo "  $0 status  — Show status"
    echo "  $0 remove  — Disconnect Gmail"
    echo ""
    echo "Creds stored at: $CREDS_FILE"
    ;;
esac
