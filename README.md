# Sentinel Auto Assign Bot - Desktop App

Applicazione desktop Windows per supportare la presa in carico degli incident Microsoft Sentinel usando la pagina web del portale Azure, senza API Sentinel/Azure.

Il bot si collega a una tab Sentinel già aperta su Chrome o Edge, legge gli incident visibili nella vista corrente, assegna all'utente corrente gli incident non assegnati e monitora i KPI operativi configurati.

---

## 1. Scopo dell'app

Funzioni principali:

```text
- lettura degli incident visibili nella pagina Sentinel Incidents
- dashboard locale degli incident letti
- assegnazione automatica degli incident Unassigned
- cambio Status da New ad Active solo per incident assegnati a te
- skip degli incident assegnati ad altri utenti
- monitoraggio Taking Charge Time
- monitoraggio Notification Time
- popup persistente quando viene raggiunto il Notification Time
- salvataggio locale delle impostazioni
```

---

## 2. Requisiti

```text
Windows
Python 3.10 o superiore
Google Chrome oppure Microsoft Edge
```

Firefox non è supportato.

Durante l'installazione di Python abilita:

```text
Add python.exe to PATH
```

---

## 3. Installazione

1. Estrai lo ZIP in una cartella locale.
2. Entra nella cartella estratta.
3. Esegui:

```text
install_windows.bat
```

---

## 4. Avvio

Uso normale:

```text
run_desktop_app_windows.bat
```

Uso con console di debug:

```text
run_desktop_app_debug_console_windows.bat
```

Reset dello stato locale:

```text
reset_local_state_windows.bat
```

---

## 5. Collegamento a Sentinel

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

## 6. Uso dei controlli

### FETCH CURRENT VIEW NOW

Legge la vista Sentinel corrente e aggiorna la dashboard. Non modifica Sentinel.

### START DRY-RUN

Simula cosa farebbe il bot, senza modificare Owner o Status.

### START REAL BOT

Avvia la modalità reale.

Il bot può:

```text
- assegnare a te incident con Owner = Unassigned
- mettere Active incident assegnati a te con Status = New
```

### PAUSE / RESUME / STOP

Pausa, riprende o ferma il ciclo automatico.

---

## 7. Logica Owner / Status

Regola operativa:

```text
Owner = Unassigned
    -> Assign to me
    -> verifica Owner
    -> se Status = New, imposta Active

Owner = me
    -> se Status = New, imposta Active

Owner = altro utente
    -> skip
    -> non cambia Owner
    -> non cambia Status
```

Il bot impara il tuo Owner display name dopo un `Assign to me` riuscito e lo salva localmente.

Il confronto Owner è stretto: il bot considera "me" solo un match esatto normalizzato con il nome salvato. Non usa match parziali.

---

## 8. KPI gestiti

### Taking Charge Time

Serve per verificare entro quanto un incident viene preso in carico.

```text
Critical: 30 min
High:     30 min
Medium:   60 min
Low:      60 min
Info:     60 min
```

### Notification Time

Serve per decidere quando mostrare il popup persistente.

```text
Critical: 30 min
High:     60 min
Medium:   240 min
Low:      480 min
Info:     480 min
```

Il popup usa il Notification Time, non una percentuale del Taking Charge.

---

## 9. Dashboard

La tab `Incidents seen by bot` mostra:

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

Valori `OVERDUE` indicano che il KPI è già superato.

---

## 10. Notifiche

Quando un incident raggiunge il Notification Time, il bot mostra:

```text
- popup persistente nell'app
- notifica/beep Windows
```

Il popup resta visibile finché non clicchi:

```text
ACKNOWLEDGE
```

La colonna `Last Notified` mostra solo ora e minuti:

```text
HH:MM
```

---

## 11. Log operativi

La tab `Actions / logs` mostra le azioni registrate.

Esempi:

```text
FETCH
DRY_RUN
ASSIGN_TO_ME
SET_ACTIVE
SKIP_OTHER_OWNER
SLA_NOTIFICATION
```

---

## 12. Stato locale

L'app salva lo stato in:

```text
data/bot_state.sqlite3
```

Contiene incident letti, azioni/log, configurazioni KPI, timestamp notifiche e Owner display name dell'utente.

---

## 13. Procedura consigliata

```text
1. Avvia app
2. Lancia Chrome/Edge dal bottone dell'app
3. Login Azure + MFA + PIM
4. Apri Sentinel > Incidents
5. Premi FETCH CURRENT VIEW NOW
6. Controlla la dashboard
7. Premi START DRY-RUN
8. Verifica Actions / logs
9. Premi START REAL BOT
```

---

## 14. Troubleshooting

### La tab Sentinel non compare

```text
1. Premi Refresh browser tabs
2. Se non basta, chiudi il browser bot
3. Riapri con Launch Chrome/Edge for bot
4. Rifai login e torna su Sentinel > Incidents
```

### Gli incident chiusi restano in dashboard

Premi:

```text
FETCH CURRENT VIEW NOW
```

La dashboard rimuove gli incident non più presenti nella vista corrente quando la lettura contiene almeno un incident valido.

### Il bot non assegna un incident

Controlla Owner. Se è già assegnato a un altro utente, è corretto che il bot lo salti.

### Il bot non mette Active

Il bot mette Active solo se:

```text
Owner = me
Status = New
```

### Voglio vedere errori tecnici

Usa:

```text
run_desktop_app_debug_console_windows.bat
```

---

## Nota finale

Il bot lavora sulla vista Sentinel selezionata. Filtri, workspace e colonne visibili in Sentinel influenzano cosa il bot legge e processa.
