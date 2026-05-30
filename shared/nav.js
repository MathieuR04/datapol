/* shared/nav.js — Datapol unified navigation
   initNav(countryCode, processCode, electionCode) */
(function(global) {
  'use strict';

  /* ── Data ─────────────────────────────────────────────────────────────────
     Three-level hierarchy: Country → Process → Election
     Add new processes/elections here; pages need no changes.             */
  var CONFIG = {
    peru: {
      flag: '🇵🇪', name: 'Perú',
      processes: [
        {
          code: '2026eg', label: '2026 EG', fullLabel: 'Elecciones Generales 2026',
          elections: [
            { code: 'segunda-vuelta',     label: '2da Vuelta',        url: '/electoral/peru/2026eg/segunda-vuelta/', available: true  },
            { code: 'primera-vuelta',     label: '1ra Vuelta',        url: '/electoral/peru/2026eg/primera-vuelta/', available: true  },
            { code: 'senado',             label: 'Senado',            url: '#',                                      available: false },
            { code: 'diputados',          label: 'Diputados',         url: '#',                                      available: false },
            { code: 'parlamento-andino',  label: 'Parl. Andino',      url: '#',                                      available: false },
          ]
        },
        /* Future — uncomment and fill URLs when ready:
        { code: '2026erm', label: '2026 ERM', fullLabel: 'Elecciones Regionales y Municipales 2026', elections: [] },
        { code: '2021eg',  label: '2021 EG',  fullLabel: 'Elecciones Generales 2021', elections: [] },
        */
      ]
    },
    colombia: {
      flag: '🇨🇴', name: 'Colombia',
      processes: [
        {
          code: '2026', label: '2026', fullLabel: 'Elecciones 2026',
          elections: [
            { code: 'primera-vuelta', label: '1ra Vuelta', url: '/electoral/colombia/2026/primera-vuelta/',  available: true  },
            { code: 'primarias',      label: 'Primarias',  url: '/electoral/colombia/2026/primarias/',       available: true  },
            { code: 'senado',         label: 'Senado',     url: '/electoral/colombia/2026/senado/',          available: true  },
            { code: 'segunda-vuelta', label: '2da Vuelta', url: '#',                                         available: false },
            { code: 'diputados',      label: 'Diputados',  url: '#',                                         available: false },
          ]
        },
      ]
    }
  };

  var COUNTRIES = Object.keys(CONFIG).map(function(k) {
    return { code: k, flag: CONFIG[k].flag, name: CONFIG[k].name };
  });

  /* ── Helpers ────────────────────────────────────────────────────────────── */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls)  e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function closeAll() {
    document.querySelectorAll('.nav-dropdown.open').forEach(function(d) {
      d.classList.remove('open');
      if (d.parentElement) d.parentElement.classList.remove('open');
    });
  }

  function makeDropdownWrap(btnHTML, items) {
    var wrap     = el('div', 'nav-dropdown-wrap');
    var btn      = el('button', 'nav-dropdown-btn');
    btn.innerHTML = btnHTML;
    var list     = el('div', 'nav-dropdown');
    items.forEach(function(i) { list.appendChild(i); });

    btn.onclick = function(e) {
      e.stopPropagation();
      var wasOpen = list.classList.contains('open');
      closeAll();
      if (!wasOpen) {
        var rect = btn.getBoundingClientRect();
        list.style.left = rect.left + 'px';
        list.classList.add('open');
        wrap.classList.add('open');
      }
    };
    wrap.appendChild(btn);
    wrap.appendChild(list);
    return wrap;
  }

  function chevron() {
    return '<svg class="nav-chevron" width="8" height="5" viewBox="0 0 8 5" fill="currentColor" aria-hidden="true"><path d="M0 0l4 5 4-5H0z"/></svg>';
  }

  /* ── Main ─────────────────────────────────────────────────────────────── */
  global.initNav = function(countryCode, processCode, electionCode) {
    var nav  = document.querySelector('.nav');
    var menu = document.getElementById('nav-mob');
    if (!nav) return;

    var country = CONFIG[countryCode];
    if (!country) return;
    var process = country.processes.find(function(p) { return p.code === processCode; });
    if (!process) process = country.processes[0];

    var social = nav.querySelector('.nav-social');

    /* Clear any previously injected items */
    Array.from(nav.children).forEach(function(child) {
      var cls = child.className || '';
      var isSep  = cls === 'nav-sep' && !child.style.margin;
      var isItem = cls.indexOf('nav-item') !== -1 || cls.indexOf('nav-dropdown') !== -1;
      if ((isSep || isItem) && child !== social) nav.removeChild(child);
    });

    /* ── Desktop: Country dropdown ──────────────────────────────────────── */
    var countryItems = COUNTRIES.map(function(c) {
      var a = el('a', 'nav-dropdown-item' + (c.code === countryCode ? ' active' : ''));
      a.innerHTML = '<span>' + c.flag + '</span> ' + c.name;
      if (c.code !== countryCode) {
        /* Navigate to first available election of first process */
        var firstProcess = CONFIG[c.code].processes[0];
        var firstEl = firstProcess.elections.find(function(e) { return e.available; });
        a.href = firstEl ? firstEl.url : '#';
      } else {
        a.href = '#';
        a.onclick = function(e) { e.preventDefault(); closeAll(); };
      }
      return a;
    });
    var countryWrap = makeDropdownWrap(
      country.flag + ' <span>' + country.name.toUpperCase() + '</span>' + chevron(),
      countryItems
    );
    nav.insertBefore(countryWrap, social);

    /* ── Desktop: Process dropdown ──────────────────────────────────────── */
    var sepA = el('div', 'nav-sep');
    nav.insertBefore(sepA, social);

    var processItems = country.processes.map(function(p) {
      var item = el('div', 'nav-dropdown-item' + (p.code === processCode ? ' active' : ''));
      item.textContent = p.fullLabel;
      if (p.code !== processCode) {
        var firstEl = p.elections.find(function(e) { return e.available; });
        item.style.cursor = 'pointer';
        item.onclick = function() { closeAll(); if (firstEl) location.href = firstEl.url; };
      } else {
        item.style.cursor = 'default';
      }
      return item;
    });
    var processWrap = makeDropdownWrap(
      '<span>' + process.label + '</span>' + chevron(),
      processItems
    );
    nav.insertBefore(processWrap, social);

    /* ── Desktop: Election tabs ─────────────────────────────────────────── */
    var sepB = el('div', 'nav-sep');
    nav.insertBefore(sepB, social);

    process.elections.forEach(function(e) {
      var item = (e.available && e.code !== electionCode)
        ? document.createElement('a')
        : document.createElement('span');
      item.className = 'nav-item' + (e.code === electionCode ? ' active' : '');
      if (e.available && e.code !== electionCode) item.href = e.url;
      if (!e.available) {
        item.style.cursor = 'default';
        item.innerHTML = e.label + ' <span class="nav-pill">próx.</span>';
      } else {
        item.textContent = e.label;
      }
      nav.insertBefore(item, social);
    });

    /* ── Mobile menu (hierarchical, no auto-navigate for country/process) ─ */
    if (!menu) return;

    var mobState = { country: countryCode, process: processCode };

    function renderMobile() {
      menu.innerHTML = '';

      var mCountry = CONFIG[mobState.country];
      var mProcess = mCountry.processes.find(function(p) { return p.code === mobState.process; })
                     || mCountry.processes[0];

      /* PAÍS */
      menu.appendChild(el('div', 'nav-mob-section', 'País'));
      COUNTRIES.forEach(function(c) {
        var isSelected = c.code === mobState.country;
        var row = el('div', 'nav-mob-item nav-mob-country' + (isSelected ? ' active' : ' clickable'));
        row.innerHTML = c.flag + ' ' + c.name;
        if (!isSelected) {
          row.onclick = function() {
            mobState.country = c.code;
            mobState.process = CONFIG[c.code].processes[0].code;
            renderMobile();
          };
        }
        menu.appendChild(row);
      });

      /* PROCESO */
      menu.appendChild(el('div', 'nav-mob-divider'));
      menu.appendChild(el('div', 'nav-mob-section', 'Proceso'));
      mCountry.processes.forEach(function(p) {
        var isSelected = p.code === mobState.process;
        var row = el('div', 'nav-mob-item' + (isSelected ? ' active' : ' clickable'));
        row.textContent = p.fullLabel;
        if (!isSelected) {
          row.onclick = function() {
            mobState.process = p.code;
            renderMobile();
          };
        }
        menu.appendChild(row);
      });

      /* ELECCIÓN */
      menu.appendChild(el('div', 'nav-mob-divider'));
      menu.appendChild(el('div', 'nav-mob-section', 'Elección'));
      mProcess.elections.forEach(function(e) {
        var isCurrentPage = e.code === electionCode
                          && mobState.country === countryCode
                          && mobState.process  === processCode;
        var row = el('div', 'nav-mob-item'
          + (isCurrentPage   ? ' active'   : '')
          + (!isCurrentPage && e.available ? ' clickable' : ''));
        row.textContent = e.label + (!e.available ? ' — PRÓX.' : '');
        if (!e.available) row.style.opacity = '0.4';
        if (!isCurrentPage && e.available) {
          row.onclick = function() { menu.classList.remove('open'); location.href = e.url; };
        }
        menu.appendChild(row);
      });
    }

    renderMobile();

    /* Close on outside click */
    document.addEventListener('click', function(e) {
      if (!e.target.closest || !e.target.closest('.nav-dropdown-wrap')) closeAll();
      if (!e.target.closest('#nav-hbg') && !e.target.closest('#nav-mob')) {
        menu.classList.remove('open');
      }
    });
  };

})(window);
