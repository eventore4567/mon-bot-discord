"""Le bot s'adresse a l'utilisateur au VOUVOIEMENT, partout.

Mesure a l'origine de ce choix : 258 chaines utilisateur tutoyaient contre 690 qui
vouvoyaient, et 13 modules melangeaient les deux — parfois dans le meme ecran.
Le vouvoiement l'emporte parce qu'il etait deja majoritaire et qu'il convient a un
bot de moderation qui parle au staff d'un serveur.

Ce test parcourt les chaines qui atteignent reellement un humain. Il ignore :
  - les docstrings et les constantes de module (elles s'adressent au developpeur) ;
  - les prompts envoyes au modele d'IA (les convertir changerait l'instruction) ;
  - les expressions regulieres, qui doivent au contraire accepter les deux formes.
"""
import ast
import pathlib
import re
import unittest

RACINE = pathlib.Path(__file__).resolve().parent.parent

PRONOM_TU = re.compile(r"(?<![\wà-ÿ'])(tu|ton|ta|tes|toi)(?![\wà-ÿ])")
# Un imperatif a la 2e personne du singulier, en tete de phrase ou apres un connecteur.
IMPERATIF_TU = re.compile(
    r"(?:^|[.!?:]\s+|\n\s*|\*\*|\b(?:puis|et|ou|alors|ensuite)\s+)"
    r"(rejoins|relance|utilise|choisis|clique|ouvre|tape|essaie|vérifie|accepte|"
    r"attends|patiente|réessaie|indique|mentionne|actualise|donne|place|écris|décris)"
    r"(?![a-zà-ÿ])",
    re.IGNORECASE,
)
# « Vous pourras », « Vous reproduis » : conversion incomplete.
DESACCORD = re.compile(r"\b[Vv]ous\s+([a-zà-ÿ]+(?:as|is)\b)(?<!vous avez)")

# Les prompts partent au modele, pas a l'utilisateur : les convertir changerait
# l'instruction donnee a l'IA. Ils arrivent sous deux formes — passes a un appel,
# ou assignes a une variable (`prompt = f"""Vérifie cette capture..."""`).
APPELS_IA = ("_handle_ai_command", "ask", "generate", "complete", "chat",
             "ai_service", "build_prompt", "system_prompt")
NOMS_DE_PROMPT = ("prompt", "system", "instruction", "consigne", "directive")
# Ces modules SONT des tables de motifs : ils doivent reconnaitre les deux registres.
MODULES_DE_MOTIFS = {"microcopy.py", "intelligent_ux.py", "sentrix_intelligent_ux.py"}


def _chaines_utilisateur(chemin: pathlib.Path):
    """Chaines litterales passees en argument a un appel, hors prompts IA."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError:
        return
    parents = {}
    for noeud in ast.walk(arbre):
        for enfant in ast.iter_child_nodes(noeud):
            parents[enfant] = noeud

    # Tout ce qui est affecte a une variable de prompt sort du perimetre.
    hors_perimetre = set()
    for noeud in ast.walk(arbre):
        cibles = []
        if isinstance(noeud, ast.Assign):
            cibles = [ast.unparse(c) for c in noeud.targets]
        elif isinstance(noeud, ast.AnnAssign) and noeud.target is not None:
            cibles = [ast.unparse(noeud.target)]
        if any(any(m in c.lower() for m in NOMS_DE_PROMPT) for c in cibles):
            for descendant in ast.walk(noeud):
                hors_perimetre.add(id(descendant))

    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            texte = noeud.value
        elif isinstance(noeud, ast.JoinedStr):
            texte = "".join(
                v.value for v in noeud.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
        else:
            continue
        if not texte or len(texte) < 8 or id(noeud) in hors_perimetre:
            continue

        parent = parents.get(noeud)
        while parent is not None and not isinstance(
            parent, (ast.Call, ast.Expr, ast.FunctionDef, ast.AsyncFunctionDef, ast.Module, ast.ClassDef)
        ):
            parent = parents.get(parent)
        if not isinstance(parent, ast.Call):
            continue
        cible = ast.unparse(parent.func)
        if any(motif in cible for motif in APPELS_IA) or cible.startswith("re."):
            continue
        yield noeud.lineno, texte


class RegistreUnique(unittest.TestCase):
    def _parcourir(self, motif, etiquette):
        fautifs = []
        for dossier in ("cogs", "utils"):
            for chemin in sorted((RACINE / dossier).glob("*.py")):
                if chemin.name in MODULES_DE_MOTIFS:
                    continue
                for ligne, texte in _chaines_utilisateur(chemin):
                    trouve = motif.search(texte)
                    if trouve:
                        fautifs.append(
                            f"{chemin.name}:{ligne} [{trouve.group(0).strip()}] {texte[:70]!r}"
                        )
        self.assertEqual(
            fautifs, [], f"{etiquette} — le bot vouvoie :\n" + "\n".join(fautifs[:25])
        )

    def test_aucun_pronom_de_tutoiement(self):
        self._parcourir(PRONOM_TU, "tutoiement (tu / ton / ta / tes / toi)")

    def test_aucun_imperatif_au_singulier(self):
        self._parcourir(IMPERATIF_TU, "impératif à la 2e personne du singulier")

    def test_aucun_desaccord_apres_vous(self):
        """« Vous pourras » : une conversion laissee a mi-chemin."""
        self._parcourir(DESACCORD, "accord incorrect après « vous »")


class CoucheDeMicrocopy(unittest.TestCase):
    """utils/microcopy retouche CHAQUE embed premium a l'affichage.

    Ses valeurs de remplacement etaient en tutoiement : la couche reecrivait donc
    les textes convertis vers l'ancien registre au moment de les afficher.
    """

    def test_les_remplacements_vouvoient(self):
        from utils import microcopy

        fautifs = [
            f"{cle!r} -> {valeur!r}"
            for cle, valeur in microcopy._EXACT.items()
            if PRONOM_TU.search(valeur) or IMPERATIF_TU.search(valeur)
        ]
        for _motif, valeur in microcopy._PATTERNS:
            if PRONOM_TU.search(valeur) or IMPERATIF_TU.search(valeur):
                fautifs.append(f"motif -> {valeur!r}")
        self.assertEqual(fautifs, [], "\n".join(fautifs))

    def test_les_deux_registres_sont_encore_reconnus(self):
        """Un texte non encore converti doit continuer d'etre raccourci."""
        from utils import microcopy

        paires = (
            ("Tu n'as pas les permissions nécessaires pour cette action.",
             "Vous n'avez pas les permissions nécessaires pour cette action."),
            ("Réessaie dans quelques instants.", "Réessayez dans quelques instants."),
        )
        for tutoiement, vouvoiement in paires:
            with self.subTest(texte=tutoiement[:30]):
                self.assertEqual(
                    microcopy.polish_text(tutoiement), microcopy.polish_text(vouvoiement)
                )

    def test_la_sortie_ne_tutoie_jamais(self):
        from utils import microcopy

        for entree in (
            "Mentionne le membre concerné **ou réponds directement à son message**, puis reformule ta demande.",
            "L'action n'a pas pu être terminée. Détail technique.",
            "Réessaie ta question.",
        ):
            with self.subTest(entree=entree[:34]):
                sortie = microcopy.polish_text(entree)
                self.assertIsNone(PRONOM_TU.search(sortie), sortie)
                self.assertIsNone(IMPERATIF_TU.search(sortie), sortie)


if __name__ == "__main__":
    unittest.main()
