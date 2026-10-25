"""haven.gennemgang.visning — al udskrift til terminalen.

Det eneste modul i pakken, der printer. Modtager færdige data fra fakta,
status og vejr_normal og beslutter kun, hvordan de ser ud.
"""

from ..kontekst import MÅNEDER, PLANTE_DB
from . import fakta
from .filer import læs
from .status import Status, Punkt, FÆRDIG, I_GANG, MANGLER
from .stier import sort_fil, ERFARINGER_FIL

__all__ = ["vis_status", "vis_oprettet", "vis_dom_hoved", "vis_dom_gemt", "vis_dom_besked",
           "vis_bed", "vis_sort", "vis_vejr"]

_IKON = {FÆRDIG: "✅", MANGLER: "·", I_GANG: "✏️ "}


def _plantenavn(plante_id: str) -> str:
    p = PLANTE_DB.get(plante_id)
    if not p:
        return f"{plante_id} (ukendt i planter.yaml)"
    return f"{p.get('navn', plante_id)} — {p['sort']}" if p.get("sort") else p.get("navn", plante_id)


def _måneder(fra, til) -> str:
    if fra and til:
        return f"{MÅNEDER[fra - 1]}–{MÅNEDER[til - 1]}"
    return ""


def _indlæg_linje(e: dict) -> str:
    tekst = " ".join(str(e.get("tekst", "")).split())
    if len(tekst) > 110:
        tekst = tekst[:107] + "…"
    return f"  {e.get('dato', '?')}  {tekst}"


def _punkter(overskrift: str, punkter: list[Punkt], forklaring) -> None:
    """forklaring(punkt) er teksten i anden kolonne; første kolonne er det
    navn, 'have gennemgang vis' skal have."""
    færdige = sum(p.tilstand == FÆRDIG for p in punkter)
    print(f"\n{overskrift} ({færdige}/{len(punkter)} færdige)")
    for p in punkter:
        print(f"  {_IKON.get(p.tilstand, '?')} {p.sti.stem:<32} {forklaring(p)}")
        for problem in p.problemer:
            print(f"      ⚠️  {problem}")


def vis_status(status: Status) -> None:
    print(f"🌱 Gennemgang af {status.år}")
    for p in status.påmindelser:
        print(f"⏰ {p}")
    _punkter("Bede", status.bede, lambda p: p.navn)
    _punkter("Sorter", status.sorter, lambda p: _plantenavn(p.navn))
    print(f"\nErfaringer: {'✅ skrevet' if status.erfaringer else '· ikke skrevet'}"
          f"  ({ERFARINGER_FIL.name}, afsnit ## {status.år})")

    næste = status.næste()
    if næste is None:
        print("\n🎉 Alt er gennemgået. Næste skridt er planen (etape 2).")
    elif næste == "erfaringer":
        print("\n➡️  Næste: erfaringerne")
    else:
        hvad = "opret filerne med 'have gennemgang opret'" if næste.tilstand == MANGLER \
            else næste.sti.name
        print(f"\n➡️  Næste: {næste.sti.stem} — {hvad}")


def vis_oprettet(oprettede: list[str]) -> None:
    if not oprettede:
        print("ℹ️  Alle filer fandtes i forvejen — intet oprettet.")
        return
    print(f"✅ {len(oprettede)} fil(er) oprettet:")
    for navn in oprettede:
        print(f"  + {navn}")


def vis_dom_hoved(år: int, plante_id: str, nr: int, i_alt: int, alle_indlæg: list) -> None:
    """Kort hoved før spørgsmålet i 'have gennemgang dom'. Hele billedet: 'vis'."""
    tæller = f"   ({nr}/{i_alt})" if i_alt > 1 else ""
    print(f"\n🌿 {_plantenavn(plante_id)} — {år}{tæller}")
    dele = [f"Dagbog: {len(fakta.indlæg_for_sort(alle_indlæg, plante_id))} indlæg"]
    sidste = sort_fil(år - 1, plante_id)
    if sidste.exists():
        dele.append(f"sidste år: {læs(sidste)[0].get('dom') or '—'}")
    print("   " + " · ".join(dele))


def vis_dom_gemt(navn: str, dom: str, erstat_med: str | None) -> None:
    ekstra = f" → {erstat_med}" if erstat_med else ""
    print(f"✓ {navn}: {dom}{ekstra}")


def vis_dom_besked(tekst: str) -> None:
    print(tekst)


