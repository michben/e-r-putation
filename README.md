# e-réputation

Retirer ou déréférencer les données personnelles d'une personne qui y consent : moteurs de
recherche, annuaires, courtiers en contacts B2B, registres d'entreprises et plateformes, en France
et dans l'UE. Les demandes sont rédigées en français (RGPD, DSA), leurs délais légaux sont suivis,
les relances et la plainte CNIL sont préparées.

L'outil est conçu pour être piloté par un agent (Claude Code, via le skill
[`.claude/skills/e-reputation`](.claude/skills/e-reputation/SKILL.md)) mais la CLI s'utilise aussi
à la main. Python 3.10+ sans dépendance.

## Démarrage

```bash
python3 -m erep setup
python3 -m erep intake --full-name "Jeanne Exemple" --birth-name "Jeanne Modèle" \
  --email jeanne@example.org --phone +33600000000 --city Lyon --consent
python3 -m erep plan s_xxxxxxxxxxxx
python3 -m erep render s_xxxxxxxxxxxx google-search --kind dereferencement \
  --listing https://exemple.fr/article --motif "Information obsolète, sans intérêt public"
python3 -m erep record s_xxxxxxxxxxxx google-search submitted --kind dereferencement \
  --disclosed full_name,contact_email --channel web_form
python3 -m erep due s_xxxxxxxxxxxx      # relances et plaintes CNIL arrivées à échéance
python3 -m erep status s_xxxxxxxxxxxx
```

Pour agir au nom d'un proche ou d'un client : `python3 -m erep mandate --full-name ... --mandataire
...`, faire signer, puis `intake ... --consent --consent-method mandate --mandate-ref <emplacement>`.

## Fonctionnement

- **Consentement obligatoire** et identifiants opaques : aucun nom dans les chemins ou le journal.
- **Minimisation** : chaque demande ne contient que les champs exigés par la cible ; jamais de
  NIR, de numéro de pièce d'identité ni d'IBAN.
- **Parents d'abord** : la liste rouge auprès de l'opérateur couvre les annuaires ; la diffusion
  partielle SIRENE couvre Societe.com et Pappers ; une demande d'accès (art. 15) révèle la source
  d'un courtier.
- **Paliers T0 à T3** : de l'entièrement automatisable à l'humain de bout en bout, avec un seul
  récapitulatif des tâches humaines.
- **Registre à états** validés et journal d'audit (noms des champs transmis, jamais leurs valeurs).
- **Délais légaux** : un mois (art. 12.3 RGPD), prolongation de deux mois, relance, puis plainte
  CNIL préparée.
- **Résultat honnête** : « déréférencé » n'est pas « supprimé », et rien n'est marqué terminé sans
  nouvelle recherche qui le confirme.

| Dossier | Contenu |
|---|---|
| `erep/` | La CLI |
| `targets/` | Une fiche JSON par cible (canal, champs exigés, types de demande, parents) |
| `templates/demandes/` | Modèles de demandes en français |
| `templates/consentement/` | Mandat à faire signer |
| `tests/` | Tests hermétiques : `python3 -m unittest discover tests` |

Les fiches cibles sont **documentées mais pas encore vérifiées sur le terrain** : confirmer le canal
au premier usage. `python3 -m erep doctor` liste celles dont le canal reste à relever.

## Feuille de route

1. Socle (cette version) : CLI, registre et délais, cibles FR, modèles, tests.
2. Autonomie : envoi d'e-mails (navigateur ou SMTP/IMAP), boucle `next`, vérifications planifiées.
3. Veille : suivi des résultats de recherche et des avis sur le nom, rapport d'évolution.

## Crédits et licence

- Architecture adaptée de [unbroker](https://github.com/NousResearch/hermes-agent/tree/main/optional-skills/security/unbroker)
  (NousResearch/hermes-agent, licence MIT). La liste de courtiers BADBOOL utilisée par unbroker
  (CC BY-NC-SA, États-Unis) n'est pas reprise.
- Code : MIT, voir [LICENSE](LICENSE).

## Avertissement

Ceci n'est pas un conseil juridique. N'agir que pour des personnes qui ont autorisé ces démarches.
Retirer des données réduit l'exposition sans garantir un effacement total.
