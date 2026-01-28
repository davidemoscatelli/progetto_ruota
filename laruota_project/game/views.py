from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from .models import Partita, Frase, Giocatore, ConfigurazioneGioco
from .utils import gira_la_ruota_logic
import sys # Serve per stampare i log su Render

# -------------------------------------------------------------------------
# 1. SETUP
# -------------------------------------------------------------------------
def setup_partita(request):
    request.session.flush() 
    
    if request.method == "POST":
        nomi = request.POST.getlist('nomi_giocatori')
        nomi = [n.strip() for n in nomi if n.strip()]
        if len(nomi) < 1:
            return render(request, 'game/setup.html', {'error': 'Inserisci almeno un giocatore'})

        frase_random = Frase.objects.order_by('?').first()
        if not frase_random:
            return HttpResponse("ERRORE CRITICO: Database vuoto. Esegui il comando popola_db.")

        config = ConfigurazioneGioco.objects.first()
        totale_rounds = config.numero_round_per_partita if config else 3

        partita = Partita.objects.create(
            frase_corrente=frase_random,
            numero_round=1,
            totale_rounds=totale_rounds
        )
        
        for nome in nomi:
            Giocatore.objects.create(partita=partita, nome=nome)
            
        request.session['partita_id'] = partita.id
        request.session['valore_ruota'] = 0
        request.session['round_vinto'] = False
        
        print(f"--- NUOVA PARTITA ({partita.id}) INIZIATA ---", file=sys.stderr)
        return redirect('gioco')
        
    return render(request, 'game/setup.html')

def gioco(request):
    partita_id = request.session.get('partita_id')
    if not partita_id: return redirect('setup_partita')
    
    partita = get_object_or_404(Partita, id=partita_id)
    
    # --- FIX 1: ORDINE STABILE DEI GIOCATORI ---
    # Usiamo order_by('id') per essere sicuri che la lista non cambi mai ordine
    giocatori = list(partita.giocatori.all().order_by('id'))
    
    if not giocatori: return redirect('setup_partita')
    if partita.turno_corrente >= len(giocatori):
        partita.turno_corrente = 0
        partita.save()
    
    giocatore_corrente = giocatori[partita.turno_corrente]
    valore_ruota = request.session.get('valore_ruota', 0)
    messaggio = request.session.pop('messaggio', '')
    
    # Auto-fix per ruota bloccata su PASSA
    if valore_ruota in ['PASSA', 'BANCAROTTA']:
        valore_ruota = 0
        request.session['valore_ruota'] = 0

    if request.session.get('round_vinto'):
        tabellone = [[{'char': c, 'visibile': True} for c in word] for word in partita.frase_corrente.testo.upper().split(' ')]
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

# -------------------------------------------------------------------------
# 2. LOGICA AZIONI
# -------------------------------------------------------------------------
def azione_gioco(request):
    if request.method != 'POST': return redirect('gioco')

    partita = get_object_or_404(Partita, id=request.session['partita_id'])
    
    # --- FIX 1: ORDINE STABILE ANCHE QUI ---
    giocatori = list(partita.giocatori.all().order_by('id'))
    
    if partita.turno_corrente >= len(giocatori):
        partita.turno_corrente = 0
        partita.save()
        
    giocatore_attivo = giocatori[partita.turno_corrente]
    tipo = request.POST.get('tipo')
    valore_ruota = request.session.get('valore_ruota', 0)
    vocali = "AEIOU"

    print(f"DEBUG: Azione {tipo} di {giocatore_attivo.nome}. Ruota: {valore_ruota}", file=sys.stderr)

    # --- TIMEOUT ---
    if tipo == 'tempo_scaduto':
        request.session['messaggio'] = f"⏰ TEMPO SCADUTO! {giocatore_attivo.nome} perde il turno."
        _cambia_turno(partita, request, len(giocatori), "Tempo Scaduto")
        return redirect('gioco')

    # --- SOLUZIONE ---
    if tipo == 'soluzione':
        tentativo = request.POST.get('soluzione_input', '').upper().strip()
        reale = partita.frase_corrente.testo.upper().strip()
        
        if tentativo == reale:
            giocatore_attivo.punteggio += giocatore_attivo.montepremi_round
            giocatore_attivo.save()
            for g in giocatori: # Reset parziali
                g.montepremi_round = 0
                g.save()
            request.session['round_vinto'] = True
            request.session['messaggio'] = f"🏆 CAMPIONE! {giocatore_attivo.nome} ha vinto!"
        else:
            giocatore_attivo.montepremi_round = 0
            giocatore_attivo.save()
            request.session['messaggio'] = f"❌ '{tentativo}' è SBAGLIATA! Perdi tutto e passi la mano."
            _cambia_turno(partita, request, len(giocatori), "Soluzione Errata")
            
        return redirect('gioco')

    # --- LETTERA ---
    if tipo == 'lettera':
        lettera = request.POST.get('lettera_input', '').upper().strip()
        if not lettera or not lettera.isalpha(): return redirect('gioco')

        # Se già chiamata -> AVVISA MA NON CAMBIA TURNO
        if lettera in partita.lettere_chiamate:
            request.session['messaggio'] = f"⚠️ '{lettera}' già uscita! Riprova."
            print(f"DEBUG: Lettera {lettera} già presente. Turno invariato.", file=sys.stderr)
            return redirect('gioco')

        is_vocale = lettera in vocali

        # A) VOCALE
        if is_vocale:
            if giocatore_attivo.montepremi_round < 500:
                request.session['messaggio'] = "🚫 Servono 500€!"
                return redirect('gioco')
            
            giocatore_attivo.montepremi_round -= 500
            giocatore_attivo.save()
            partita.lettere_chiamate += lettera
            partita.save()

            if lettera in partita.frase_corrente.testo.upper():
                request.session['messaggio'] = f"✅ VOCALE '{lettera}' TROVATA!"
                print(f"DEBUG: Vocale trovata. Resta a {giocatore_attivo.nome}", file=sys.stderr)
                # NO CAMBIO TURNO
            else:
                request.session['messaggio'] = f"❌ La vocale '{lettera}' non c'è."
                _cambia_turno(partita, request, len(giocatori), "Vocale Assente")

        # B) CONSONANTE
        else:
            if valore_ruota == 0 or valore_ruota in ['PASSA', 'BANCAROTTA']:
                request.session['messaggio'] = "🌀 Devi girare la ruota!"
                return redirect('gioco')

            partita.lettere_chiamate += lettera
            partita.save()
            occorrenze = partita.frase_corrente.testo.upper().count(lettera)

            if occorrenze > 0:
                try:
                    vincita = int(valore_ruota) * occorrenze
                    giocatore_attivo.montepremi_round += vincita
                    giocatore_attivo.save()
                    request.session['messaggio'] = f"🎉 BRAVO! {occorrenze} '{lettera}'. Vinci {vincita}€."
                    print(f"DEBUG: Consonante trovata. Resta a {giocatore_attivo.nome}", file=sys.stderr)
                except: pass
                
                # Indovinato -> Reset Ruota -> NO CAMBIO TURNO
                request.session['valore_ruota'] = 0
            else:
                request.session['messaggio'] = f"❌ La lettera '{lettera}' non c'è."
                _cambia_turno(partita, request, len(giocatori), "Lettera Assente")

    return redirect('gioco')

