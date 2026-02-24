# Deploy Runbook (Coolify + Traefik File Provider)

## Context
This project uses:
- App deployment via Coolify
- Domain routing via Traefik dynamic file config (`/data/coolify/proxy/dynamic/ka-org.yaml`)

Important:
- Do not rely on Coolify app `Domains` for `ka.organisatienetwerk.nl`.
- Source of truth for routing is `ka-org.yaml`.

## Pre-Deploy Checklist
1. Push code to `main`.
2. In Coolify app service, verify runtime env vars:
   - `KA_DASHBOARD_USERNAME`
   - `KA_DASHBOARD_PASSWORD`
   - `KA_DATA_DIR=/data`
3. Redeploy app service.

## Post-Deploy Verification
Run on VPS:

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"
```

Find the current app container (example: `jgck0wc80ok00co0gss8oogg`), then verify code/env:

```bash
docker exec -it jgck0wc80ok00co0gss8oogg sh -lc "grep -n 'AUTHENTICATION GATE' /app/dashboard.py; env | grep '^KA_DASHBOARD_'"
```

## Critical Routing Check
Verify Traefik backend target:

```bash
sudo grep -n 'url:' /data/coolify/proxy/dynamic/ka-org.yaml
```

Expected target format:

```text
url: http://<CURRENT_APP_CONTAINER_NAME>:8501
```

If it points to an old container, update and reload Traefik:

```bash
sudo sed -i 's#<OLD_CONTAINER>#<CURRENT_APP_CONTAINER>#g' /data/coolify/proxy/dynamic/ka-org.yaml
sudo docker restart coolify-proxy
```

## Smoke Test
1. Open `https://ka.organisatienetwerk.nl` in incognito/private window.
2. Confirm login screen appears.
3. Login and confirm sidebar shows `Uitloggen`.

## Known Failure Pattern
Symptom:
- "Deployed commit is correct, but UI still shows old behavior."

Cause:
- `ka-org.yaml` still routes to old container name.

Fix:
- Point `ka-org.yaml` to current container and restart `coolify-proxy`.

## Optional Diagnostic Commands
Check app startup command:

```bash
docker inspect jgck0wc80ok00co0gss8oogg --format '{{json .Config.Cmd}}'
```

Check app mounts:

```bash
docker inspect jgck0wc80ok00co0gss8oogg --format '{{json .Mounts}}'
```

Expected:
- Mount to `/data` is good.
- Mount to `/app` is risky (can mask new code).

Check proxy logs:

```bash
sudo docker logs --tail 100 coolify-proxy
```

## Security Notes
1. Rotate any password that was typed in shell/history.
2. Keep credentials only in Coolify environment variables.
3. Use a strong `KA_DASHBOARD_PASSWORD`.
