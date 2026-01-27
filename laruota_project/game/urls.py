from django.urls import path
from . import views

urlpatterns = [
    path('', views.setup_partita, name='setup_partita'),
    path('gioco/', views.gioco, name='gioco'),
    path('azione/', views.azione_gioco, name='azione_gioco'),
    path('api/gira/', views.api_gira_ruota, name='api_gira_ruota'),
    path('prossimo_round/', views.prossimo_round, name='prossimo_round'),
    path('fine/', views.fine_partita, name='fine_partita'), # <--- NUOVO
]