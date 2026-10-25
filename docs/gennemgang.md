# Årsgennemgang

Når en sæson er slut, gennemgås den bed for bed og sort for sort. Det tager
uger, ikke en aften, så gennemgangen er filer, du fylder ud lidt ad gangen,
og ikke en wizard, der skal gøres færdig i ét hug.

```bash
have gennemgang                 # status: hvad er gjort, hvad mangler, hvad er næste
have gennemgang opret           # opret manglende filer (overskriver aldrig)
have gennemgang vis <navn>      # fakta om et bed eller en sort
have gennemgang dom [plante_id] # vælg dom med piletasterne (alle uden dom, eller én)
have gennemgang vejr            # årets vejr mod normalåret 1991–2020
```

Alle tager `--år 2026`. Standard er `aktivt_år` fra `haven.yaml`.

## Filerne

```
data/<år>/gennemgang/bede/<områdefil>-<bed_id>.md   ét pr. bed
data/<år>/gennemgang/bede/<områdefil>.md            område uden bede
data/<år>/gennemgang/sorter/<plante_id>.md          én pr. sort
data/erfaringer.md                                  vokser år for år, nyeste øverst
```

Hver fil har en kort frontmatter til det, maskinen skal kunne læse, og fri
tekst under den:

| Felt | Hvor | Betydning |
|---|---|---|
| `dom` | sort | etårige: `gentag`, `skift-sort`, `drop`, `flyt`. Flerårige: `behold`, `beskær`, `forny`, `fjern` |
| `erstat_med` | sort | `plante_id` for den nye sort ved `skift-sort` |
| `færdig` | bed | `true`, når bedet er gennemgået |
| `skadedyr` | begge | id'er fra `data/skadedyr.yaml` |
| `køb` | begge | ting, der skal købes: jord, net, materialer |

`dom` og `erstat_med` behøver du ikke skrive i hånden. `have gennemgang dom`
går gennem sorterne uden dom og viser en valgliste. Ved `skift-sort` får du
autocomplete på `plante_id`. Kun de to linjer i frontmatteren ændres, og
kommentarerne og din tekst bliver stående. Valget gemmes med det samme, så
Ctrl-C mister intet. Med et `plante_id` kan du rette en enkelt sorts dom.

## Hvornår er noget færdigt?

Status udledes af filerne hver gang. Der er ingen tjekliste ved siden af:

- en **sort** er færdig, når den har en gyldig `dom`
- et **bed** er færdigt, når det har `færdig: true`
- **erfaringerne** er skrevet, når der står tekst under `## <år>` i `data/erfaringer.md`

## Fakta gemmes ikke

`vis` samler dagbogsindlæg, sædskifte, kendte skadedyr og sidste års dom,
hver gang den køres. Retter du et indlæg, slår det igennem med det samme.
Dagbogsindlæg kender kun *området*, ikke bedet. Et indlæg om majroer i
mistbænken dukker derfor også op under Højbed 1, hvis der stod majroer dér.

Normalåret hentes én gang fra Open-Meteo og caches i `.cache/`
(git-ignoreret, og hver maskine har sin egen). Årets eget vejr kommer fra
`almanak.yaml`, så kør `have hent-vejr <år>` først.

## Med Claude

`/havegennemgang` i Claude Code kører `have gennemgang`, finder det næste
punkt og tager det i dialog: fakta fra `vis`, spørgsmål til dig, et forslag
til en dom, og dine svar skrevet ind i filen.

## Næste etaper

2. Frøoptælling, og `have nyt-år` læser dommene, når det skaber næste års bede.
3. Indkøbsliste, såbegivenheder i kalenderen og gennemgang af almanakken.
