# Sentinel Auto Assign Bot - Desktop App

Questa versione apre una vera app desktop, non una dashboard web.

## Cosa fa

- Ti permette di avviare Chrome o Edge in modalità controllabile dal bot.
- Elenca le tab aperte su Chrome/Edge.
- Ti permette di selezionare la tab Sentinel corretta, utile se lavori con più browser o più workspace.
- Ha un pulsante `FETCH CURRENT VIEW` che legge gli incident senza modificarli.
- Ha `START REAL BOT` per assegnare i `New + Unassigned` e portarli in `Active`.
- Ha SLA configurabili e notifiche Windows al raggiungimento della percentuale scelta, default 60%.

## Limite importante

Non è possibile trascinare fisicamente una tab Chrome/Edge/Firefox dentro l'app e controllarla in modo affidabile.
La soluzione corretta è selezionare la tab dalla lista dopo aver aperto Chrome/Edge con remote debugging.

Firefox non è supportato per agganciare una tab già aperta. Chrome ed Edge sì.

## Installazione

Esegui:

```text
install_windows.bat
```

## Avvio

Esegui:

```text
run_desktop_app_windows.bat
```

## Flusso

1. Apri l'app.
2. Clicca `Launch Chrome for bot` o `Launch Edge for bot`.
3. Fai login Azure, MFA e PIM.
4. Vai su Microsoft Sentinel > Incidents.
5. Premi `Refresh browser tabs`.
6. Seleziona la tab del workspace corretto.
7. Premi `FETCH CURRENT VIEW`.
8. Controlla la tabella degli incident visti dal bot.
9. Se i dati sono corretti, premi `START REAL BOT`.

## Porte locali

- Chrome: 127.0.0.1:9222
- Edge: 127.0.0.1:9223

Non esporre queste porte sulla rete.


## Fix auto-link tab

Questa versione avvia Chrome/Edge con un profilo dedicato in:

```text
browser_profiles/chrome_bot_profile
browser_profiles/edge_bot_profile
```

Questo è necessario perché, se Chrome/Edge è già aperto normalmente, il comando di avvio spesso riusa il processo esistente e la porta di debug non viene attivata. In quel caso l'app non vede nessuna scheda.

Con il profilo dedicato:

```text
Launch Chrome for bot
→ apre una nuova finestra Chrome debuggabile
→ l'app fa Refresh automaticamente
→ seleziona automaticamente la tab Azure/Sentinel
```

Se hai più workspace aperti, puoi comunque selezionare manualmente la tab corretta nella tabella.


## Fixed BROWSER_PROFILE_DIR

Questa release corregge l'errore:

```text
NameError: name 'BROWSER_PROFILE_DIR' is not defined
```

e crea automaticamente la cartella:

```text
browser_profiles/
```

usata per avviare Chrome/Edge in modalità bot.


## No-refresh fetch + auto-fetch

Questa release cambia il comportamento di `FETCH CURRENT VIEW`:

```text
prima: ricaricava la pagina Sentinel
ora: legge direttamente la schermata corrente senza refresh
```

Quindi non modifica i filtri, non riapre la blade e non cambia la vista impostata manualmente su Sentinel.

Inoltre la dashboard fa automaticamente una fetch ogni 20 secondi quando:

```text
- una tab Sentinel è selezionata
- il bot real/dry-run non è in esecuzione
- l'app non è in pausa
```

Puoi cambiare l'intervallo dalla sezione SLA/settings:

```text
Auto fetch sec
```

Se premi `START REAL BOT`, invece, entra in gioco lo scan del bot con l'intervallo `Scan sec`.


## SLA breach time based on Created

La tabella `Incidents seen by bot` ora include due nuove colonne:

```text
SLA Notify At
SLA Due At
```

La colonna `SLA Due At` viene calcolata come:

```text
Creation time + SLA della severity
```

Esempio:

```text
Created = 06/06/26, 04:23 PM
Severity = Informational
Info SLA = 480 min
SLA Due At = 06/07/26, 12:23 AM
```

