# Conso GRDF

Intégration Home Assistant qui lit la consommation de gaz de votre compteur **Gazpar**
sur votre espace client GRDF (monespace.grdf.fr) et l'expose en **capteurs**.

Elle utilise la bibliothèque [pygazpar](https://github.com/ssenart/PyGazpar), la même que
l'add-on [gazpar2haws](https://github.com/ssenart/gazpar2haws), et peut écrire **les mêmes
statistiques** pour le tableau Énergie : vous pouvez remplacer l'add-on sans perdre l'historique.

> GRDF publie les relevés avec un à plusieurs jours de retard. Il n'y a pas de temps réel.

## Installation

1. HACS → ⋮ → **Dépôts personnalisés** → `https://github.com/frederic76430/conso-grdf`, type **Intégration**.
2. Installez **Conso GRDF**, puis redémarrez Home Assistant.
3. Paramètres → Appareils et services → **Ajouter une intégration** → *Conso GRDF*.
4. Saisissez l'e-mail et le mot de passe de votre espace client GRDF.

## Options

- **Relevés GRDF** : *informatifs* (quotidiens, conseillé) ou *publiés* si les informatifs sont vides.
- **Statistiques du tableau Énergie** : écrit `sensor.<nom>_volume` (m³) et `sensor.<nom>_energy` (kWh),
  un point par jour, exactement comme gazpar2haws, à la suite de ses valeurs.
- **Nom d'appareil gazpar2haws** : le `name` de votre configuration gazpar2haws (`gazpar2haws` par défaut).

## Capteurs

| Capteur | Contenu |
|---|---|
| Énergie jour / Volume jour | dernier jour publié (attributs `date`, `temperature`, `coef`) |
| Énergie / Volume mois, mois dernier, année | sommes des jours publiés |
| Index compteur | index de fin du dernier jour publié, en m³ |
| Température du jour | température GRDF du dernier jour publié |
| Dernière lecture | date de la dernière lecture réussie |

## Remplacer gazpar2haws

1. Relevez le `name` de l'appareil dans la configuration de gazpar2haws.
2. **Arrêtez** gazpar2haws.
3. Dans les options de Conso GRDF : cochez les statistiques et saisissez ce nom.
4. Vérifiez le lendemain le tableau Énergie, puis désinstallez gazpar2haws.

Les coûts calculés par gazpar2haws (`sensor.<nom>_total_cost`…) ne sont pas repris : indiquez
plutôt un prix au kWh dans les réglages du tableau Énergie.

## Connexions à GRDF

Relecture à 8 h, 12 h, 17 h et 21 h (minute tirée au hasard), **seulement si des données manquent** ;
les données sont gardées sur disque (aucune connexion au redémarrage si tout est à jour).

## Licence

MIT
