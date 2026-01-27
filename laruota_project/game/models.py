from django.db import models

class Categoria(models.Model):
    nome = models.CharField(max_length=100)
    def __str__(self): return self.nome

class Frase(models.Model):
    testo = models.CharField(max_length=200)
    suggerimento = models.CharField(max_length=100, default="", help_text="Es: PINK FLOYD") # <--- NUOVO CAMPO
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    
    def __str__(self): return self.testo.upper()

class Partita(models.Model):
    frase_corrente = models.ForeignKey(Frase, on_delete=models.CASCADE)
    lettere_chiamate = models.TextField(default="", blank=True)
    turno_corrente = models.IntegerField(default=0)
    vincitore = models.CharField(max_length=100, null=True, blank=True)
    numero_round = models.IntegerField(default=1) 
    totale_rounds = models.IntegerField(default=3) 
    
    def get_tabellone_a_parole(self):
        frase_split = self.frase_corrente.testo.upper().split(' ')
        chiamate = self.lettere_chiamate.upper()
        risultato = []
        for parola_raw in frase_split:
            parola_obj = []
            for char in parola_raw:
                if char.isalpha():
                    if char in chiamate:
                        parola_obj.append({'char': char, 'visibile': True})
                    else:
                        parola_obj.append({'char': '', 'visibile': False})
                else:
                    parola_obj.append({'char': char, 'visibile': True})
            risultato.append(parola_obj)
        return risultato

class Giocatore(models.Model):
    partita = models.ForeignKey(Partita, related_name="giocatori", on_delete=models.CASCADE)
    nome = models.CharField(max_length=50)
    punteggio = models.IntegerField(default=0)
    montepremi_round = models.IntegerField(default=0)
    def __str__(self): return self.nome