---
name: e-reputation
description: Retirer ou déréférencer les données personnelles d'une personne consentante (moteurs de recherche, annuaires, courtiers B2B, plateformes) en France et dans l'UE, avec demandes RGPD/DSA en français, suivi des délais et escalade CNIL.
---

# e-réputation

Trouver où les données personnelles d'une personne (nom, téléphone, e-mail, adresse, activité
professionnelle) sont exposées en ligne, puis les faire retirer ou déréférencer : automatiquement
quand c'est possible, avec une seule liste de tâches humaines pour le reste (démarche auprès de
l'opérateur, compte à supprimer, plainte CNIL à déposer).

La CLI (`python3 -m erep`, à lancer depuis la racine du dépôt) détient l'état déterministe :
dossiers et consentement, base des cibles, plan par paliers, registre de suivi, délais légaux,
brouillons de demandes et rapports. Toi, l'agent, tu fais les recherches (recherche web, navigateur)
et les soumissions (formulaires, e-mails envoyés par la personne ou, plus tard, par la CLI).

Architecture adaptée du skill `unbroker` (NousResearch/hermes-agent, MIT), recentrée sur la France.

## Limites absolues

- **Pas de consentement, pas d'action.** La CLI refuse tout sans consentement enregistré. Pour un
  tiers (proche, client), il faut un mandat signé (`python3 -m erep mandate`) et `--consent-method
  mandate --mandate-ref <emplacement>`. Ne jamais « juste regarder » quelqu'un d'autre.
- **Minimisation.** Ne transmettre que `disclosure_fields`. Jamais de NIR, numéro de pièce
  d'identité, IBAN. Si un site exige une pièce d'identité, la personne décide : enregistrer
  `human_task_queued --reason` et passer à la suite.
- **Ne jamais invoquer un droit inapplicable.** `render` refuse le RGPD pour une personne hors UE
  face à une cible non établie dans l'UE.
- **Pas de contournement anti-bot**, pas de service de résolution de CAPTCHA.
- **Vérifier avant de conclure.** `confirmed_removed` ou `delisted` seulement après une nouvelle
  recherche qui le montre (`--verified`), jamais sur la seule page de confirmation d'un site.
- **Dire la vérité sur le résultat.** Déréférencé n'est pas supprimé ; les données légalement
  publiques (RCS, décisions de justice) restent publiques.

## Commandes

