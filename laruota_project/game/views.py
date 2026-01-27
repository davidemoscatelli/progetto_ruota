from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.models import User
from .models import Partita, Frase, Giocatore, ConfigurazioneGioco
from .utils import gira_la_ruota_logic

# -------------------------------------------------------------------------
# 1. SETUP E GESTIONE PARTITA
# -------------------------------------------------------------------------

def setup_partita(request):
    # PULIZIA SESSIONE: Rimuove residui vecchi
    keys_to_clear = ['round_vinto', 'valore_ruota', 'messaggio', 'partita_id', 'rotazione_ruota', 'frasi_usate']
    for key in keys_to_clear:
        if key in request.session:
            del request.session[key]

    if request.method == "POST":
        nomi = request.POST.getlist('nomi_giocatori')
        nomi = [n.strip() for n in nomi if n.strip()]
        
        if len(nomi) < 1:
            return render(request, 'game/setup.html', {'error': 'Inserisci almeno un giocatore'})

        frase_random = Frase.objects.order_by('?').first()
        if not frase_random:
            return HttpResponse("ERRORE: Nessuna frase nel database! Esegui il comando popola_db.")

        # Recupera configurazione o usa default
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
        return redirect('gioco')
        
    return render(request, 'game/setup.html')

def gioco(request):
    partita_id = request.session.get('partita_id')
    if not partita_id: return redirect('setup_partita')
    
    partita = get_object_or_404(Partita, id=partita_id)
    giocatori = partita.giocatori.all()
    
    # FIX SICUREZZA INDICI: Se l'indice sballa, resetta al primo giocatore
    if not giocatori or partita.turno_corrente >= len(giocatori):
        partita.turno_corrente = 0
        partita.save()
    
    giocatore_corrente = giocatori[partita.turno_corrente]
    valore_ruota = request.session.get('valore_ruota', 0)
    messaggio = request.session.pop('messaggio', '')
    
    # Costruzione Tabellone
    if request.session.get('round_vinto'):
        # Mostra tutta la frase
        tabellone = []
        for parola_raw in partita.frase_corrente.testo.upper().split(' '):
            parola_obj = [{'char': c, 'visibile': True} for c in parola_raw]
            tabellone.append(parola_obj)
    else:
        # Mostra solo lettere indovinate
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
# 2. LOGICA DI GIOCO (Core)
# -------------------------------------------------------------------------

