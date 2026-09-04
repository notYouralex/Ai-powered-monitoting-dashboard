# Internal HTTPS deployment

This runbook prepares the approved internal-only HTTPS model for the monitoring platform. It does not contain production hostnames, private keys, passwords, or tokens. Live package installation, certificate installation, Grafana or Wazuh Dashboard changes, DNS/firewall changes, and service reloads require explicit approval.

## Target architecture

Use one approved internal IP with three internal DNS names:

```text
https://<GRAFANA_HOSTNAME>         -> Nginx -> https://127.0.0.1:3000 (Grafana)
https://<APP_HOSTNAME>             -> Nginx -> http://127.0.0.1:8000 (FastAPI / AI)
https://<WAZUH_DASHBOARD_HOSTNAME> -> Nginx -> https://127.0.0.1:5601 (Wazuh Dashboard)

PostgreSQL remains local only at 127.0.0.1:55432.
```

Separate hostnames are intentional. Grafana, FastAPI, and Wazuh Dashboard each have their own routes and authentication behavior. A single hostname with path routing would create unnecessary route and cookie conflicts.

The repository template is `deploy/nginx/ai-monitoring.conf.example`. It contains no certificate, private key, password, token, or production hostname.

## Required approved values

Before rendering the template, obtain these values from the company deployment owner:

- `<INTERNAL_BIND_IP>`: the specific approved company-network interface address. Do not replace it with `0.0.0.0` or `[::]`.
- `<GRAFANA_HOSTNAME>`: the internal DNS name used by Grafana users.
- `<APP_HOSTNAME>`: the internal DNS name used for FastAPI and the `/ai` interface.
- `<WAZUH_DASHBOARD_HOSTNAME>`: the internal DNS name used for Wazuh Dashboard.
- `<APP_PORT>`: normally `8000` unless `APP_PORT` is deliberately changed.
- `<GRAFANA_UPSTREAM_CA_PATH>`: CA/trust path for Grafana's existing loopback TLS certificate. On the current host the Grafana certificate is self-signed `CN=localhost`, so the certificate file itself can be used as the trust anchor after its path is verified.
- `<TLS_CERTIFICATE_PATH>`: path to the company-approved certificate/full chain used by Nginx.
- `<TLS_PRIVATE_KEY_PATH>`: protected host path to the matching private key.
- `<WAZUH_DASHBOARD_CA_PATH>`: protected/readable CA certificate path that validates the existing Wazuh Dashboard server certificate.

The external Nginx certificate must cover all three internal hostnames, for example through SAN entries or an approved internal wildcard certificate.

Do not reuse the current Wazuh Dashboard server certificate as the external Nginx certificate unless its SANs are explicitly reissued for the approved internal hostnames. The currently observed Wazuh Dashboard certificate is valid for loopback (`127.0.0.1`) and is appropriate for the local upstream, not for user-facing internal DNS names.

Do not commit TLS certificate or private key material. Do not copy a private key into the repository or Docker build context.

## Production application settings

The production `.env` remains outside Git. At minimum, production deployment must use:

```text
APP_ENV=production
COOKIE_SECURE=true
```

`APP_SECRET_KEY`, `POSTGRES_PASSWORD`, `GRAFANA_API_TOKEN`, and source credentials must be strong production values supplied through the approved secret process. Configured source integrations must keep TLS verification enabled.

Validate the resolved application configuration before changing the live stack:

```bash
docker compose config --quiet
```

FastAPI must continue listening only on `127.0.0.1:8000` (or the configured loopback `APP_PORT`). PostgreSQL must continue listening only on `127.0.0.1:55432` (or the configured loopback `POSTGRES_HOST_PORT`).

## Grafana server settings

Grafana remains the main monitoring dashboard UI. Before HTTPS acceptance, its direct listener must be restricted from all interfaces to loopback and its external URL must match the HTTPS hostname.

