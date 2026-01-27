from django.shortcuts import render, redirect, get_object_or_404
from .models import Partita, Frase, Giocatore
from .utils import gira_la_ruota_logic, SPICCHI_RUOTA
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from django.http import HttpResponse
from django.core.management import call_command
from django.contrib.auth.models import User

def setup_partita(request):
    # --- PULIZIA SESSIONE (FIX IMPORTANTE) ---
    # Questo cancella eventuali residui di partite precedenti appena arrivi alla home
    keys_to_clear = ['round_vinto', 'valore_ruota', 'messaggio', 'partita_id', 'rotazione_ruota']
    for key in keys_to_clear:
        if key in request.session:
            del request.session[key]
    # -----------------------------------------

    if request.method == "POST":
        nomi = request.POST.getlist('nomi_giocatori')
        nomi = [n for n in nomi if n.strip()]
        
        if len(nomi) < 1:
            return render(request, 'game/setup.html', {'error': 'Inserisci almeno un giocatore'})

        frase_random = Frase.objects.order_by('?').first()
        # Creiamo la partita impostando esplicitamente i default
        partita = Partita.objects.create(
            frase_corrente=frase_random,
            numero_round=1,
            totale_rounds=3
        )
        
        for nome in nomi:
            Giocatore.objects.create(partita=partita, nome=nome)
            
        request.session['partita_id'] = partita.id
        request.session['valore_ruota'] = 0
        request.session['round_vinto'] = False # Si assicura che parta falso
        return redirect('gioco')
        
    return render(request, 'game/setup.html')

def gioco(request):
    partita_id = request.session.get('partita_id')
    if not partita_id: return redirect('setup_partita')
    partita = get_object_or_404(Partita, id=partita_id)
    
    giocatori = partita.giocatori.all()
    if partita.turno_corrente >= len(giocatori):
        partita.turno_corrente = 0
        partita.save()
        
    giocatore_corrente = giocatori[partita.turno_corrente]

    valore_ruota = request.session.get('valore_ruota', 0)
    messaggio = request.session.pop('messaggio', '')
    
    if request.session.get('round_vinto'):
        # Se vinto, mostriamo tutto. Creiamo la struttura a parole manualmente.
        tabellone = []
        for parola_raw in partita.frase_corrente.testo.upper().split(' '):
            parola_obj = [{'char': c, 'visibile': True} for c in parola_raw]
            tabellone.append(parola_obj)
    else:
        # Usa il nuovo metodo che raggruppa per parole
        tabellone = partita.get_tabellone_a_parole()


    context = {
        'tabellone': tabellone,
        'partita': partita,
        'giocatori': giocatori,
        'giocatore_corrente': giocatore_corrente,
        'valore_ruota': valore_ruota,
        'messaggio': messaggio,
    }
    return render(request, 'game/gioco.html', context)

def azione_gioco(request):
    if request.method != 'POST': return redirect('gioco')
    
    partita = get_object_or_404(Partita, id=request.session['partita_id'])
    giocatori = list(partita.giocatori.all())
    giocatore_attivo = giocatori[partita.turno_corrente]
    tipo = request.POST.get('tipo')

    # Recuperiamo il valore (che potrebbe essere PASSA/BANCAROTTA ma è già stato gestito)
    valore_ruota = request.session.get('valore_ruota', 0)

    # Se l'utente sta cercando di fare un'azione ma il turno è passato (es. ricaricamento strano)
    # blocchiamo tutto, ma nel flusso normale non dovrebbe succedere.
    
    if tipo == 'lettera':
        lettera = request.POST.get('lettera_input', '').upper().strip()
        vocali = "AEIOU"
        
        if not lettera: return redirect('gioco')

        # --- CONTROLLO GLOBALE: LETTERA GIÀ CHIAMATA ---
        if lettera in partita.lettere_chiamate:
             request.session['messaggio'] = f"La lettera '{lettera}' è già stata detta! PERDI IL TURNO."
             # PENALITÀ: CAMBIO TURNO
             partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
             partita.save()
             request.session['valore_ruota'] = 0 
             return redirect('gioco')

        # Se per qualche motivo il valore è ancora Passa/Bancarotta (bug visivo), impediamo azioni
        if valore_ruota in ['PASSA', 'BANCAROTTA']:
             request.session['messaggio'] = "Il turno è passato!"
             return redirect('gioco')

        if tipo == 'tempo_scaduto':
            request.session['messaggio'] = f"⏰ TEMPO SCADUTO! {giocatore_attivo.nome} è stato troppo lento."
            partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
            partita.save()
            request.session['valore_ruota'] = 0 # Reset ruota
            return redirect('gioco')
    

        if lettera in vocali:
            # COMPRA VOCALE
            if giocatore_attivo.punteggio < 500:
                request.session['messaggio'] = "Non hai 500€ per la vocale!"
                return redirect('gioco')
            
            giocatore_attivo.punteggio -= 500
            giocatore_attivo.save()
            
            if lettera in partita.lettere_chiamate:
                 request.session['messaggio'] = "Vocale già chiamata!"
            else:
                partita.lettere_chiamate += lettera
                partita.save()
                
                if lettera not in partita.frase_corrente.testo.upper():
                    request.session['messaggio'] = f"La vocale '{lettera}' non c'è. Cambio turno."
                    partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                    partita.save()
                else:
                    request.session['messaggio'] = f"VOCALE COMPRATA: '{lettera}' è presente!"

        else: 
            # CHIAMA CONSONANTE
            if valore_ruota == 0:
                 request.session['messaggio'] = "Devi girare la ruota!"
                 return redirect('gioco')

            if lettera in partita.lettere_chiamate:
                request.session['messaggio'] = "Lettera già chiamata!"
            else:
                partita.lettere_chiamate += lettera
                occorrenze = partita.frase_corrente.testo.upper().count(lettera)
                
                if occorrenze > 0:
                    try:
                        vincita = int(valore_ruota) * occorrenze
                        giocatore_attivo.punteggio += vincita
                        giocatore_attivo.save()
                        request.session['messaggio'] = f"Sì! {occorrenze} '{lettera}'. Hai vinto {vincita}€."
                    except ValueError:
                        pass
                else:
                    request.session['messaggio'] = f"La lettera '{lettera}' non c'è. Cambio turno."
                    partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                    partita.save()
                
                partita.save()
                request.session['valore_ruota'] = 0 # Reset ruota

    elif tipo == 'soluzione':
        tentativo = request.POST.get('soluzione_input', '').upper().strip()
        soluzione_reale = partita.frase_corrente.testo.upper().strip()
        
        if tentativo == soluzione_reale:
            # VITTORIA!
            partita.vincitore = giocatore_attivo.nome 
            # RIMOSSO: partita.lettere_chiamate = "TUTTE"  <-- Questa riga va cancellata!
            partita.save()
            request.session['messaggio'] = f"CAMPIONE! {giocatore_attivo.nome} ha indovinato la frase!"
            request.session['round_vinto'] = True 
        else:
            # ERRORE
            request.session['messaggio'] = f"No! '{tentativo}' è sbagliata! Cambio turno."
            partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
            partita.save()

    return redirect('gioco')

