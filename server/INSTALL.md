# Report server

The **Device report → Send to the project server** option in the application
sends reports to this server. The server validates a report, stores it on disk
and opens it as an issue in a **private** GitHub repository. People who send
reports do not need a GitHub account, and no token ever goes into the
application or this repository.

```
Tartım application ──HTTPS──▶ nginx (/tartim/) ──▶ tartim-rapor service (127.0.0.1:8095)
                                                      │  store on disk (0600)
                                                      └──▶ GitHub API (private repo, issue)
```

Project server: `https://ldow.duckdns.org/tartim/report` (the older
`/tartim/rapor` path keeps working). Organisations that want to use their own
server set the `TARTIM_REPORT_URL` environment variable in the application;
an empty value disables sending to a server.

Errors are returned as `{"ok": false, "code": "...", "error": "..."}`. The
application shows a translated message for each `code`, so the server does not
need to know the user's language.

## Security model

In an open-source application every "secret" shipped inside the application is
public. So we do not try to authenticate the application; instead we make
abuse of the endpoint **harmless and expensive**:

| Layer | Measure |
|---|---|
| Transport | HTTPS only (Let's Encrypt). The service listens on `127.0.0.1`; only the `/tartim/` path in nginx is public. |
| Rate limits | nginx: 10 requests per minute per IP (burst of 5). Service: 5 reports per hour per IP, 200 per day in total. Rejected attempts count too. |
| Size and format | At most 2 MB; JSON only; `schema: 1`, a model name, at most 10 measurements, a note of at most 2000 characters. The user's "not a real client" confirmation is required. |
| Disk | At most 500 reports waiting to be forwarded; the server generates file names, no path is taken from the client. |
| Content sent to GitHub | Goes to a private repository, never public. The user's note is put in a code block (Markdown and mentions are neutralised); the model name in the title is reduced to safe characters. |
| Token | Fine-grained token: **only** the `tartim-raporlar` repository, **only** "Issues: Read and write", with an expiry date. Kept in a root-owned 0600 file and handed to the service with systemd `LoadCredential` (not visible in the environment or the logs). |
| Service isolation | `DynamicUser`, `ProtectSystem=strict`, `ProtectHome`, `NoNewPrivileges`, empty capability set, 96 MB memory limit. `systemd-analyze security tartim-rapor`: 3.4 (OK). |
| Logs | Neither report content nor IP addresses are logged; only report ids. |

**Worst case:** someone pushing against the limits creates a few junk issues in
the private repository; they are deleted. Even a leaked token can only open
issues in that private repository; it cannot touch other repositories, code or
the account. If in doubt, revoke the token on GitHub with one click.

Organisations that want a stricter setup (only their own staff can send) can
publish the endpoint on a Tailscale/VPN address only, instead of the internet.

## Installation

Requirements: Ubuntu/Debian, systemd, nginx and a site with a "listen 443 ssl" block.

```sh
git clone https://github.com/muratGursel/tartim.git
sudo sh tartim/server/install.sh /etc/nginx/sites-enabled/SITE
```

The script installs the service, backs up the nginx configuration
(`/root/tartim-rapor-yedek/`), adds the line `include snippets/tartim-rapor.conf;`
and rolls everything back if `nginx -t` fails. It is safe to run again (it is
also how you update).

Some names keep their original (Turkish) form so that existing installations
keep working: the `tartim-rapor` service, `/etc/tartim-rapor/github-token` and
the `tartim-raporlar` repository.

## Adding the GitHub token

1. GitHub → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**
   - **Token name:** `tartim-report-server`
   - **Expiration:** 1 year (put a renewal reminder in your calendar)
   - **Repository access:** *Only select repositories* → `tartim-raporlar`
   - **Permissions → Repository permissions → Issues:** *Read and write*
     (Metadata: Read-only is added automatically; give no other permission)
2. Copy the token and run this command **in your own terminal**. Do not paste
   the token into any chat, e-mail or file:

   ```sh
   ssh -t SERVER 'read -rsp "Token: " T; echo; printf %s "$T" | sudo tee /etc/tartim-rapor/github-token >/dev/null; unset T; sudo systemctl restart tartim-rapor; sudo journalctl -u tartim-rapor -n 3 --no-pager'
   ```

   The token is not shown while you type. The last lines should say
   `GitHub forwarding: on`. Reports received without a token wait on the server
   and are forwarded once the token is added.

## Operation

```sh
systemctl status tartim-rapor                    # status
journalctl -u tartim-rapor -f                    # log
sudo ls /var/lib/private/tartim-rapor/incoming   # waiting to be forwarded
sudo ls /var/lib/private/tartim-rapor/sent       # forwarded (with the issue address)
curl https://SERVER/tartim/health                # {"ok": true}
```

**Revoking the token:** delete it on GitHub and on the server run
`sudo truncate -s0 /etc/tartim-rapor/github-token && sudo systemctl restart tartim-rapor`.

**Removing:** `sudo systemctl disable --now tartim-rapor`, delete the
`include snippets/tartim-rapor.conf;` line from the site file and run
`sudo nginx -t && sudo systemctl reload nginx`.

## Personal data

Reports are meant for test measurements; on every submission the user confirms
that the measurement does not belong to a real client. Reports may still contain
the age, height, gender and body values of the test person. That is why they
are kept only on the server and in the private repository and never published.
Delete reports you no longer need.
