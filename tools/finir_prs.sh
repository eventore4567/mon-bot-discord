#!/usr/bin/env bash
# Fusionne des PR SentriX une par une, SEULEMENT si elles sont prêtes.
#
#   bash tools/finir_prs.sh 554            # une PR
#   bash tools/finir_prs.sh 554 542 541    # plusieurs, dans l'ordre donné
#
# Pour chaque PR : attend la fin de sa CI (30 min max), puis fusionne si
# toutes les vérifications sont vertes ET qu'elle n'a pas de conflit avec la
# production. Sinon elle est sautée, avec la raison. Rien n'est forcé.
set -u
REPO="eventore4567/mon-bot-discord"

for PR in "$@"; do
  echo "=== PR #$PR"
  etat=$(gh pr view "$PR" --repo "$REPO" --json state,mergeable --jq '.state + " " + .mergeable' 2>/dev/null)
  case "$etat" in
    "OPEN MERGEABLE") ;;
    "OPEN UNKNOWN") sleep 10; etat=$(gh pr view "$PR" --repo "$REPO" --json mergeable --jq .mergeable) ;;
    *) echo "  sautée : $etat (fermée ou en conflit avec la production)"; continue ;;
  esac
  [ "$etat" = "CONFLICTING" ] && { echo "  sautée : conflit avec la production"; continue; }

  echo "  attente de la CI…"
  gh pr checks "$PR" --repo "$REPO" --watch --interval 60 >/dev/null 2>&1 &
  watch_pid=$!
  ( sleep 1800; kill "$watch_pid" 2>/dev/null ) &
  wait "$watch_pid" 2>/dev/null
  echecs=$(gh pr checks "$PR" --repo "$REPO" 2>/dev/null | awk -F'\t' '$2!="pass" && $2!="skipping"' | wc -l | tr -d ' ')
  if [ "$echecs" != "0" ]; then
    echo "  sautée : $echecs vérification(s) non verte(s) :"
    gh pr checks "$PR" --repo "$REPO" 2>/dev/null | awk -F'\t' '$2!="pass" && $2!="skipping" {print "    - " $1 " : " $2}'
    continue
  fi
  if gh pr merge "$PR" --repo "$REPO" --merge; then
    echo "  fusionnée. Railway redéploie la production (~3 min)."
  else
    echo "  fusion refusée par GitHub."
  fi
done
