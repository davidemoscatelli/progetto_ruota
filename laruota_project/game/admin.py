from django.contrib import admin
from django.core.management import call_command
from django.contrib import messages
from .models import Categoria, Frase, Partita, Giocatore, ConfigurazioneGioco

@admin.register(ConfigurazioneGioco)
class ConfigurazioneAdmin(admin.ModelAdmin):
    # Mostriamo i campi nel pannello
    list_display = ['numero_round_per_partita', 'ultima_modifica']
    
    # Metodo speciale che viene chiamato quando premi "Salva"
    def save_model(self, request, obj, form, change):
        # Se l'admin ha spuntato la casella...
        if obj.ricarica_frasi:
            try:
                # 1. Esegui il comando
                call_command('popola_db')
                
                # 2. Avvisa l'admin che è andato tutto bene
                messages.success(request, "✅ DATABASE AGGIORNATO! Tutte le frasi sono state ricaricate.")
                
                # 3. Togli la spunta (altrimenti lo rifà ogni volta che salvi)
                obj.ricarica_frasi = False
                
            except Exception as e:
                messages.error(request, f"❌ Errore durante l'aggiornamento: {e}")
        
        # Salva le modifiche normali (es. numero round)
        super().save_model(request, obj, form, change)

    def ultima_modifica(self, obj):
        return "Modifica per aggiornare"

# Registrazione classica degli altri modelli
admin.site.register(Categoria)
admin.site.register(Frase)
admin.site.register(Partita)
admin.site.register(Giocatore)