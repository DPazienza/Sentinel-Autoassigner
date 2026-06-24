# Sentinel Auto Assign Bot - Desktop App

Applicazione desktop Windows per supportare la presa in carico degli incident Microsoft Sentinel dalla pagina web del portale Azure, senza usare API Sentinel/Azure.

Il bot si collega a una tab Sentinel aperta su Chrome o Edge, legge gli incident visibili, assegna all'utente corrente gli incident non assegnati, porta in `Active` gli incident assegnati a te e monitora i KPI operativi.

---

## Requisiti

```text
Windows
Python 3.10+
Google Chrome oppure Microsoft Edge
```

Durante l'installazione di Python abilita:

```text
Add python.exe to PATH
```

---

## Installazione

1. Estrai lo ZIP.
2. Apri la cartella estratta.
3. Esegui:

```text
install_sentinel_autoassigner_windows.bat
```

---

## Avvio

Uso normale:

```text
start_sentinel_autoassigner_windows.bat
```

Uso debug:

```text
app\tools\start_sentinel_autoassigner_debug_console.bat
```

Il debug lascia la console aperta e serve per vedere errori tecnici.

---

## Collegamento a Sentinel

Procedura consigliata:

```text
1. Avvia l'app
2. Clicca Launch Chrome for bot oppure Launch Edge for bot
3. Fai login su Azure
4. Completa MFA
5. Attiva eventuale PIM
6. Apri Microsoft Sentinel > Incidents
7. Torna nell'app
8. Premi Refresh browser tabs se la tab non appare
9. Seleziona la tab Sentinel corretta
10. Premi FETCH CURRENT VIEW NOW
```

Il bot lavora solo sulla tab selezionata.

---

## Controlli principali

### FETCH CURRENT VIEW NOW

Esegue una lettura manuale della vista Sentinel corrente.

Non assegna nulla e non cambia status.

### START DRY-RUN

Prima esegue un fetch iniziale, poi simula cosa farebbe il bot senza modificare Sentinel.

### START REAL BOT

Prima esegue un fetch iniziale, poi avvia il bot reale.

Logica:

```text
Owner = Unassigned
    -> Assign to me
    -> Apply
    -> verifica Owner
    -> se Status = New, imposta Active

Owner = me
    -> se Status = New, imposta Active

Owner = altro utente
    -> skip
    -> non cambia Owner
    -> non cambia Status
```

### PAUSE

Mette in pausa il bot e disabilita l'auto-fetch.

### RESUME

Riprende il bot. L'auto-fetch resta disabilitato mentre il bot è in esecuzione.

### STOP

Ferma il bot e disabilita anche l'auto-fetch.

Dopo STOP, per aggiornare la dashboard usa manualmente:

```text
FETCH CURRENT VIEW NOW
```

---

## Auto-fetch e bot

L'app evita che fetch e bot lavorino insieme sulla stessa tab.

Regola:

```text
Auto-fetch attivo solo quando il bot è fermo
Bot in avvio -> fetch iniziale completato prima del bot
Bot running/paused -> auto-fetch disabilitato
STOP -> bot fermo e auto-fetch disabilitato
```

Questo riduce errori dovuti a click o letture simultanee della stessa pagina Sentinel.

---

## KPI gestiti

### Taking Charge Time

Serve per misurare entro quanto un incident deve essere preso in carico.

Default:

```text
Critical: 30 min
High:     30 min
Medium:   60 min
Low:      60 min
Info:     60 min
```

### Notification Time

Serve per il popup di notifica.

Default:

```text
Critical: 30 min
High:     60 min
Medium:   240 min
Low:      480 min
Info:     480 min
```

Il popup usa il Notification Time, non una percentuale del Taking Charge.

---

## Dashboard

Colonne principali:

```text
Incident
Severity
Status
Owner
Title
Created
Min To Taking Charge
Min To Notify
Last Notified
Last Update
Active Since
Age
Workspace
```

`OVERDUE X min` indica che il KPI è già superato.

---

## Log

L'app logga gli eventi in due posti.

