# N2F → Pennylane V2 — Streamlit Community Cloud

Remplacer les fichiers du dépôt GitHub par app.py, convertisseur.py, pieces.py et requirements.txt. Garder app.py comme point d'entrée Streamlit Cloud. Aucun fichier client ne doit être ajouté à GitHub.

## Changements

- FPROLIANS → 401PROLIANS : suppression du F initial, sans supprimer les F à l'intérieur du nom. Les comptes numériques restent inchangés. Mapping modifiable.
- Export de type FEC : libellé original sur chaque ligne ; EcritureNum et PieceRef identiques pour les lignes de la même écriture.
- CSV Pennylane alternatif : réunion des libellés originaux en un libellé commun à la pièce pour respecter la règle de regroupement documentée par Pennylane. Aucun libellé réduit au seul nom de fichier.
- FG : par défaut une pièce équilibrée par fichier/date/journal. Un fichier doit correspondre à une note. Si plusieurs notes sont fusionnées dans un même CSV sans identifiant, impossible de les distinguer avec certitude : exporter séparément depuis N2F. Option de découpage par libellé uniquement si tous les sous-groupes sont équilibrés ; plusieurs dépenses identiques peuvent rester regroupées.
- AC : une pièce par bloc fournisseur ; le même fournisseur à la même date peut avoir plusieurs pièces distinctes.
- Références stables issues du contenu et du groupe, indépendantes du nom du CSV. Avec une PJ, ajout du numéro de note N2F à la référence.
- Lecture des ZIP de rapports ou PDF individuels. Détection du numéro de note, collaborateur, période, TTC, remboursable et nombre de pages.
- Conservation des entrées ZIP de même nom mais de contenus différents. Seuls les PDF strictement identiques sont dédupliqués.
- Association manuelle explicite de chaque pièce comptable à un PDF entier. Les égalités de montant sont seulement proposées comme indices. Les écarts de montant et de période doivent être confirmés.
- Export d'un pack ZIP avec le fichier de type FEC, le CSV alternatif, PJ.zip et les contrôles. Ne jamais importer les deux fichiers comptables.

## Limites utiles

La moulinette ne recrée pas la comptabilité à partir des PDF seuls : il manque notamment les comptes, dates comptables et contreparties fiables. Les paiements professionnels peuvent avoir un TTC non nul et zéro à rembourser. Importer les CSV correspondant réellement aux rapports.

Le PDF entier est associé à la note. Il n'est pas découpé ticket par ticket. Si un PDF est associé à plusieurs écritures, une copie est produite pour chaque PieceRef ; cela augmente le volume. Limite de 350 Mo pour les PDF et leurs copies, afin de limiter la mémoire sur Streamlit Cloud. Éviter le découpage fin avec de gros PDF.

Le fichier de type FEC n'est pas un FEC fiscal réglementaire : les champs absents des sources (CompteLib, PieceDate, ValidDate, etc.) restent vides. Le CSV alternatif respecte la règle Pennylane « une pièce = une date / un journal / un libellé d'écriture ». Les dates réelles des tickets visibles dans le PDF ne remplacent pas les dates comptables du CSV.

Le traitement se fait en mémoire sur le serveur Streamlit Cloud. Pas de cache partagé, ni sauvegarde des données comptables sur disque par l'application. Les fichiers restent accessibles dans la session le temps de travailler ; bouton pour vider la session.

Documentation Pennylane consultée le 14/10/2026 : https://help.pennylane.com/fr/articles/18793-importer-des-ecritures