La colonna `SLA Notify At` usa invece la percentuale configurata, ad esempio 60% dello SLA.


## Fix fetch + silent app

Questa release corregge l'errore:

```text
NameError: name 'add_minutes_to_sentinel_datetime' is not defined
```

`FETCH CURRENT VIEW` torna a funzionare e mantiene le colonne:

```text
SLA Notify At
SLA Due At
```

## Avvio senza shell

Per uso normale:

```text
run_desktop_app_windows.bat
```

Questo usa `pythonw.exe`, quindi la shell non resta aperta.

Se vuoi vedere errori o log in console:

```text
run_desktop_app_debug_console_windows.bat
```

Versione completamente nascosta:

```text
run_desktop_app_hidden_windows.vbs
```

## Chiusura

Premendo la `X` sulla finestra dell'app, il bot viene fermato e il processo Python viene terminato.


## Safe assignment fix

Questa release corregge il problema in cui il bot poteva assegnare un incident e poi disassegnarlo.

Cause probabile:

```text
il bot cliccava testi generici come "Unassigned" o "New" nella pagina intera;
Azure/Sentinel ha molti elementi simili nella lista, nei filtri e nel detail pane;
un click successivo poteva riaprire il menu Owner e causare un unassign.
```

Fix implementati:

```text
- Owner: click diretto sull'area Owner del detail pane, non sul testo generico "Unassigned"
- Status: click diretto sull'area Status del detail pane, non sul testo generico "New"
- rimosso click generico su Apply/Save
- se un incident è già stato preso dal bot, non viene mai più toccato l'Owner
- dopo Assign to me, l'incident viene marcato subito localmente per evitare retry pericolosi
```


## ID-based processing fix

Questa release cambia la logica del bot:

```text
1. legge prima la lista degli ID visibili
2. prende il primo ID
3. apre dinamicamente la riga con quell'ID
4. verifica che il detail pane aperto contenga lo stesso ID
5. controlla Owner:
   - se Unassigned -> Assign to me
   - altrimenti non tocca l'Owner
6. ricontrolla lo stesso ID aperto
7. controlla Status:
   - se New -> Active
   - altrimenti non tocca lo Status
8. passa all'ID successivo cercandolo di nuovo nella lista corrente
```

Questo evita il problema in cui, dopo l'assegnazione, la lista Sentinel si riordina o una riga sparisce e il bot finisce per agire sull'incident sbagliato.


## Remaining SLA minutes

La tabella non mostra più l'orario assoluto di notifica/SLA.

Ora mostra:

```text
Min To Notify = minuti mancanti alla notifica SLA, calcolati da Created
Min To SLA    = minuti mancanti alla scadenza SLA, calcolati da Created
```

Esempio:

```text
Created = 10:00
High SLA = 60 min
Notify at = 60%
Ora = 10:20

Min To Notify = 16 min
Min To SLA = 40 min
```

Se la soglia è già superata, la tabella mostra:

```text
OVERDUE X min
```


## Control + assignment reliability fix

Questa release corregge due punti:

### 1. Bottoni Pause / Resume / Stop

Prima i bottoni passavano solo dalla coda del worker. Se il worker era dentro uno scan lungo,
il comando veniva letto solo alla fine dello scan.

Ora i bottoni aggiornano subito lo stato del worker:

```text
PAUSE -> si ferma prima del prossimo incident
STOP  -> interrompe il ciclo prima del prossimo incident
RESUME -> riprende
```

### 2. Assign/Active più robusto

La logica rimane ID-based:

```text
- prende l'ID
- apre quell'ID
- verifica che il detail pane sia lo stesso ID
- se Owner = Unassigned, prova Assign to me
- se Status = New, prova Active
```

In più ora, se il click diretto sull'area Owner/Status non apre il menu, usa un fallback controllato:

