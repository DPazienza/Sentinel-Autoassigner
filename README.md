# Sentinel Auto Assign Bot - Desktop App

Applicazione desktop Windows per aiutare il SOC nella gestione operativa degli incident Microsoft Sentinel direttamente dalla pagina web del portale Azure, senza usare API.

L'app si collega a una tab Sentinel già aperta su Chrome o Edge, legge gli incident visibili nella vista corrente, può assegnare automaticamente gli incident `Unassigned` all'utente corrente, portarli in `Active` e monitorare gli SLA/KPI principali.

---

## 1. Cosa fa il bot

Il bot lavora sulla vista `Microsoft Sentinel > Incidents` aperta nel browser.

Funzioni principali:

```text
- legge gli incident visibili nella tab Sentinel selezionata
- popola una dashboard locale con ID, severity, status, owner, title e timestamp
- assegna a te gli incident con Owner = Unassigned
- mette in Active gli incident assegnati a te se Status = New
- non tocca incident assegnati ad altri utenti
- monitora i KPI Taking Charge e Notification
- mostra popup persistenti per notifiche SLA
- salva configurazione SLA e owner locale nel database dell'app
```

Il bot non usa API Sentinel/Azure. Opera solo tramite interazione controllata con la pagina web.

---

## 2. Browser supportati

Supportati:

```text
Google Chrome
Microsoft Edge
```

Non supportato:

```text
Firefox
```

Firefox non espone in modo affidabile lo stesso protocollo di controllo usato da Chrome/Edge per agganciarsi a una tab già aperta.

---

## 3. File inclusi

Dopo l'estrazione dello ZIP trovi:

```text
app.py
requirements.txt
install_windows.bat
run_desktop_app_windows.bat
run_desktop_app_debug_console_windows.bat
run_desktop_app_hidden_windows.vbs
reset_local_state_windows.bat
start_chrome_debug_windows.bat
start_edge_debug_windows.bat
README.md
```

Uso normale:

```text
install_windows.bat
run_desktop_app_windows.bat
```

Uso debug:

```text
run_desktop_app_debug_console_windows.bat
```

Reset stato locale:

```text
reset_local_state_windows.bat
```

---

## 4. Installazione

### Requisiti

Serve Python 3.10 o superiore installato su Windows.

Durante l'installazione di Python deve essere abilitata l'opzione:

```text
Add python.exe to PATH
```

### Procedura

1. Estrai lo ZIP in una cartella locale.
2. Apri la cartella estratta.
3. Esegui:

```text
install_windows.bat
```

L'installer crea un virtual environment `.venv` e installa le dipendenze necessarie.

---

## 5. Avvio dell'app

Per uso normale esegui:

```text
run_desktop_app_windows.bat
```

Questo avvia l'app senza lasciare una shell aperta.

Per vedere eventuali errori in console usa:

```text
run_desktop_app_debug_console_windows.bat
```

La finestra dell'app può essere chiusa con la `X`. La chiusura termina anche il processo Python.

---

## 6. Primo collegamento a Sentinel

Flusso consigliato:

```text
1. Avvia l'app
2. Clicca Launch Chrome for bot oppure Launch Edge for bot
3. Fai login su Azure
4. Accetta MFA
5. Attiva eventuale PIM
6. Vai su Microsoft Sentinel > Incidents
7. Premi Refresh browser tabs se la tab non compare
8. Seleziona la tab Sentinel corretta nella tabella Browser / workspace selection
9. Premi FETCH CURRENT VIEW NOW
```

Se la tab viene letta correttamente, gli incident appaiono nella dashboard.

---

## 7. Sezione Browser / workspace selection

Questa sezione mostra le tab browser agganciate al bot.

Colonne:

```text
Browser
Sentinel
Title
Url
```

Usala per selezionare la tab Sentinel corretta, soprattutto se hai più workspace o più browser aperti.

Se cambi workspace o tab, premi:

```text
Refresh browser tabs
```

e seleziona di nuovo la tab corretta.

---

## 8. Bot controls

### FETCH CURRENT VIEW NOW

Legge gli incident visibili nella pagina Sentinel selezionata e aggiorna la dashboard.

Non modifica nulla su Sentinel.

Non cambia:

```text
owner
status
filtri
incident
```

Serve per verificare che il bot stia leggendo correttamente la vista corrente.

### START REAL BOT

Avvia il bot in modalità reale.

Il bot esegue questa logica:

```text
Per ogni incident visibile:
    se Owner = Unassigned:
        Assign to me
        Apply
        verifica owner

    se Owner = me e Status = New:
        Status = Active
        verifica status

    se Owner = qualcun altro:
        skip
```

Il bot usa sempre l'Incident ID come riferimento. Se la lista cambia ordine, cerca di nuovo l'ID prima di agire.

### START DRY-RUN

Avvia una simulazione.

Il bot legge cosa farebbe, ma non modifica Sentinel.

Da usare prima della modalità reale quando vuoi testare la logica.

### PAUSE

Mette in pausa il bot.

La pausa ha effetto prima del prossimo incident.

### RESUME

Riprende il bot dopo una pausa.

### STOP

Ferma il ciclo automatico.

L'app resta aperta e puoi continuare a usare `FETCH CURRENT VIEW NOW`.

---

## 9. Regole di sicurezza operative

Il bot rispetta queste regole:

