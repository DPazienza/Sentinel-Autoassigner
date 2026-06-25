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

## Panoramica dettagliata UI

La finestra principale e' divisa in blocchi funzionali per separare controllo, stato e dettaglio incident:

- **Header / Stato globale**
  - Titolo app e stato corrente del worker.
  - Label di stato in basso con messaggi operativi (`Ready/scan running/fetch done/error`).

- **Workspace / Browser**
  - Sezione con pulsanti `Lancia Chrome Debug` e `Lancia Edge Debug`.
  - Pulsante `Refresh browser tabs` per rilista tutte le tab correnti collegate ai CDP.
  - Elenco tab con:
    - Browser (Chrome/Edge)
    - Indicatore Sentinel (`Yes/No`)
    - Titolo e URL
  - Selezionando una riga, l'app imposta la tab target per fetch/scan.

- **Controllo bot e stato esecuzione**
  - `Start (dry-run)` e `Start (reale)`: avviano il ciclo automatico con primo fetch immediato.
  - `Pause` / `Resume`: mettono in pausa l'esecuzione automatica senza cancellare lo stato.
  - `Stop`: ferma bot, auto-fetch e loop operativi.
  - `FETCH CURRENT VIEW NOW`: forza una lettura immediata della vista corrente (solo quando il bot non sta processando).

- **Blocchi SLA / impostazioni avanzate**
  - Card dedicata ai threshold:
    - `Taking Charge / Notification / Resolution` per severita' (Critical, High, Medium, Low).
    - `Misclassification %`.
    - `% notifiche Windows`, `Ripeti notifica (min)`.
    - `Scan interval (s)`, `Auto-fetch interval (s)`.
  - Le impostazioni sono persistite e inviate al worker con `Salva impostazioni`.

- **Tab Incidenti**
  - Griglia con campi principali:
    - ID incident
    - Severity
    - Stato/Owner
    - Titolo
    - Timestamps
    - Remaining SLA (Taking charge/Notification)
    - Ultimo warning / ultimo aggiornamento
  - Colorazioni per severita' (critical/high/medium/low) e stato.
  - Azioni per riga:
    - `Ignore` (da UI principale): imposta l'incidente come ignorato localmente senza cancellare manualmente dal DB core.

- **Tab Azioni/Log**
  - Log cronologico di tutte le azioni principali:
    - fetch/scan
    - assignment
    - stato active
    - notifiche sent/sentenza
  - Utile per audit e diagnostica rapida.

## Flusso UI in uso quotidiano

1. Avvio app.
2. Lancio/connessione browser debug.
3. Refresh tab e selezione della pagina Sentinel corretta.
4. Settaggio intervalli (opzionale) e check SLA.
5. Start dry-run per verifica senza modifiche.
6. Passaggio a start reale quando la lista si comporta correttamente.

## Come leggere i campi chiave

- **Status bot**: riflette direttamente lo stato del runtime (`running`, `paused`, `starting`, `stop`) ed evita conflitti tra scan automatici e fetch manuali.
- **AUTO-FETCH / SCAN**:
  - Auto-fetch: leggeri refetch su tab selezionata quando il bot e' fermo.
  - Scan: ciclo automatico completo quando bot in run con intervallo `Scan interval (s)`.
- **Incident row status**:
  - `new active/closed` visibile nel campo stato.
  - owner e percentuale di ETA sono aggiornati dopo refresh.
- **SLA columns**:
  - il valore mostrato e' il tempo residuo in minuti verso la soglia corrente della severita' impostata.

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