def api_gira_ruota(request):
    partita = get_object_or_404(Partita, id=request.session['partita_id'])
    giocatori = list(partita.giocatori.all())
    giocatore_attivo = giocatori[partita.turno_corrente]

    valore, rotazione_target = gira_la_ruota_logic()
    request.session['valore_ruota'] = valore
    
    if valore == 'PASSA':
        partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
        partita.save()
        request.session['messaggio'] = f"PASSA LA MANO! {giocatore_attivo.nome} salta il turno."
        
    elif valore == 'BANCAROTTA':
        # PERDI SOLO I SOLDI DEL ROUND! Quelli "in banca" sono salvi.
        giocatore_attivo.montepremi_round = 0 
        giocatore_attivo.save()
        
        partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
        partita.save()
        request.session['messaggio'] = f"BANCAROTTA! {giocatore_attivo.nome} perde il bottino del round."
    
    return JsonResponse({'valore': valore, 'gradi_finali': rotazione_target})


def azione_gioco(request):
    if request.method != 'POST': return redirect('gioco')
    
    partita = get_object_or_404(Partita, id=request.session['partita_id'])
    giocatori = list(partita.giocatori.all())
    giocatore_attivo = giocatori[partita.turno_corrente]
    tipo = request.POST.get('tipo')
    valore_ruota = request.session.get('valore_ruota', 0)

    # --- TIMEOUT ---
    if tipo == 'tempo_scaduto':
        request.session['messaggio'] = f"⏰ TEMPO SCADUTO! {giocatore_attivo.nome} passa la mano."
        partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
        partita.save()
        request.session['valore_ruota'] = 0
        return redirect('gioco')

    # --- LETTERA ---
    if tipo == 'lettera':
        lettera = request.POST.get('lettera_input', '').upper().strip()
        vocali = "AEIOU"
        
        if not lettera: return redirect('gioco')

        if lettera in vocali:
            # VOCALE: Si paga usando i soldi del round (o della banca se servono?)
            # Regola TV: Solitamente si scala dal montepremi del round.
            if giocatore_attivo.montepremi_round < 500:
                 # Opzionale: se non ha soldi nel round, controlliamo la banca?
                 # Per ora manteniamo la regola rigida: servono soldi liquidi nel round.
                 request.session['messaggio'] = "Non hai 500€ nel montepremi di questo round!"
                 return redirect('gioco')
            
            giocatore_attivo.montepremi_round -= 500
            giocatore_attivo.save()
            
            if lettera in partita.lettere_chiamate:
                 request.session['messaggio'] = "Vocale già chiamata!"
            else:
                partita.lettere_chiamate += lettera
                partita.save()
                if lettera not in partita.frase_corrente.testo.upper():
                    request.session['messaggio'] = f"La vocale '{lettera}' non c'è. Cambio turno."
                    partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                    partita.save()
                else:
                    request.session['messaggio'] = f"VOCALE COMPRATA: '{lettera}' presente!"

        else: # CONSONANTE
            if valore_ruota == 0 or valore_ruota in ['PASSA', 'BANCAROTTA']:
                 request.session['messaggio'] = "Devi girare la ruota!"
                 return redirect('gioco')

            if lettera in partita.lettere_chiamate:
                request.session['messaggio'] = "Lettera già chiamata!"
            else:
                partita.lettere_chiamate += lettera
                occorrenze = partita.frase_corrente.testo.upper().count(lettera)
                
                if occorrenze > 0:
                    try:
                        # AGGIUNGIAMO AL MONTEPREMI DEL ROUND (NON TOTALE)
                        vincita = int(valore_ruota) * occorrenze
                        giocatore_attivo.montepremi_round += vincita
                        giocatore_attivo.save()
                        request.session['messaggio'] = f"Sì! {occorrenze} '{lettera}'. Aggiunti {vincita}€ al parziale."
                    except ValueError: pass
                else:
                    request.session['messaggio'] = f"La lettera '{lettera}' non c'è. Cambio turno."
                    partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                    partita.save()
                
                partita.save()
                request.session['valore_ruota'] = 0 

    # --- SOLUZIONE (IL MOMENTO DELLA VERITÀ) ---
    elif tipo == 'soluzione':
        tentativo = request.POST.get('soluzione_input', '').upper().strip()
        soluzione_reale = partita.frase_corrente.testo.upper().strip()
        
        if tentativo == soluzione_reale:
            # VITTORIA DEL ROUND!
            # 1. Il vincitore sposta il parziale in banca
            soldi_vinti = giocatore_attivo.montepremi_round
            giocatore_attivo.punteggio += soldi_vinti
            giocatore_attivo.save()
            
            # 2. TUTTI GLI ALTRI perdono il parziale del round!
            for g in giocatori:
                g.montepremi_round = 0
                g.save()
            
            partita.vincitore = giocatore_attivo.nome 
            partita.save()
            request.session['messaggio'] = f"CAMPIONE! {giocatore_attivo.nome} vince il round e incassa {soldi_vinti}€!"
            request.session['round_vinto'] = True 
        else:
            request.session['messaggio'] = f"No! '{tentativo}' è sbagliata! Cambio turno."
            partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
            partita.save()

    return redirect('gioco')