def vis_bed(år: int, område: fakta.Område, bed: fakta.Bed | None, alle_indlæg: list) -> None:
    print(f"🪴 {område.titel}{' — ' + bed.navn if bed else ''} ({år})")
    if bed and bed.noter:
        print(f"   Noter: {bed.noter}")

    plante_ids = []
    print("\nStod her:")
    if bed:
        for a in bed.afgrøder:
            plante_ids.append(a.plante_id)
            print(f"  {a.zone:<28} {_plantenavn(a.plante_id):<36} {_måneder(a.fra, a.til)}")
    else:
        for pid in område.løse_planter:
            plante_ids.append(pid)
            print(f"  {_plantenavn(pid)}")

    tunge = fakta.tunge_familier(år, område)
    if any(tunge.values()):
        print("\nSædskifte (tunge familier i området):")
        for å, etiketter in tunge.items():
            print(f"  {å}: {', '.join(etiketter) or '—'}")

    områdets = fakta.indlæg_for_område(alle_indlæg, område)
    om_bedet = [e for e in områdets if set(e["plante_id"]) & set(plante_ids)]
    øvrige = [e for e in områdets if not e["plante_id"]]
    # Indlæg kender området, ikke bedet: et indlæg om majroer i mistbænken
    # dukker også op under Højbed 1, hvis der stod majroer dér.
    print(f"\nDagbog fra {område.titel} om planter, der stod her ({len(om_bedet)}):")
    for e in om_bedet:
        print(_indlæg_linje(e))
    if øvrige:
        print(f"\nDagbog om {område.titel} uden plante ({len(øvrige)}):")
        for e in øvrige:
            print(_indlæg_linje(e))


def vis_sort(år: int, plante_id: str, steder: list, alle_indlæg: list) -> None:
    p = PLANTE_DB.get(plante_id) or {}
    print(f"🌿 {_plantenavn(plante_id)} ({år})")
    if p.get("familie"):
        print(f"   Familie: {p['familie']}")
    kalender = [(navn, p.get(felt)) for navn, felt in
                (("indendørs", "indendørs"), ("udplantning", "udplantning"),
                 ("direkte", "direkte"), ("høst fra", "høst_fra"), ("høst til", "høst_til"))]
    kalender = [f"{navn} {MÅNEDER[m - 1]}" for navn, m in kalender if m]
    if kalender:
        print(f"   Kalender: {', '.join(kalender)}")
    if p.get("noter"):
        print(f"   Noter i planter.yaml: {p['noter']}")

    print("\nStod her:")
    for s in steder:
        hvor = s.område.titel + (f" — {s.bed.navn}" if s.bed else "")
        zone = f", {s.afgrøde.zone}" if s.afgrøde and s.afgrøde.zone else ""
        tid = _måneder(s.afgrøde.fra, s.afgrøde.til) if s.afgrøde else ""
        print(f"  {hvor}{zone}  {tid}")

    indlæg = fakta.indlæg_for_sort(alle_indlæg, plante_id)
    print(f"\nDagbog ({len(indlæg)}):")
    for e in indlæg:
        print(_indlæg_linje(e))

    skadedyr = fakta.kendte_skadedyr(plante_id)
    if skadedyr:
        print("\nKendte skadedyr: " + ", ".join(f"{s['navn']} ({s['id']})" for s in skadedyr))

    sidste = sort_fil(år - 1, plante_id)
    if sidste.exists():
        fm, _ = læs(sidste)
        print(f"\nDom sidste år ({år - 1}): {fm.get('dom') or '—'}")


def _tal(v, enhed: str) -> str:
    return f"{v:>6.1f}{enhed}" if isinstance(v, (int, float)) else f"{'—':>6} "


def vis_vejr(år: int, rækker: list[dict] | None) -> None:
    if rækker is None:
        print(f"ℹ️  Intet vejr for {år} i almanak.yaml — kør 'have hent-vejr {år}' først.")
        return
    print(f"🌦️  Vejret {år} mod normalåret 1991–2020\n")
    print(f"  {'måned':<10} {'middel':>7} {'normal':>7} {'nedbør':>8} {'normal':>8}")
    for r in rækker:
        print(f"  {r['måned']:<10} {_tal(r['middel'], '°')} {_tal(r['normal_middel'], '°')}"
              f" {_tal(r['nedbør'], 'mm')} {_tal(r['normal_nedbør'], 'mm')}")
