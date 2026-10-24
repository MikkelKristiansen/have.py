"""haven.gennemgang — årsgennemgangen: evaluér et år, bed for bed og sort for sort.

Gennemgangen er filer, ikke en wizard: data/<år>/gennemgang/ fyldes ud over
flere uger, og 'have gennemgang' viser, hvad der mangler. Fakta (indlæg,
sædskifte, skadedyr, vejr) genereres hver gang, de vises, og gemmes aldrig.

Pakken bygger ved siden af den gamle kode og læser kun fra den (kontekst,
indlaes, config) — intet i site-bygningen importerer herfra. Undtagelsen
bliver nyt_aar.py, der i etape 2 skal læse dommene.

Moduler:
  stier        hvor filerne bor, og hvad de hedder
  filer        læs frontmatter + opret skabeloner (overskriver aldrig)
  fakta        samler årets bede, sorter og indlæg
  vejr_normal  normalår 1991–2020 fra Open-Meteo, cachet
  status       hvad mangler
  visning      al udskrift til terminalen
  kommando     argparse for 'have gennemgang …'
"""