The current host already serves Grafana over HTTPS on port 3000 with a self-signed `CN=localhost` certificate. Preserve that local TLS. Apply these values to the existing `[server]` section of `/etc/grafana/grafana.ini` only after making a backup, while keeping the existing `cert_file` and `cert_key` paths unchanged:

```ini
[server]
protocol = https
http_addr = 127.0.0.1
http_port = 3000
domain = <GRAFANA_HOSTNAME>
enforce_domain = true
root_url = https://<GRAFANA_HOSTNAME>/
```

Restricting `http_addr` to `127.0.0.1` prevents users from bypassing Nginx on port 3000. Nginx connects to Grafana with TLS and verifies the loopback certificate using `<GRAFANA_UPSTREAM_CA_PATH>` and the certificate name `localhost`.

## Wazuh Dashboard server settings

The current host uses Wazuh Dashboard directly on port 443. Nginx cannot safely take port 443 until Wazuh Dashboard is moved to a loopback-only alternate port.

Port `5601` was verified free on the current host. Keep the existing Wazuh Dashboard TLS certificate and private-key settings unchanged, and change only the listener address/port required for the handoff:

```yaml
server.host: 127.0.0.1
server.port: 5601
server.ssl.enabled: true
```

Do not disable Wazuh Dashboard TLS. The Nginx template connects to `https://127.0.0.1:5601` and requires:

```text
proxy_ssl_verify on
<WAZUH_DASHBOARD_CA_PATH>
```

Before editing Wazuh Dashboard, inspect and record the current server TLS paths without printing key contents:

```bash
sudo grep -nE '^server\.(host|port|ssl\.enabled|ssl\.certificate|ssl\.key):' \
  /etc/wazuh-dashboard/opensearch_dashboards.yml
```

Identify the CA file that validates the configured dashboard certificate. Candidate files are normally stored with the Wazuh Dashboard certificates. Verify the selected CA against the configured server certificate before using it in Nginx:

```bash
sudo openssl verify -CAfile <WAZUH_DASHBOARD_CA_PATH> <WAZUH_DASHBOARD_CERTIFICATE_PATH>
```

Expected result ends with `OK`. Do not weaken Nginx upstream verification if this fails; identify the correct CA instead.

## Back up live configuration before the handoff

Before any edit, create protected backups outside the repository:

```bash
sudo cp --preserve=all /etc/wazuh-dashboard/opensearch_dashboards.yml \
  /etc/wazuh-dashboard/opensearch_dashboards.yml.pre-internal-https

sudo cp --preserve=all /etc/grafana/grafana.ini \
  /etc/grafana/grafana.ini.pre-internal-https
```

If Nginx already has a site configuration when activation occurs, back that up as well.

## Prepare the Nginx configuration

Work on a copy outside the repository so deployment-specific hostnames and certificate paths are not committed:

```bash
cp deploy/nginx/ai-monitoring.conf.example /tmp/ai-monitoring.conf
```

Replace every `<...>` placeholder in `/tmp/ai-monitoring.conf` with approved values. Confirm that none remain:

```bash
grep -n '<[A-Z_]*>' /tmp/ai-monitoring.conf
```

The command should return no output.

The template deliberately redirects HTTP to each fixed configured hostname instead of reflecting the incoming `Host` header. HTTPS uses only TLS 1.2 and TLS 1.3. The FastAPI upstream read/send timeout is 180 seconds so the reverse proxy does not cut off the default 120-second local AI request timeout. Grafana Live WebSocket traffic is proxied through `/api/live/`. Wazuh Dashboard remains encrypted on loopback and Nginx verifies its certificate using `<WAZUH_DASHBOARD_CA_PATH>`.

## Safe activation order

The order matters because Wazuh Dashboard currently owns port 443:

