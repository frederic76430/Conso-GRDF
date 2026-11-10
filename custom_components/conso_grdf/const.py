"""Constantes de l'intégration Conso GRDF."""

from __future__ import annotations

DOMAIN = "conso_grdf"
MANUFACTURER = "GRDF"
MODEL = "Compteur Gazpar"

CONF_PCE = "pce"
CONF_TYPE_CONSO = "type_conso"
CONF_STATISTIQUES = "statistiques"
CONF_PREFIXE = "prefixe"
CONF_COUTS = "couts"
# Tarifs TTC saisis à la main (0 = repris des coûts gazpar2haws)
CONF_PRIX_KWH = "prix_kwh"
CONF_TAXES_KWH = "taxes_kwh"
CONF_ABONNEMENT_JOUR = "abonnement_jour"
CONF_TRANSPORT_JOUR = "transport_jour"

TYPE_INFORMATIVE = "informative"
TYPE_PUBLIEE = "published"

# Préfixe des statistiques de gazpar2haws : sensor.<prefixe>_volume et sensor.<prefixe>_energy
PREFIXE_DEFAUT = "gazpar2haws"

# GRDF publie les relevés quotidiens avec un ou plusieurs jours de retard, souvent dans la journée
HEURES_RELECTURE = (8, 12, 17, 21)

# Premier import des statistiques, quand aucune n'existe encore
JOURS_INITIAUX = 365

STORAGE_VERSION = 1