```text
Owner fallback: clicca "Unassigned" solo se il dettaglio ha confermato Owner = Unassigned
Status fallback: clicca "New" solo se il dettaglio ha confermato Status = New
```

Questo dovrebbe risolvere il caso in cui legge gli incident ma non esegue l'assegnazione.


## Apply + verify fix

Questa release corregge il problema visto nello screenshot:

```text
il bot apriva il menu Owner e selezionava "Assign to me",
ma non premeva Apply.
```

Ora la logica è:

```text
Owner:
1. apre menu Owner
2. seleziona Assign to me
3. preme Apply
4. rilegge la UI
5. segna SUCCESS solo se Owner non è più Unassigned

Status:
1. apre menu Status
2. seleziona Active
3. preme Apply se presente
4. rilegge la UI
5. segna SUCCESS solo se Status è davvero Active
```

La dashboard non marca più l'incident come Active/me in modo ottimistico: aggiorna lo stato solo dopo verifica reale dalla schermata Sentinel.


## Status click + speed fix

Questa release corregge il problema in cui il bot assegnava l'owner ma non metteva l'incident in Active.

Cambiamenti:

```text
- click sullo Status fatto cercando "New" solo nella detail pane destra, non nella tabella
- coordinate Status aggiornate per la riga alta della detail pane
- selezione "Active" cercata solo nel menu/pannello destro
- dopo Status=Active verificato, il bot preme Refresh sulla toolbar Sentinel
- ridotti diversi tempi di attesa per rendere il ciclo più veloce
```

Il flusso reale ora è:

```text
1. apre incident ID
2. se Owner = Unassigned -> Assign to me + Apply + verifica
3. se Status = New -> Active + verifica
4. Refresh Sentinel
5. passa all'ID successivo
```


## Zoom/screen safe status + SLA local time fix

Questa release corregge tre punti:

### 1. Status Active non cliccato

Il bot non usa più coordinate fisse per Owner/Status.
Ora cerca la label nella detail pane:

```text
Owner  -> clicca il valore sopra la label Owner
Status -> clicca il valore sopra la label Status
```

Questo dovrebbe funzionare anche con zoom diverso dal 100% e su monitor con dimensioni diverse.

### 2. Status Active immediato dopo Assign

Dopo `Assign to me + Apply`, il bot controlla subito lo stesso incident ID e, se lo Status è ancora `New`, apre il menu Status e seleziona `Active`.

Dopo `Active` verificato, preme Refresh sulla toolbar Sentinel.

### 3. SLA Remaining

Il calcolo dei minuti rimanenti ora usa l'ora locale del browser/macchina, non UTC. Sentinel mostra gli orari nella UI come orari locali, quindi il calcolo precedente poteva risultare sfasato.


## Persistent SLA popup + saved settings

This release changes SLA notifications:

```text
- SLA notification is based on Created time
- notification triggers when elapsed time reaches the configured percentage, e.g. 60%
- Windows toast/beep is still used
- the desktop app also opens a persistent topmost popup
- the popup closes only when the user clicks ACKNOWLEDGE
```

The incidents table now includes:

```text
Last Notified
```

SLA settings are now persisted in the local SQLite database:

```text
data/bot_state.sqlite3
```

When you reopen the app, saved SLA values are automatically restored.


## Last Notified local time + skip other owners

This release changes two final behaviors.

### Last Notified

`Last Notified` now uses the system local timestamp and displays only:

```text
HH:MM
```

Example:

```text
14:37
```

The repeat-notification logic also uses the system-local timestamp for newly generated notifications.

### Assigned to other users

The bot no longer changes incidents assigned to another user.

Rule:

```text
Owner = Unassigned
    -> Assign to me
    -> then Set Active

Owner = me
    -> may Set Active if Status is New

Owner = someone else
    -> do not assign
    -> do not change status
```

The bot learns the current user's owner display name after a successful `Assign to me` and saves it locally in:

```text
data/bot_state.sqlite3
```

So the behavior is kept after reopening the app.