def azione_gioco(request):
    """
    Gestisce tutte le azioni: Timeout, Soluzione, Lettera (Consonante/Vocale).
    Usa 'return redirect' immediati per evitare che il codice prosegua per sbaglio.
    """
    if request.method != 'POST': 
        return redirect('gioco')

    partita_id = request.session.get('partita_id')
    partita = get_object_or_404(Partita, id=partita_id)
    giocatori = list(partita.giocatori.all())
    
    # Sicurezza indice turno
    if partita.turno_corrente >= len(giocatori):
        partita.turno_corrente = 0
        partita.save()
        
    giocatore_attivo = giocatori[partita.turno_corrente]
    tipo = request.POST.get('tipo')
    valore_ruota = request.session.get('valore_ruota', 0)
    vocali = "AEIOU"

    # ==========================================
    # CASO 1: TEMPO SCADUTO -> CAMBIO TURNO
    # ==========================================
    if tipo == 'tempo_scaduto':
        request.session['messaggio'] = f"⏰ TEMPO SCADUTO! {giocatore_attivo.nome} passa la mano."
        partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
        partita.save()
        request.session['valore_ruota'] = 0
        return redirect('gioco')

    # ==========================================
    # CASO 2: SOLUZIONE -> VINCE O PERDE TURNO
    # ==========================================
    if tipo == 'soluzione':
        tentativo = request.POST.get('soluzione_input', '').upper().strip()
        reale = partita.frase_corrente.testo.upper().strip()
        
        if tentativo == reale:
            # VITTORIA
            vincita = giocatore_attivo.montepremi_round
            giocatore_attivo.punteggio += vincita
            giocatore_attivo.save()
            
            # Resetta montepremi round degli altri (regola opzionale, ma comune)
            for g in giocatori:
                g.montepremi_round = 0
                g.save()

            request.session['round_vinto'] = True
            request.session['messaggio'] = f"🏆 CAMPIONE! {giocatore_attivo.nome} vince il round e {vincita}€!"
        else:
            # ERRORE -> CAMBIO TURNO E PERDITA SOLDI ROUND
            giocatore_attivo.montepremi_round = 0
            giocatore_attivo.save()
            request.session['messaggio'] = f"❌ '{tentativo}' è SBAGLIATA! Perdi tutto e passi la mano."
            partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
            partita.save()
            request.session['valore_ruota'] = 0
            
        return redirect('gioco')

    # ==========================================
    # CASO 3: LETTERA (Consonante o Vocale)
    # ==========================================
    if tipo == 'lettera':
        lettera = request.POST.get('lettera_input', '').upper().strip()
        
        # Validazione input
        if not lettera or len(lettera) > 1 or not lettera.isalpha():
            return redirect('gioco')

        # A) LETTERA GIÀ CHIAMATA -> CAMBIO TURNO
        if lettera in partita.lettere_chiamate:
            request.session['messaggio'] = f"⚠️ La lettera '{lettera}' è GIÀ USCITA! Passi il turno."
            partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
            partita.save()
            request.session['valore_ruota'] = 0
            return redirect('gioco')

        is_vocale = lettera in vocali

        # B) GESTIONE VOCALE
        if is_vocale:
            # Controllo soldi
            if giocatore_attivo.montepremi_round < 500:
                request.session['messaggio'] = "🚫 Non hai 500€ per comprare la vocale!"
                return redirect('gioco')
            
            # Paga vocale
            giocatore_attivo.montepremi_round -= 500
            giocatore_attivo.save()
            partita.lettere_chiamate += lettera
            
            if lettera in partita.frase_corrente.testo.upper():
                request.session['messaggio'] = f"✅ VOCALE '{lettera}' PRESENTE! Continua a giocare."
                partita.save()
                # NON CAMBIA IL TURNO (Exit immediato)
                return redirect('gioco')
            else:
                request.session['messaggio'] = f"❌ La vocale '{lettera}' NON c'è. Cambio turno."
                partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                partita.save()
                return redirect('gioco')

        # C) GESTIONE CONSONANTE
        else:
            # Controllo se ha girato la ruota
            if valore_ruota == 0 or valore_ruota in ['PASSA', 'BANCAROTTA']:
                request.session['messaggio'] = "🌀 Devi prima girare la ruota!"
                return redirect('gioco')

            partita.lettere_chiamate += lettera
            occorrenze = partita.frase_corrente.testo.upper().count(lettera)

            if occorrenze > 0:
                # --- SUCCESSO! ---
                try:
                    vincita = int(valore_ruota) * occorrenze
                    giocatore_attivo.montepremi_round += vincita
                    giocatore_attivo.save()
                    request.session['messaggio'] = f"🎉 BRAVO! Ci sono {occorrenze} '{lettera}'. Vinci {vincita}€. GIRA ANCORA!"
                    # Resettiamo la ruota perché deve rigirare, MA MANTENIAMO IL TURNO
                    request.session['valore_ruota'] = 0 
                except ValueError: 
                    pass # Caso raro (es. valore stringa strano), ignoriamo

                partita.save()
                # RETURN IMMEDIATO: Qui siamo sicuri che il turno NON cambia
                return redirect('gioco') 
            
            else:
                # --- FALLIMENTO ---
                request.session['messaggio'] = f"❌ La lettera '{lettera}' NON c'è. Tocca al prossimo."
                partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
                partita.save()
                request.session['valore_ruota'] = 0
                return redirect('gioco')

    return redirect('gioco')


def api_gira_ruota(request):
    partita = get_object_or_404(Partita, id=request.session['partita_id'])
    giocatori = list(partita.giocatori.all())
    giocatore_attivo = giocatori[partita.turno_corrente]

    valore, rotazione_target = gira_la_ruota_logic()
    request.session['valore_ruota'] = valore
    
    # Gestione eventi speciali Ruota
    if valore == 'PASSA':
        request.session['messaggio'] = f"😰 PASSA LA MANO! {giocatore_attivo.nome} salta il turno."
        partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
        partita.save()
        # Non resettiamo valore_ruota qui, così il frontend vede 'PASSA'
        
    elif valore == 'BANCAROTTA':
        request.session['messaggio'] = f"💸 BANCAROTTA! {giocatore_attivo.nome} perde tutto il montepremi del round."
        giocatore_attivo.montepremi_round = 0 
        giocatore_attivo.save()
        
        partita.turno_corrente = (partita.turno_corrente + 1) % len(giocatori)
        partita.save()
    
    return JsonResponse({'valore': valore, 'gradi_finali': rotazione_target})


def prossimo_round(request):
    partita_id = request.session.get('partita_id')
    partita = get_object_or_404(Partita, id=partita_id)
    
    # Avanza round
    partita.numero_round += 1
    
    # Resetta turno al primo giocatore (o fai ruotare se preferisci)
    partita.turno_corrente = 0 
    partita.lettere_chiamate = ""
    
    # Evita ripetizione frasi
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
        
        # Reset montepremi parziali
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
    
    # Classifica finale
    classifica = partita.giocatori.all().order_by('-punteggio')
    vincitore_assoluto = classifica.first()
    
    return render(request, 'game/fine_partita.html', {
        'classifica': classifica,
        'vincitore': vincitore_assoluto
    })

# --- FUNZIONE DI INSTALLAZIONE (Quella che avevamo fatto prima, la lascio in fondo) ---
def installazione_segreta(request):
    return HttpResponse("Funzione disabilitata per sicurezza. Usa il comando popola_db.")