### Log nella UI

Tab:

```text
Actions / logs
```

Mostra eventi come:

```text
FETCH
SCAN
BOT_START
BOT_STOP
ASSIGN_TO_ME
SET_ACTIVE
SKIP_OTHER_OWNER
SLA_NOTIFICATION
ERROR
```

### Log su file

File:

```text
app/logs/app.log
```

Contiene errori tecnici, stack trace e problemi Playwright/browser.

Se qualcosa si rompe, questo è il primo file da controllare.

---

## Perché su alcuni PC funziona meglio che su altri

Il bot controlla una pagina web dinamica, quindi la stabilità dipende da vari fattori:

```text
versione Chrome/Edge
zoom browser
risoluzione schermo
lingua UI Sentinel
performance del PC
latenza rete
sessione Azure/MFA/PIM
policy aziendali del browser
estensioni browser
aggiornamenti del portale Azure
```

Consigli:

```text
usa Chrome/Edge lanciato dal bottone dell'app
evita zoom strani se possibile
non usare la stessa tab manualmente mentre il bot lavora
aspetta che Sentinel abbia caricato completamente la tab Incidents
usa START DRY-RUN prima della modalità reale
```

---

## Errore EPIPE / Playwright / Node

Un errore tipo:

```text
Error: EPIPE: broken pipe, write
```

indica che il canale tra Python, Playwright/Node e il browser si è rotto.

Può accadere se:

```text
il browser viene chiuso mentre il bot lo controlla
la tab Sentinel viene ricaricata/chiusa
l'app viene chiusa mentre Playwright sta scrivendo
la sessione CDP del browser cade
due operazioni provano a usare la tab quasi insieme
```

Questa versione chiude Playwright in modo più ordinato e serializza le operazioni per ridurre il problema.

---

## Reset stato locale

Per cancellare database e stato locale:

```text
app\tools\reset_sentinel_local_state.bat
```

Questo resetta:

```text
incident letti
azioni/log UI
ultimo timestamp SLA
owner display name salvato
settings KPI
```

---

## Procedura consigliata

```text
1. Avvia l'app
2. Lancia Chrome/Edge dal bottone dell'app
3. Login Azure + MFA + PIM
4. Apri Sentinel > Incidents
5. Premi FETCH CURRENT VIEW NOW
6. Controlla dashboard
7. Premi START DRY-RUN
8. Controlla Actions / logs
9. Premi START REAL BOT
10. Usa STOP per fermare bot e auto-fetch
```


---

## Ignore manuale incident

La versione desktop include:

```text
IGNORE SELECTED
UNIGNORE ALL
```

Uso:

```text
1. Seleziona una riga nella dashboard Incidents seen by bot
2. Premi IGNORE SELECTED
3. L'incident viene rimosso dalla dashboard locale
4. Non genera più notifiche SLA
5. Il bot lo salta anche se lo rivede nella vista Sentinel
```

Per ripristinare tutti gli ignore:

```text
UNIGNORE ALL
FETCH CURRENT VIEW NOW
```

Questo è utile quando un incident è già stato gestito/chiuso su Sentinel ma resta nello stato locale del muletto.


---

## Sincronizzazione forte con Sentinel Incidents

La dashboard locale ora viene riallineata alla lista incident visibile in Sentinel dopo ogni fetch/scan completato.

Regola:

```text
Incident visibile nella lista Sentinel
    -> resta nella dashboard del muletto

Incident non più visibile nella lista Sentinel
    -> viene rimosso dalla dashboard del muletto
    -> non genera più notifiche SLA
    -> non viene più processato
```

Questo copre il caso in cui un incident/offense sia stato chiuso o gestito direttamente su Sentinel e quindi non compaia più nella sezione `Incidents`.

Puoi forzare manualmente la pulizia con:

```text
FETCH CURRENT VIEW NOW
```

oppure:

```text
SYNC CURRENT VIEW
```

Se la vista Sentinel corrente è vuota e il fetch è completato correttamente, anche la dashboard locale viene svuotata.
