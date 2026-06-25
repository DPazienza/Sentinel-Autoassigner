# Sentinel Auto Assigner

Desktop app per monitorare e auto-assegnare incident in Microsoft Sentinel / Defender via UI web automatizzata.

## Stato attuale (principali caratteristiche)

- Interfaccia desktop (pywebview) con:
  - stato bot (start/pause/stop),
  - elenco incident in tempo reale,
  - log delle azioni,
  - impostazioni SLA/notification/refresh.
- Collegamento ad una tab Sentinel gia' aperta tramite CDP (chrome/edge debug).
- Notifiche Windows per nuovi alert e alert con SLA vicino alla soglia.
- Supporto fetch manuale e auto-fetch periodico (solo quando non in esecuzione bot).
- modalita' background-friendly: se Chrome/Edge sono gia' avviati sulla porta debug, l'app non rilancia piu' automaticamente il browser.

## Requisiti

- Windows 10/11
- Python 3.10+
- Permessi per avviare Chrome o Edge
- Accesso ad una tab Sentinel nel browser (login/MFA attivi nel browser scelto)

## Struttura repository

```text
Sentinel Autoassigner/
  app/
    app.py
    app_webview.py
    requirements.txt
  install_sentinel_autoassigner_windows.bat
  start_sentinel_autoassigner_windows.bat
  README.md
```

## Installazione (Windows)

1. Apri PowerShell o Prompt dalla root del progetto.
2. Esegui:

```bat
install_sentinel_autoassigner_windows.bat
```

Lo script esegue:
- creazione/attivazione del virtualenv `.venv`
- installazione dipendenze Python
- installazione runtime Chromium di Playwright

## Avvio

```bat
start_sentinel_autoassigner_windows.bat
```

Il batch avvia l'app con `pythonw` e UI webview.

## Utilizzo rapido

1. Avvia Chrome/Edge debug dal pulsante della UI (o assicurati che sia gia' attiva sulla porta corretta).
2. Premere `Refresh browser tabs`.
3. Selezionare la tab Sentinel.
4. Avviare il bot (`Start` dry-run o reale).

### Opzioni bot

- **Fetch current view**: forza una lettura rapida della vista attiva.
- **Stop**: ferma completamente bot e auto-fetch.
- **Settings**: aggiorna SLA (taking charge, notification, resolution), % notifiche e intervalli.

## Nota comportamento background (Chrome/Edge)

L'app ora:
- evita di riaprire il browser se la porta CDP e' gia' attiva (`9222` per Chrome, `9223` per Edge);
- non forza piu' il focus della finestra browser durante le operazioni;
- puo' continuare a lavorare anche se browser e' minimizzato o su un altro desktop.

Se il browser non si collega automaticamente:
- verifica che il canale CDP sia aperto sulla porta giusta,
- controlla che la tab selezionata sia effettivamente una pagina Sentinel,
- premi nuovamente `Refresh browser tabs`.

## File importanti

- `app/app.py`  
  logica worker, scan/fetch, notifiche, gestione stato.
- `app/app_webview.py`  
  wrapper launcher UI webview + avvio browser debug.
- `app/requirements.txt`  
  dipendenze.

## Troubleshooting

- **La UI non mostra incident**: verifica selezione tab e login corretto in Sentinel.
- **Doppia apertura browser**: assicurati che la sessione debug precedente sia attiva; in tal caso l'avvio viene saltato.
- **Notifiche non appaiono**: controlla che Winotify/Toast siano disponibili su Windows e che il DB non filtri l'incidente gia' segnato.
- **Fetch lento**: aumenta i log o controlla condizioni di rete/portal.

## Sviluppo / manutenzione

- Tutte le operazioni vengono loggate in:
  - `app/logs/app.log`
- Database app:
  - `app/data/bot_state.sqlite3`

## Nota

Questo repository non include dati sensibili: gli ambienti utente e i credenziali di accesso devono restare gestiti nel browser/sessione corrente di Sentinel.