```text
Owner = Unassigned
    -> il bot può assegnarlo a te

Owner = me
    -> il bot può metterlo in Active se è ancora New

Owner = altro utente
    -> il bot non assegna
    -> il bot non cambia status
    -> skip
```

Il bot impara automaticamente il tuo owner display name dopo un `Assign to me` riuscito e lo salva localmente.

---

## 10. SLA / KPI gestiti

Il bot gestisce due KPI operativi:

```text
Taking Charge Time
Notification Time
```

### Taking Charge Time

Indica entro quanto un incident deve essere preso in carico.

Default:

```text
Critical: 30 min
High:     30 min
Medium:   60 min
Low:      60 min
Info:     60 min fallback
```

### Notification Time

Indica entro quanto deve partire la notifica popup all'utente.

Default:

```text
Critical: 30 min
High:     60 min
Medium:   240 min
Low:      480 min
Info:     480 min fallback
```

Il popup SLA usa il KPI `Notification Time`, non una percentuale del Taking Charge.

---

## 11. Sezione SLA settings

La sezione permette di modificare i valori in minuti.

Campi principali:

```text
Taking Charge:
    Crit
    High
    Med
    Low
    Info

Notification:
    Crit
    High
    Med
    Low
    Info

Bot:
    Scan sec
    Repeat min
    Auto fetch
```

### Scan sec

Intervallo del bot quando è avviato in modalità reale o dry-run.

### Repeat min

Dopo quanti minuti può essere ripetuta una notifica SLA già inviata per lo stesso incident.

### Auto fetch

Intervallo di aggiornamento automatico della dashboard quando il bot non è in esecuzione.

Dopo aver modificato i valori premi:

```text
SAVE SLA SETTINGS
```

Le impostazioni vengono salvate localmente e restano disponibili anche dopo la riapertura dell'app.

---

## 12. Dashboard incident

La tabella `Incidents seen by bot` mostra gli incident visibili nella vista Sentinel corrente.

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

### Min To Taking Charge

Minuti mancanti alla scadenza del KPI Taking Charge.

Se la soglia è già superata mostra:

```text
OVERDUE X min
```

### Min To Notify

Minuti mancanti alla scadenza del KPI Notification.

Quando viene raggiunta questa soglia, il bot mostra il popup SLA.

### Last Notified

Ora dell'ultima notifica inviata dal bot per quell'incident.

Formato:

```text
HH:MM
```

---

## 13. Notifiche SLA

Quando un incident supera il KPI Notification, il bot mostra:

```text
popup persistente nell'app
toast/beep Windows
```

Il popup persistente resta visibile finché l'utente non clicca:

```text
ACKNOWLEDGE
```

La notifica viene registrata nella colonna:

```text
Last Notified
```

---

## 14. Actions / logs

La tab `Actions / logs` mostra le operazioni eseguite o simulate dal bot.

Esempi:

```text
FETCH
DRY_RUN
ASSIGN_TO_ME
SET_ACTIVE
SLA_WARNING
SKIP_OTHER_OWNER
```

Usala per capire cosa ha fatto il bot su ogni incident.

---

## 15. Sincronizzazione dashboard

Dopo ogni fetch o scan, la dashboard viene sincronizzata con la vista Sentinel corrente.

Se un incident non è più visibile perché è stato chiuso o filtrato fuori, viene rimosso dalla dashboard locale.

Il bot non cancella nulla da Sentinel. Rimuove solo la riga dalla dashboard locale.

---

## 16. Stato locale

L'app salva dati locali in:

```text
data/bot_state.sqlite3
```

Contiene:

```text
incident letti
azioni/log
ultimo timestamp di notifica
SLA configurati
owner display name dell'utente
```

Per resettare lo stato locale:

```text
reset_local_state_windows.bat
```

---

## 17. Uso consigliato

Flusso sicuro:

```text
1. Avvia l'app
2. Lancia Chrome/Edge dal bottone dell'app
3. Login Azure + MFA + PIM
4. Apri Sentinel > Incidents
5. Premi FETCH CURRENT VIEW NOW
6. Verifica la dashboard
7. Premi START DRY-RUN
8. Controlla Actions / logs
9. Premi START REAL BOT
```

---

## 18. Troubleshooting

### La tab Sentinel non compare

Premi:

```text
Refresh browser tabs
```

Se ancora non compare:

```text
1. Chiudi Chrome/Edge
2. Riapri il browser dal bottone dell'app
3. Fai login
4. Torna su Sentinel > Incidents
5. Premi Refresh browser tabs
```

### Il bot legge incident vecchi o chiusi

Premi:

```text
FETCH CURRENT VIEW NOW
```

La dashboard si riallinea con la vista Sentinel corrente.

### Il bot non assegna un incident

Controlla `Owner`.

Se l'incident è assegnato a un altro utente, il bot lo salta volutamente.

### Il bot non mette in Active

Controlla che l'incident sia assegnato a te.

Il bot cambia status solo se:

```text
Owner = me
Status = New
```

### Voglio vedere errori tecnici

Avvia:

```text
run_desktop_app_debug_console_windows.bat
```

---

## 19. Nota operativa

Il bot lavora solo sugli incident visibili nella vista Sentinel selezionata.

Quindi filtri, severity, status e workspace impostati in Sentinel determinano cosa il bot vede e processa.