1. Install Nginx, but do not start/reload a listener on port 443 yet.
2. Prepare the rendered Nginx configuration and validate all certificate paths.
3. Back up Wazuh Dashboard and Grafana configuration.
4. Change Wazuh Dashboard to `127.0.0.1:5601` while preserving `server.ssl.enabled: true` and its existing certificate/key paths.
5. Validate the Wazuh Dashboard configuration according to the installed package/version.
6. Restart Wazuh Dashboard and verify `https://127.0.0.1:5601` before continuing.
7. Change Grafana to `127.0.0.1:3000` and the approved HTTPS `root_url` while preserving `protocol = https` and its existing certificate/key paths.
8. Restart Grafana and verify `https://127.0.0.1:3000` before continuing.
9. Install/enable the rendered Nginx site.
10. Run `nginx -t` and only then start/reload Nginx.
11. Validate all three HTTPS hostnames.
12. Only after application validation, make any separately approved DNS/firewall changes needed for client access.

Do not disable authentication, TLS verification, or secure cookies to make deployment easier.

## Pre-reload validation

After Nginx is installed and the rendered file is placed in the approved configuration location, validate syntax before any reload:

```bash
nginx -t
```

Also verify the intended local listeners:

```bash
ss -ltn
```

Expected backend listeners after the Wazuh/Grafana handoff and before/alongside Nginx are:

```text
127.0.0.1:8000   FastAPI
127.0.0.1:3000   Grafana (TLS)
127.0.0.1:5601   Wazuh Dashboard (TLS)
127.0.0.1:55432  PostgreSQL
```

After Nginx activation, only the approved internal interface should add ports 80 and 443. There must be no public `0.0.0.0` or `[::]` listener for FastAPI, Grafana, Wazuh Dashboard, or PostgreSQL.

## HTTPS acceptance checks

Use the company CA chain when required. Replace placeholders below with approved values:

```bash
curl --fail --show-error \
  --resolve <APP_HOSTNAME>:443:<INTERNAL_BIND_IP> \
  --cacert <COMPANY_CA_CERT_PATH> \
  https://<APP_HOSTNAME>/health

curl --fail --show-error --head \
  --resolve <GRAFANA_HOSTNAME>:443:<INTERNAL_BIND_IP> \
  --cacert <COMPANY_CA_CERT_PATH> \
  https://<GRAFANA_HOSTNAME>/login

curl --fail --show-error --head \
  --resolve <WAZUH_DASHBOARD_HOSTNAME>:443:<INTERNAL_BIND_IP> \
  --cacert <COMPANY_CA_CERT_PATH> \
  https://<WAZUH_DASHBOARD_HOSTNAME>/
```

Expected results:

- FastAPI `/health` returns HTTP 200 through HTTPS.
- Grafana login is reachable through HTTPS.
- Wazuh Dashboard redirects or loads its normal login route through HTTPS.
- HTTP requests redirect to the corresponding configured HTTPS hostname.
- Browser login to FastAPI uses a `Secure` session cookie.
- Grafana dashboards continue loading through the HTTPS hostname.
- Grafana Live does not report WebSocket proxy errors.
- Nginx can verify both the Grafana and Wazuh Dashboard loopback TLS certificates without disabling verification.
- Direct access from another machine is not available on ports 8000, 3000, 5601, or 55432.

## Rollback

Keep the previous validated Wazuh Dashboard, Grafana, and Nginx configuration before activation. If HTTPS validation fails:

1. Stop/disable the new Nginx site or restore its previous configuration.
2. Validate Nginx with `nginx -t` before any reload.
3. Restore `/etc/wazuh-dashboard/opensearch_dashboards.yml.pre-internal-https` and restart Wazuh Dashboard only after approval.
4. Restore `/etc/grafana/grafana.ini.pre-internal-https` and restart Grafana only after approval.
5. Verify the original Wazuh Dashboard listener and Grafana listener returned.
6. Recheck the loopback FastAPI health endpoint.

The application and database remain loopback-bound throughout the reverse-proxy change, so rollback must not require exposing them directly.
