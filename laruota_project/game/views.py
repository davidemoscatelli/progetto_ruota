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
    
    # --- FIX CRITICO: SICUREZZA INDICI ---
    # Se per qualche motivo (es. cambio round) l'indice è fuori scala, lo resettiamo a 0
    if not giocatori or partita.turno_corrente >= len(giocatori):
        partita.turno_corrente = 0
        partita.save()
    
    giocatore_corrente = giocatori[partita.turno_corrente]
    valore_ruota = request.session.get('valore_ruota', 0)
    messaggio = request.session.pop('messaggio', '')
    
    # Costruzione Tabellone
    if request.session.get('round_vinto'):
        tabellone = []
        for parola_raw in partita.frase_corrente.testo.upper().split(' '):
            parola_obj = [{'char': c, 'visibile': True} for c in parola_raw]
            tabellone.append(parola_obj)
    else:
        tabellone = partita.get_tabellone_a_parole()

    context = {
        'partita': partita,
        'tabellone': tabellone,
        'giocatori': giocatori,
        'giocatore_corrente': giocatore_corrente,
        'valore_ruota': valore_ruota,
        'messaggio': messaggio,
    }
    return render(request, 'game/gioco.html', context)

def azione_gioco(request):
    partita_id = request.session.get('partita_id')
    partita = get_object_or_404(Partita, id=partita_id)
    giocatori = partita.giocatori.all()
    
    # FIX INDICI: Se l'indice è fuori scala, resetta a 0
    if partita.turno_corrente >= len(giocatori):
        partita.turno_corrente = 0
        partita.save()
        
    giocatore_attivo = giocatori[partita.turno_corrente]
    
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        valore_ruota = request.session.get('valore_ruota', 0)
        vocali = "AEIOU"

        # --- CASO 1: TIMEOUT ---
        if tipo == 'tempo_scaduto':
            request.session['messaggio'] = f"⏰ TEMPO SCADUTO! Tocca al prossimo."
            request.session['valore_ruota'] = 0
            partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
            partita.save()
            return redirect('gioco')

        # --- CASO 2: TENTATIVO SOLUZIONE ---
        if tipo == 'soluzione':
            soluzione = request.POST.get('soluzione_input', '').upper().strip()
            if soluzione == partita.frase_corrente.testo.upper():
                request.session['round_vinto'] = True
                request.session['messaggio'] = f"🏆 {giocatore_attivo.nome} HA VINTO IL ROUND!"
                giocatore_attivo.punteggio += giocatore_attivo.montepremi_round
                giocatore_attivo.save()
            else:
                request.session['messaggio'] = f"❌ Soluzione errata! Perdi turno e montepremi parziale."
                giocatore_attivo.montepremi_round = 0
                giocatore_attivo.save()
                partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                partita.save()
                request.session['valore_ruota'] = 0
            return redirect('gioco')

        # --- CASO 3: LETTERA (Consonante o Vocale) ---
        elif tipo == 'lettera':
            lettera = request.POST.get('lettera_input', '').upper().strip()
            
            # Validazione base
            if not lettera or len(lettera) > 1 or not lettera.isalpha():
                return redirect('gioco')

            # Lettera già detta? -> CAMBIO TURNO
            if lettera in partita.lettere_chiamate:
                request.session['messaggio'] = f"⚠️ La lettera '{lettera}' è già uscita! Passi il turno."
                partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                request.session['valore_ruota'] = 0
                partita.save()
                return redirect('gioco')

            is_vocale = lettera in vocali

            # --- A) È UNA VOCALE ---
            if is_vocale:
                if giocatore_attivo.montepremi_round < 500:
                    request.session['messaggio'] = "🚫 Non hai 500€ per la vocale!"
                    return redirect('gioco')
                
                # Pagamento
                giocatore_attivo.montepremi_round -= 500
                giocatore_attivo.save()
                partita.lettere_chiamate += lettera
                
                if lettera in partita.frase_corrente.testo.upper():
                    request.session['messaggio'] = f"✅ VOCALE TROVATA! Continua a giocare."
                    # NON CAMBIA IL TURNO
                else:
                    request.session['messaggio'] = f"❌ La vocale '{lettera}' non c'è. Cambio turno."
                    partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                
                partita.save()

            # --- B) È UNA CONSONANTE ---
            else:
                # Obbligo giro ruota
                if valore_ruota == 0 or valore_ruota in ['PASSA', 'BANCAROTTA']:
                    request.session['messaggio'] = "🌀 Devi prima girare la ruota!"
                    return redirect('gioco')

                partita.lettere_chiamate += lettera
                occorrenze = partita.frase_corrente.testo.upper().count(lettera)

                if occorrenze > 0:
                    # LETTERA PRESENTE
                    try:
                        vincita = int(valore_ruota) * occorrenze
                        giocatore_attivo.montepremi_round += vincita
                        giocatore_attivo.save()
                        request.session['messaggio'] = f"🎉 TROVATE {occorrenze} '{lettera}'! Vinci {vincita}€. GIRA ANCORA!"
                        
                        # Resetta la ruota (deve rigirare) ma NON CAMBIA TURNO
                        request.session['valore_ruota'] = 0 
                    except ValueError: pass
                else:
                    # LETTERA ASSENTE
                    request.session['messaggio'] = f"❌ La lettera '{lettera}' non c'è. Tocca al prossimo."
                    partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                    request.session['valore_ruota'] = 0 
                
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
    partita = get_object_or_404(Partita, id=partita_id)
    
    # Reset variabili per il nuovo round
    partita.numero_round += 1
    
    # BUG FIX: Reset del turno al primo giocatore o al vincitore (qui mettiamo 0 per semplicità)
    # Oppure: (partita.turno_corrente + 1) % n se vuoi ruotare chi inizia
    partita.turno_corrente = 0 
    
    partita.lettere_chiamate = ""
    
    # Nuova frase
    frasi_usate_ids = request.session.get('frasi_usate', [])
    if partita.frase_corrente:
        frasi_usate_ids.append(partita.frase_corrente.id)
    
    nuova_frase = Frase.objects.exclude(id__in=frasi_usate_ids).order_by('?').first()
    
    if nuova_frase and partita.numero_round <= partita.totale_rounds:
        partita.frase_corrente = nuova_frase
        partita.save()
        request.session['frasi_usate'] = frasi_usate_ids
        request.session['round_vinto'] = False
        request.session['valore_ruota'] = 0
        request.session['messaggio'] = f"Inizia il Round {partita.numero_round}!"
        
        # Reset montepremi parziale dei giocatori
        for g in partita.giocatori.all():
            g.montepremi_round = 0
            g.save()
            
        return redirect('gioco')
    else:
        return redirect('fine_partita')

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