| Commande | Rôle |
|---|---|
| `setup [--email-mode draft_only]` / `doctor` | Configuration et état (cibles non vérifiées, canaux manquants) |
| `intake --full-name ... [--birth-name] [--alias] [--email] [--phone] [--city] [--prior-city] [--residence FR] --consent [--consent-method mandate --mandate-ref ...]` | Enregistrer la personne ; renvoie un `subject_id` opaque |
| `mandate --full-name ... --mandataire ...` | Générer le mandat à faire signer |
| `targets [--category ...]` | Lister les cibles |
| `plan <sid>` | Une ligne par cible : palier, méthode, types de demande applicables, vecteurs de recherche, champs à transmettre, parents d'abord |
| `record <sid> <cible> <état> [--kind] [--evidence JSON] [--disclosed f,f --channel c] [--reason] [--verified]` | Mettre à jour le registre (transitions validées, délais calculés) |
| `show <sid> <cible>` | Relire un dossier du registre |
| `render <sid> <cible> --kind <type> [--listing URL] [--motif ...]` | Rédiger une demande (brouillon, rien n'est envoyé) et indiquer la commande `record` à lancer ensuite |
| `due <sid>` | Relances, plaintes CNIL et nouvelles vérifications arrivées à échéance |
| `tasks <sid>` | Le récapitulatif unique des tâches humaines |
| `status <sid>` | Rapport Markdown |

Types de demande (`--kind`) : `rgpd_acces`, `rgpd_effacement`, `rgpd_opposition`,
`dereferencement`, `dsa_notification`, `relance`, `plainte_cnil`.

## Déroulé

1. **Entretien unique.** Recueillir en une fois : nom d'usage, nom de naissance, autres noms,
   villes actuelle et passées, e-mails, téléphones, pays de résidence, et le consentement (ou le
   mandat). Lancer `intake`. Ne plus revenir avec des questions ensuite.
2. **Plan.** `plan <sid>`. Les parents passent en premier : `annuaire-universel` (liste rouge
   auprès de l'opérateur) couvre PagesBlanches et 118 712 ; `insee-sirene` (diffusion partielle)
   couvre Societe.com et Pappers. Ne traiter un enfant (`covered_by`) que si une nouvelle recherche
   montre qu'il expose encore la personne après le parent.
3. **Recherche (lecture seule).** Pour chaque cible, essayer chaque `search_vectors` (nom d'usage
   et nom de naissance, avec et sans ville ; téléphone ; e-mail). Distinguer la personne d'un
   homonyme avant de conclure. Enregistrer `found` avec `--evidence '{"listing_urls": [...]}'`,
   `not_found`, `indirect_exposure` (sa donnée sur la fiche d'un tiers) ou `blocked --reason`.
   Pour les moteurs : rechercher le nom entre guillemets sur les trois premières pages et relever
   chaque URL qui expose la personne ; chaque site trouvé hors base se traite avec
   `hebergeur-generique` (copier la fiche sous un nouvel id).
4. **Demandes.** Choisir le type parmi `kinds` du plan :
   - Courtiers B2B : `rgpd_acces` d'abord quand la source est inconnue (la réponse dit d'où vient
     la donnée, art. 14), puis `rgpd_effacement`. Une demande « à l'aveugle » (`new -> submitted`)
     est permise : elle ne transmet que les identifiants de la personne au canal officiel.
   - Moteurs : `dereferencement` avec un `--motif` concret (information obsolète, inexacte,
     sans intérêt public, atteinte à la vie privée).
   - Contenus illicites (diffamation, injure, données intimes) : `dsa_notification` à l'hébergeur,
     plus `dereferencement` en parallèle. Un avis négatif mais licite ne sera pas retiré.
   `render` produit le brouillon et la commande `record ... submitted` à lancer une fois envoyé.
   En mode `draft_only`, la personne envoie l'e-mail : mets-le dans le récapitulatif humain.
   Si `missing_channel` est vrai, trouve le canal officiel (page « données personnelles », DPO
   dans la politique de confidentialité, mentions légales) et complète la fiche dans `targets/`.
5. **Délais.** `record ... submitted` fixe l'échéance : un mois pour le RGPD (art. 12.3), 14 jours
   par usage pour le DSA. Si le responsable annonce une prolongation, `record ... extended` (deux
   mois de plus). `due` signale ensuite : `send_reminder` (rédiger `--kind relance`, l'envoyer,
   `record ... reminded`), puis `file_cnil_complaint` 15 jours après la relance (rédiger
   `--kind plainte_cnil` ; la personne dépose sur cnil.fr avec les pièces).
6. **Vérification.** Après traitement, refaire la recherche. Seulement si l'exposition a disparu :
   `record ... confirmed_removed --verified` ou `delisted --verified`. Une nouvelle vérification
   est planifiée à 90 jours ; si la donnée réapparaît, `reappeared` puis on repart.
7. **Fin de passage.** Présenter `tasks <sid>` (une seule fois) puis `status <sid>`.

## Pièges

- Les fiches de `targets/` sont `confidence: documented` : canal tiré de la documentation publique,
  pas encore vérifié sur le terrain. Confirmer au premier usage et renseigner `last_verified`.
- `submitted -> not_found` est interdit : une demande envoyée qui ne trouve rien se termine en
  `awaiting_processing` puis en vérification.
- Les données sont dans `$EREP_DATA_DIR` (par défaut `~/.erep`, droits 0600). Ne jamais les
  committer ni les coller dans un ticket.

## Vérification

`python3 -m unittest discover tests` (hermétique : ni réseau, ni navigateur, ni e-mail).
