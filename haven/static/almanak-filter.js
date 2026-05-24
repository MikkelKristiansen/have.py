/* Klientside plantefiltrering til almanakken */
(function () {
  'use strict';

  const FILTER_KLASSE = 'filtreret-væk';
  const AKTIV_KLASSE  = 'aktiv-filter';

  function aktiverFilter(navn, klikketTag) {
    // Fjern tidligere aktiv markering
    document.querySelectorAll('.' + AKTIV_KLASSE)
      .forEach(el => el.classList.remove(AKTIV_KLASSE));

    // Dæmp entries der ikke nævner planten, vis dem der gør
    document.querySelectorAll('article[data-planter]').forEach(artikel => {
      let planter;
      try { planter = JSON.parse(artikel.dataset.planter); } catch { planter = []; }
      artikel.classList.toggle(FILTER_KLASSE, !planter.includes(navn));
    });

    // Skjul månedssektioner der nu er helt tomme for entries
    opdaterMåneder();

    // Markér den klikkede tag
    if (klikketTag) klikketTag.classList.add(AKTIV_KLASSE);

    // Opdater filterstatus-bar
    const pill = document.getElementById('alm-filter-pill');
    if (pill) pill.textContent = '🌱 ' + navn + ' ×';
    const status = document.getElementById('alm-filter-status');
    if (status) status.hidden = false;

    document.body.dataset.aktivtFilter = navn;
  }

  function nulstilFilter() {
    document.querySelectorAll('.' + FILTER_KLASSE)
      .forEach(el => el.classList.remove(FILTER_KLASSE));
    document.querySelectorAll('.' + AKTIV_KLASSE)
      .forEach(el => el.classList.remove(AKTIV_KLASSE));

    // Vis alle månedssektioner igen
    document.querySelectorAll('details.alm-måned')
      .forEach(s => { s.hidden = false; });

    const status = document.getElementById('alm-filter-status');
    if (status) status.hidden = true;

    delete document.body.dataset.aktivtFilter;
  }

  function opdaterMåneder() {
    document.querySelectorAll('details.alm-måned').forEach(sektion => {
      const entries = sektion.querySelectorAll('article.alm-entry');
      // Måneder uden entries overhovedet vises altid
      if (entries.length === 0) { sektion.hidden = false; return; }
      const harSynlige = [...entries].some(e => !e.classList.contains(FILTER_KLASSE));
      sektion.hidden = !harSynlige;
    });
  }

  // Delegeret click-handler — ét event listener klarer hele siden
  document.addEventListener('click', function (e) {
    // Nulstil-knap
    if (e.target.id === 'alm-filter-nulstil') {
      nulstilFilter();
      return;
    }

    // Plantetag
    const tag = e.target.closest('.alm-tag-plante');
    if (!tag) return;

    // Lad højreklik / Ctrl+klik / Shift+klik / Middle-click følge linket normalt
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;

    e.preventDefault();

    const navn = tag.textContent.replace(/^🌱\s*/, '').trim();

    // Toggle: klik på allerede aktivt filter → nulstil
    if (document.body.dataset.aktivtFilter === navn) {
      nulstilFilter();
    } else {
      aktiverFilter(navn, tag);
    }
  });
})();