def prossimo_round(request):
    partita_id = request.session.get('partita_id')
    if not partita_id: return redirect('setup_partita')
    partita = get_object_or_404(Partita, id=request.session['partita_id'])

    # Reset Montepremi Round per tutti (Sicurezza)
    for g in partita.giocatori.all():
        g.montepremi_round = 0
        g.save()
    
    # CONTROLLO FINE GIOCO
    if partita.numero_round >= partita.totale_rounds:
        return redirect('fine_partita')
    
    # Se non è finito, incrementa round
    partita.numero_round += 1
    
    # Prende una nuova frase
    nuova_frase = Frase.objects.exclude(id=partita.frase_corrente.id).order_by('?').first()
    if not nuova_frase:
         request.session['messaggio'] = "Frasi finite! Ricarica il DB."
         return redirect('gioco')

    # Reset per nuovo round
    partita.frase_corrente = nuova_frase
    partita.lettere_chiamate = ""
    partita.vincitore = None # Nessuno ha vinto ancora questo round specifico
    partita.save()
    
    request.session['valore_ruota'] = 0
    request.session['round_vinto'] = False
    request.session['messaggio'] = f"Siamo al Round {partita.numero_round} di {partita.totale_rounds}!"
    
    return redirect('gioco')

def fine_partita(request):
    partita_id = request.session.get('partita_id')
    if not partita_id: return redirect('setup_partita')
    partita = get_object_or_404(Partita, id=partita_id)
    
    # Ordiniamo i giocatori dal più ricco al più povero
    classifica = partita.giocatori.all().order_by('-punteggio')
    vincitore_assoluto = classifica.first()
    
    return render(request, 'game/fine_partita.html', {
        'classifica': classifica,
        'vincitore': vincitore_assoluto
    })


def installazione_segreta(request):
    # 1. Popola il Database (chiama il comando che abbiamo creato)
    try:
        call_command('popola_db')
        msg_db = "Database popolato con successo.<br>"
    except Exception as e:
        msg_db = f"Errore popolamento DB: {e}<br>"

    # 2. Crea il Superuser (se non esiste già)
    # USER: admin
    # PASS: admin123
    if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
        msg_user = "Superuser 'admin' creato con password 'admin123'.<br>"
    else:
        msg_user = "Superuser 'admin' esisteva già.<br>"

    # 3. Imposta i Round di default (se non esistono)
    # (ConfigurazioneGioco viene importato, assicurati che ci sia l'import in alto o fallo qui)
    from .models import ConfigurazioneGioco
    if not ConfigurazioneGioco.objects.exists():
        ConfigurazioneGioco.objects.create(numero_round_per_partita=3)
        msg_conf = "Configurazione round impostata a 3.<br>"
    else:
        msg_conf = "Configurazione round già presente.<br>"

    return HttpResponse(f"<h1>Installazione Completata!</h1>{msg_db}{msg_user}{msg_conf} <a href='/admin'>VAI ALL'ADMIN</a>")