# Session brief: Klientside plantefiltrering i almanakken

## Formål

Gøre plantetags funktionelle i almanakken: klik på en plantetag → kun entries
der nævner den plante vises. Klik igen (eller på "Vis alle") → nulstil.
Ingen serverside logik, ingen sideload — ren JavaScript.

## Kontekst

- Almanakken (`out/2026/almanak.html`) er én lang side med 12 månedssektioner.
- Hver sektion kan indeholde entries (`<article class="alm-entry">`).
- Entries har allerede plantetags som `<a class="alm-tag alm-tag-plante">`.
- Tags er i dag links til søgesiden — filtrering er et alternativ/supplement
  der holdes på siden og giver hurtigere feedback.
- `plante_navne`-feltet på entries (Python-side) indeholder de faktiske
  plantenavne som listes bruges til at bygge tags.

## Ønsket adfærd

1. Klik på en plantetag i et entry → alle entries *uden* den plante dæmpes
   (`opacity: 0.25`, `pointer-events: none`).
2. Aktiv filter vises tydeligt — fx en "🌱 Spinat ×"-pill øverst på siden
   eller i den faste nav.
3. Klik på den aktive pill (eller en "Vis alle"-knap) → filter nulstilles.
4. Klik på en *anden* plantetag mens et filter er aktivt → skift filter
   (ikke multi-select i første omgang, det komplicerer UI'et unødigt).
5. Måneder der efter filtrering er helt tomme (ingen synlige entries) kan
   valgfrit skjules eller blot vises tomme — afklar ved implementering.

## Teknisk tilgang

### HTML-ændringer (almanak.html)

Tilføj `data-planter`-attribut på hvert `<article class="alm-entry">` med
plantenavnene som JSON-array — genereret fra `entry.plante_navne`:

```html
<article class="alm-entry"
         data-planter='{{ entry.plante_navne | default([]) | tojson }}'>
```

`tojson` er et indbygget Jinja2-filter — ingen ekstra Python nødvendigt.

Tilføj en filterstatus-beholder øverst på almanaksiden (under `<nav
class="intern-nav">`):

```html
<div id="alm-filter-status" hidden>
  <span id="alm-filter-pill"></span>
  <button id="alm-filter-nulstil">Vis alle</button>
</div>
```

### JavaScript (inline i almanak.html eller separat fil)

Modulet skal:

1. **Delegeret click-handler** på `.alm-tag-plante`: fang klik, kald
   `aktiverFilter(planteNavn)` — og kald `event.preventDefault()` så linket
   til søgesiden ikke følges når filteret er aktivt.

2. **`aktiverFilter(navn)`**:
   - Sæt `data-aktivt-filter = navn` på `<body>` (eller en wrapper).
   - Gennemgå alle `article[data-planter]`: vis dem hvis `JSON.parse(dataset.planter).includes(navn)`, ellers dæmp.
   - Opdater `#alm-filter-pill` med "🌱 {navn} ×" og vis `#alm-filter-status`.
   - Fremhæv den klikkede tag med CSS-klasse `aktiv-filter`.

3. **`nulstilFilter()`**:
   - Fjern alle dæmpninger og `aktiv-filter`-klasse.
   - Skjul `#alm-filter-status`.

4. Overvej: hvis brugeren klikker på samme tag igen → nulstil (toggle).

### CSS-tilføjelser (style.css)

```css
/* Entry dæmpet af filter */
.alm-entry.filtreret-væk {
  opacity: 0.18;
  pointer-events: none;
  transition: opacity .2s;
}

/* Aktiv plantetag */
.alm-tag-plante.aktiv-filter {
  background: #2e7d32; color: #fff;
  border-color: #1b5e20;
}

/* Filterstatus-bar */
#alm-filter-status {
  display: flex; align-items: center; gap: .75rem;
  padding: .5rem 1rem;
  background: #f1f8e9; border: 1px solid #c5e1a5;
  border-radius: 8px; margin-bottom: 1.25rem;
  font-size: .85rem;
}
#alm-filter-nulstil {
  background: none; border: 1px solid #81c784;
  border-radius: 999px; padding: .15rem .6rem;
  cursor: pointer; color: #2e7d32; font-size: .8rem;
}
```

### Python-ændringer

Ingen ændringer til `cli.py` kræves — `entry.plante_navne` findes allerede
på alle entries (tilføjet i commit 5b5e55c).

## Afgrænsning / ikke i scope

- Multi-select (flere aktive filtre samtidig) — for nu kun ét ad gangen.
- Filtrering på tværs af andre sider end almanakken.
- URL-parameter til delt/bookmarkbar filteret URL (kan tilføjes senere med
  `history.replaceState`).
- Skjule/vise hele månedssektioner ved tom filtrering — afklar ved session.

## Verificering

1. `have build` — ingen fejl, `almanak.html` indeholder `data-planter='[…]'`.
2. Åbn siden i browser, klik en plantetag — kun relevante entries vises.
3. Klik "Vis alle" — alt vises igen.
4. Klik taglinket med højreklik/ny fane — søgesiden åbner stadig korrekt
   (preventDefault gælder kun left-click uden modifier).
