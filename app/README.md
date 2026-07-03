# Sentinel Notifier - App Interna

Questa cartella contiene il runtime della desktop app Sentinel Notifier.

## Componenti

- `app.py`: worker, parsing pagina Sentinel, stato runtime, notifiche Windows e persistenza locale.
- `app_webview.py`: launcher della UI webview e bridge tra frontend e worker.
- `ui-demo-light-simple-dashboard.html`: UI principale caricata nella webview.
- `requirements.txt`: dipendenze Python.

## Flusso Operativo

1. La UI viene avviata da `start_sentinel_notifier_windows.bat`.
2. L'app pulisce il database runtime a ogni avvio.
3. L'utente collega una tab Sentinel gia' aperta tramite Chrome/Edge debug.
4. Il monitor legge gli incident visibili nella tab selezionata.
5. Gli incident non piu' presenti nella vista Sentinel vengono rimossi dal database locale.
6. Le notifiche Windows partono per nuovi alert e soglie SLA configurate.

## Database Locale

Il database runtime e' in `data/bot_state.sqlite3`.

Il database viene svuotato a ogni avvio per evitare storico locale. Le impostazioni operative restano persistite.

## Configurazione Sviluppo

Il flag interno `ENABLE_ASSIGNMENT_WORKFLOW` in `app.py` controlla se il workflow operativo avanzato deve essere eseguito.

Default:

```python
ENABLE_ASSIGNMENT_WORKFLOW = True
```

Per eseguire solo monitoraggio e notifiche, impostarlo a `False`.

## Esecuzione Background

All'avvio l'app abilita `KEEP_WINDOWS_AWAKE`, che usa Windows `SetThreadExecutionState` per evitare sleep/ibernazione mentre il processo e' attivo.

Il browser usa profili persistenti in `browser_profiles`. Se trova profili legacy (`chrome_bot_profile`, `edge_bot_profile`) li riusa per non perdere sessioni gia' autenticate.

La sessione resta salvata finche' cookie/token sono validi. Azure, Defender, MFA o policy aziendali possono comunque richiedere una nuova autenticazione.

## Log

I log applicativi sono in `logs/app.log`.
