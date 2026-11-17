#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SITE_ADDRESS="${1:?Usage: bash deploy/enable-https.sh your.hostname.example}"
if [[ ! "$SITE_ADDRESS" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+[a-zA-Z0-9]$ ]]; then
    echo 'Provide a DNS hostname without a URL scheme or path.' >&2
    exit 1
fi
sudo apt-get update -qq
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y certbot
sudo install -d -m 755 /var/www/certbot
DC=(docker compose --env-file .env.ec2 -f deploy/compose.yml)
"${DC[@]}" -f deploy/compose.acme.yml up -d --no-deps --force-recreate web
sudo certbot certonly --webroot -w /var/www/certbot -d "$SITE_ADDRESS" \
    --non-interactive --agree-tos --register-unsafely-without-email
python3 - "$SITE_ADDRESS" <<'PY'
from pathlib import Path
import sys
p=Path('.env.ec2')
lines=[line for line in p.read_text().splitlines() if not line.startswith('SITE_ADDRESS=')]
lines.append('SITE_ADDRESS='+sys.argv[1])
p.write_text('\n'.join(lines)+'\n')
p.chmod(0o600)
PY
"${DC[@]}" -f deploy/compose.https.yml up -d --no-deps --force-recreate web
"${DC[@]}" -f deploy/compose.https.yml exec -T web nginx -t
# Generate a renewal hook using a safely quoted absolute repository path.
python3 - <<'PY' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/meowmatch-reload.sh > /dev/null
import os,shlex
print('#!/bin/bash\nset -euo pipefail')
print('cd '+shlex.quote(os.getcwd()))
print('docker compose --env-file .env.ec2 -f deploy/compose.yml -f deploy/compose.https.yml exec -T web nginx -s reload')
PY
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/meowmatch-reload.sh
sudo systemctl enable --now certbot.timer
echo "HTTPS enabled: https://$SITE_ADDRESS"
