import random

# Mappatura esatta della ruota Ravensburger (24 spicchi)
# Ordine: Partendo dallo spicchio "2000" e andando in senso ORARIO
SPICCHI_RUOTA = [
    2000,           # Spicchio 0
    200,            # Spicchio 1
    350,            # Spicchio 2
    100,            # Spicchio 3
    500,            # Spicchio 4 (Quello giallo col punto interrogativo)
    "PASSA",        # Spicchio 5
    300,            # Spicchio 6
    150,            # Spicchio 7
    400,            # Spicchio 8
    250,            # Spicchio 9
    500,            # Spicchio 10 (Blu)
    "BANCAROTTA",   # Spicchio 11 (Nero/Bianco)
    400,            # Spicchio 12
    300,            # Spicchio 13
    150,            # Spicchio 14
    500,            # Spicchio 15 (Blu col punto interrogativo)
    200,            # Spicchio 16
    "PASSA",        # Spicchio 17
    350,            # Spicchio 18
    100,            # Spicchio 19
    500,            # Spicchio 20 (Giallo)
    250,            # Spicchio 21
    400,            # Spicchio 22
    "BANCAROTTA"    # Spicchio 23 (Scritta bianca verticale)
]

def gira_la_ruota_logic():
    # 1. Scegliamo un INDICE a caso
    indice_selezionato = random.randint(0, len(SPICCHI_RUOTA) - 1)
    valore = SPICCHI_RUOTA[indice_selezionato]
    
    # 2. Calcolo SOLO l'angolo target (0-360)
    # Ogni spicchio è 15 gradi.
    # L'indice 0 è a 0 gradi. L'indice 1 è a 15 gradi (ma dobbiamo ruotare indietro).
    gradi_per_spicchio = 360 / len(SPICCHI_RUOTA)
    
    # Calcoliamo l'angolo target per portare lo spicchio in alto (a ore 12)
    # Esempio: Indice 1 (15° a destra). Per portarlo su, la ruota deve girare di -15° (o 345°).
    angolo_target = (360 - (indice_selezionato * gradi_per_spicchio)) % 360
    
    # Restituiamo solo l'angolo pulito (es: 45.0, 90.0)
    return valore, angolo_target