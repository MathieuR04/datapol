/* shared/nav.js — Datapol unified navigation
   Call initNav(countryCode, electionCode) after the nav HTML is in the DOM. */
(function(global) {
  'use strict';

  var COUNTRIES = [
    { code: 'peru',     flag: '🇵🇪', name: 'Perú',     url: '/electoral/peru/2026eg/primera-vuelta/' },
    { code: 'colombia', flag: '🇨🇴', name: 'Colombia', url: '/electoral/colombia/2026/primera-vuelta/' },
  ];

  var CONFIG = {
    peru: {
      flag: '🇵🇪', name: 'Perú',
      elections: [
        { code: 'primera-vuelta', label: '1ra Vuelta', url: '/electoral/peru/2026eg/primera-vuelta/',  available: true  },
        { code: 'segunda-vuelta', label: '2da Vuelta', url: '/electoral/peru/2026eg/segunda-vuelta/', available: true  },
      ]
    },
    colombia: {
      flag: '🇨🇴', name: 'Colombia',
      elections: [
        { code: 'senado',         label: 'Senado',     url: '/electoral/colombia/2026/senado/',          available: true  },
        { code: 'primarias',      label: 'Primarias',  url: '/electoral/colombia/2026/primarias/',       available: true  },
        { code: 'primera-vuelta', label: '1ra Vuelta', url: '/electoral/colombia/2026/primera-vuelta/',  available: true  },
        { code: 'segunda-vuelta', label: '2da Vuelta', url: '#',                                         available: false },
      ]
    }
  };

  function closeAll() {
    document.querySelectorAll('.nav-country-dropdown.open').forEach(function(d) {
      d.classList.remove('open');
      if (d.parentElement) d.parentElement.classList.remove('open');
    });
  }

  global.initNav = function(countryCode, electionCode) {
    var nav = document.querySelector('.nav');
    var menu = document.getElementById('nav-mob');
    if (!nav) return;

    var country = CONFIG[countryCode];
    if (!country) return;

    var social = nav.querySelector('.nav-social');

    // ── 1. Clear any hardcoded nav-items / nav-sep injected at build time ──
    Array.from(nav.children).forEach(function(child) {
      var cls = child.className || '';
      // Remove nav-items and the separator between brand and social
      // (keep the nav-sep that's INSIDE nav-social — it has inline margin style)
      var isSep  = cls === 'nav-sep' && !child.style.margin;
      var isItem = cls.indexOf('nav-item') !== -1;
      if ((isSep || isItem) && child !== social) nav.removeChild(child);
    });

    // ── 2. Country dropdown ───────────────────────────────────────────────
    var wrap = document.createElement('div');
    wrap.className = 'nav-country-wrap';

    var btn = document.createElement('button');
    btn.className = 'nav-country-btn';
    btn.setAttribute('aria-label', 'Seleccionar país');
    btn.innerHTML =
      '<span>' + country.flag + '</span>' +
      '<span class="nav-country-name">' + country.name.toUpperCase() + '</span>' +
      '<svg class="nav-country-chevron" width="8" height="5" viewBox="0 0 8 5" fill="currentColor" aria-hidden="true">' +
        '<path d="M0 0l4 5 4-5H0z"/>' +
      '</svg>';

    var dropdown = document.createElement('div');
    dropdown.className = 'nav-country-dropdown';

    COUNTRIES.forEach(function(c) {
      var item = document.createElement('a');
      item.className = 'nav-country-item' + (c.code === countryCode ? ' active' : '');
      item.innerHTML = '<span>' + c.flag + '</span>' + c.name;
      if (c.code === countryCode) {
        item.href = '#';
        item.onclick = function(e) { e.preventDefault(); closeAll(); };
      } else {
        item.href = c.url;
      }
      dropdown.appendChild(item);
    });

    btn.onclick = function(e) {
      e.stopPropagation();
      var wasOpen = dropdown.classList.contains('open');
      closeAll();
      if (!wasOpen) {
        var rect = btn.getBoundingClientRect();
        dropdown.style.left = rect.left + 'px';
        dropdown.classList.add('open');
        wrap.classList.add('open');
      }
    };

    wrap.appendChild(btn);
    wrap.appendChild(dropdown);
    nav.insertBefore(wrap, social);

    // ── 3. Separator ──────────────────────────────────────────────────────
    var sep = document.createElement('div');
    sep.className = 'nav-sep';
    nav.insertBefore(sep, social);

    // ── 4. Election tabs ──────────────────────────────────────────────────
    country.elections.forEach(function(el) {
      var item = (el.available && el.code !== electionCode)
        ? document.createElement('a')
        : document.createElement('span');
      item.className = 'nav-item' + (el.code === electionCode ? ' active' : '');
      if (el.available && el.code !== electionCode) item.href = el.url;
      if (!el.available) {
        item.style.cursor = 'default';
        item.innerHTML = el.label + ' <span class="nav-pill">próx.</span>';
      } else {
        item.textContent = el.label;
      }
      nav.insertBefore(item, social);
    });

    // ── 5. Mobile menu ────────────────────────────────────────────────────
    if (menu) {
      menu.innerHTML = '';

      var secHeader = document.createElement('div');
      secHeader.className = 'nav-mob-section';
      secHeader.textContent = 'País';
      menu.appendChild(secHeader);

      COUNTRIES.forEach(function(c) {
        var item = document.createElement('a');
        var isActive = c.code === countryCode;
        item.className = 'nav-mob-item nav-mob-country' + (isActive ? ' active' : ' clickable');
        item.innerHTML = '<span>' + c.flag + '</span> ' + c.name;
        if (isActive) {
          item.href = '#';
          item.onclick = function(e) { e.preventDefault(); menu.classList.remove('open'); };
        } else {
          item.href = c.url;
        }
        menu.appendChild(item);
      });

      var divider = document.createElement('div');
      divider.className = 'nav-mob-divider';
      menu.appendChild(divider);

      var secElec = document.createElement('div');
      secElec.className = 'nav-mob-section';
      secElec.textContent = 'Elección';
      menu.appendChild(secElec);

      country.elections.forEach(function(el) {
        var item = document.createElement('div');
        var isActive  = el.code === electionCode;
        var isDisabled = !el.available;
        item.className = 'nav-mob-item' +
          (isActive   ? ' active'   : '') +
          (!isActive && !isDisabled ? ' clickable' : '');
        item.textContent = el.label + (isDisabled ? ' — PRÓX.' : '');
        if (isDisabled) item.style.opacity = '0.4';
        if (!isActive && !isDisabled) {
          item.onclick = function() { menu.classList.remove('open'); location.href = el.url; };
        }
        menu.appendChild(item);
      });
    }

    // ── 6. Close on outside click ─────────────────────────────────────────
    document.addEventListener('click', function(e) {
      if (!e.target.closest || !e.target.closest('.nav-country-wrap')) closeAll();
      if (menu && !e.target.closest('#nav-hbg') && !e.target.closest('#nav-mob')) {
        menu.classList.remove('open');
      }
    });
  };

})(window);
