# HTTPS-Zugang auf dem Mini-PC

Die Herdr-Chat-TUI ist unter **https://miniagent.minipc.ananta.de** erreichbar.
Stand der Einrichtung: 9. September 2026.

```text
Browser → Caddy :443 / TLS + Basic Auth
            → 172.23.0.1:7682 / ttyd
                → Herdr-Sitzung miniagent → Chat-TUI
```

Benutzername: `miniagent`. Das zufällig erzeugte Passwort liegt ausschließlich
auf dem Rechner in `~/.config/miniagent/web-login.json` (Dateirechte `0600`).
Lokal anzeigen:

```bash
python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".config/miniagent/web-login.json").read_text())["password"])'
```

Caddy verlangt die Anmeldung für alle Pfade, einschließlich `/ws`. Der Zugang
erlaubt die Bedienung einer Terminal-Sitzung als lokaler Benutzer `krusty`.
Die Zugangsdaten gehören deshalb nur dem Betreiber; sie sind nicht im Repository.
ttyd bindet ausschließlich an die private Docker-Bridge `172.23.0.1`, nicht an
eine öffentliche oder LAN-Adresse. Das bestehende Caddy-Netz `jupyter-edge`
stellt diese Host-Adresse bereit. Der lokale Zugang auf `127.0.0.1:7681` bleibt
unabhängig davon nutzbar. Jeder ttyd-Listener erlaubt einen gleichzeitigen Client.

## Hintergrunddienst

Der aktivierte systemd-Benutzerdienst heißt `miniagent-web.service`.
Seine [Vorlage](../examples/chat/miniagent-web.service) enthält die tatsächlichen
Pfade und die Bridge-Adresse dieses Rechners. Andere Installationen müssen diese
Werte anpassen. Hier ist Benutzer-Lingering bereits aktiviert; der Dienst startet
auch ohne interaktive Anmeldung. Ist die Docker-Bridge noch nicht verfügbar,
versucht systemd nach zehn Sekunden einen Neustart.

```bash
systemctl --user status miniagent-web.service
journalctl --user -u miniagent-web.service -n 30
systemctl --user restart miniagent-web.service
```

Zur erneuten Installation der Unit:

```bash
cd /home/krusty/TinyPilot
mkdir -p ~/.config/systemd/user
cp examples/chat/miniagent-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now miniagent-web.service
```

Der Launcher startet Herdr und die TUI bei Bedarf. Browser-Schließen oder Neuladen
trennt nur den Terminal-Client. Sitzung und Runs liegen unter `runs/chat/tetris`.
Nach einem Rechnerneustart werden gespeicherte Zustände geladen; pausierte Runs
werden ausdrücklich mit `/resume` fortgesetzt.

## Caddy

Der bestehende Container `compose-next-dev-domain-edge-1` liest
`/home/krusty/ananta/docker/compose-next/Caddyfile.dev-domain`.
Dort wurde ein eigener Site-Block ergänzt; andere Sites wurden beibehalten:

```caddyfile
https://miniagent.minipc.ananta.de {
    basic_auth {
        miniagent <BCRYPT_HASH>
    }
    header {
        -Server
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        Cache-Control "no-store"
    }
    reverse_proxy 172.23.0.1:7682
}
```

`<BCRYPT_HASH>` ist ein Platzhalter; die Live-Konfiguration enthält den mit
`caddy hash-password` erzeugten Hash. Caddy verwaltet das öffentliche TLS-Zertifikat
und die HTTP-zu-HTTPS-Weiterleitung. Zum Passwortwechsel müssen lokale Zugangsdaten
und der Hash in der Live-Konfiguration gemeinsam aktualisiert werden.

Die installierte Version 2.10.2 unterstützt `SIGUSR1`-Reload noch nicht, und die
Admin-API ist abgeschaltet. Nach Konfigurationsänderungen erst `caddy validate`
ausführen und dann ausschließlich den Edge-Container neu starten. Dessen
einzeln eingebundene Konfigurationsdatei muss beim Schreiben ihren Inode behalten.
Die Sicherung vor dieser Erweiterung liegt lokal in
`.cache/deploy/Caddyfile.before-miniagent`; sie ist kein Rollback für spätere
Änderungen anderer Sites.

## Verifikation und aktueller Modellstatus

Über den HTTPS-Host mit eingeschalteter Zertifikatsprüfung getestet:

- Ohne Zugangsdaten: HTTP `401`, auch für WebSocket-Upgrades.
- Falsches Passwort: HTTP `401`; korrektes Passwort: HTTP `200`.
- Chromium: Herdr-TUI sichtbar, `/status` eingegeben, Antwort sichtbar.
- Neuladen: Terminal-Verbindung wiederhergestellt, keine WebSocket-Fehler.
- HTTP wird mit `308` auf HTTPS umgeleitet.
- Bestehende Oberfläche auf `minipc.ananta.de`: weiterhin HTTP `200`.

Der veröffentlichte Terminalzugang läuft unabhängig vom Modellserver. Beim
vorangegangenen K2-Test fiel CUDA aus; `nvidia-smi -L` meldet weiterhin keine GPU.
Neue Modellantworten sind daher derzeit nicht verfügbar. Der Modellserver auf
Port `18089` wird von diesem Web-Dienst nicht gestartet. Nach Wiederherstellung
der GPU gilt der Startaufruf aus der [Chat-Anleitung](chat.md).