def api_gira_ruota(request):
    partita = get_object_or_404(Partita, id=request.session['partita_id'])
    # FIX 1: ORDINE ANCHE QUI
    giocatori = list(partita.giocatori.all().order_by('id')) 
    giocatore_attivo = giocatori[partita.turno_corrente]

    valore, rotazione = gira_la_ruota_logic()
    
    if valore == 'PASSA':
        request.session['messaggio'] = f"😰 PASSA! {giocatore_attivo.nome} salta il turno."
        _cambia_turno(partita, request, len(giocatori), "Uscito PASSA")
        request.session['valore_ruota'] = 0 
        
    elif valore == 'BANCAROTTA':
        request.session['messaggio'] = f"💸 BANCAROTTA! {giocatore_attivo.nome} perde il parziale."
        giocatore_attivo.montepremi_round = 0
        giocatore_attivo.save()
        _cambia_turno(partita, request, len(giocatori), "Uscito BANCAROTTA")
        request.session['valore_ruota'] = 0
        
    else:
        request.session['valore_ruota'] = valore

    return JsonResponse({'valore': valore, 'gradi_finali': rotazione})

def prossimo_round(request):
    partita_id = request.session.get('partita_id')
    partita = get_object_or_404(Partita, id=partita_id)
    
    partita.numero_round += 1
    partita.turno_corrente = 0 
    partita.lettere_chiamate = ""
    
    frasi_usate = request.session.get('frasi_usate', [])
    if partita.frase_corrente: frasi_usate.append(partita.frase_corrente.id)
    
    nuova = Frase.objects.exclude(id__in=frasi_usate).order_by('?').first()
    
    if nuova and partita.numero_round <= partita.totale_rounds:
        partita.frase_corrente = nuova
        partita.save()
        request.session['frasi_usate'] = frasi_usate
        request.session['round_vinto'] = False
        request.session['valore_ruota'] = 0
        request.session['messaggio'] = f"Round {partita.numero_round}!"
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
    return render(request, 'game/fine_partita.html', {
        'classifica': partita.giocatori.all().order_by('-punteggio'),
        'vincitore': partita.giocatori.all().order_by('-punteggio').first()
    })

# --- HELPER PER CAMBIO TURNO SICURO ---
def _cambia_turno(partita, request, num_giocatori, motivo=""):
    vecchio_turno = partita.turno_corrente
    partita.turno_corrente = (partita.turno_corrente + 1) % num_giocatori
    partita.save()
    request.session['valore_ruota'] = 0
    # Stampiamo nel log di Render perché stiamo cambiando turno
    print(f"DEBUG: Cambio turno da {vecchio_turno} a {partita.turno_corrente}. Motivo: {motivo}", file=sys.stderr)