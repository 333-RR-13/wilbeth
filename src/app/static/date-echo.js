/*
 * Klartext-Echo fuer Datumsfelder: native <input type="date"> UND das neue
 * Hybrid-Textfeld TT.MM.JJJJ (s. templates/_partials/datum_feld.html, TEIL 3).
 *
 * Hintergrund: Das Anzeigeformat von <input type="date"> (z. B. MM/DD/YYYY vs.
 * DD.MM.YYYY) haengt an der BROWSER-Sprache, nicht am lang="de" des Dokuments.
 * Ein Browser mit englischer UI zeigt also MM/DD/YYYY, egal was die Seite tut -
 * "01/09/2024" wird dann leicht als 1. September statt als 9. Januar gelesen.
 * Deshalb wurden die nativen Felder ueberwiegend durch ein sichtbares
 * Textfeld im festen Format TT.MM.JJJJ ersetzt -- unabhaengig von der
 * Locale ist das Format hier eindeutig. Dieses Skript macht den TATSAECHLICH
 * gewaehlten/eingegebenen Wert zusaetzlich unmissverstaendlich sichtbar: ein
 * deutscher Klartext-Satz (inkl. Wochentag) direkt unter dem Feld -- oder,
 * bei einer (noch) ungueltigen Texteingabe, einen dezenten Hinweis statt
 * eines (falschen) Datums.
 *
 * Bewusst KEIN toLocaleDateString('de-DE', ...): das haengt wieder von der
 * System-/Browser-Locale ab - genau das Problem, das wir umgehen wollen. Die
 * deutschen Monats- und Wochentagsnamen sind daher fest im Skript hinterlegt.
 *
 * Wird programmweit ueber base.html UND share/_base.html eingebunden. Damit es
 * auch fuer per HTMX nachgeladene Formulare funktioniert, arbeitet das Skript
 * mit Event-Delegation auf document (statt einmaliger Initialisierung beim
 * Laden) plus einer Nachinitialisierung fuer bereits vorbefuellte Felder.
 */
(function () {
  'use strict';

  var WOCHENTAGE = [
    'Sonntag', 'Montag', 'Dienstag', 'Mittwoch',
    'Donnerstag', 'Freitag', 'Samstag',
  ];

  var MONATE = [
    'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
    'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
  ];

  var ECHO_KLASSE = 'date-echo';
  var ECHO_HINWEIS_KLASSE = 'date-echo-hinweis';
  var HINWEIS_TEXT = 'ungültiges Datum – bitte TT.MM.JJJJ';

  /** Baut aus Jahr/Monat(0-basiert)/Tag ein UTC-Datum, oder null wenn ungueltig
   * (z. B. 31. Februar -- Date normalisiert sowas sonst stillschweigend). */
  function baueGueltigesDatum(jahr, monatIndex, tag) {
    if (monatIndex < 0 || monatIndex > 11) return null;
    var d = new Date(Date.UTC(jahr, monatIndex, tag));
    var gueltig = d.getUTCFullYear() === jahr
      && d.getUTCMonth() === monatIndex
      && d.getUTCDate() === tag;
    return gueltig ? d : null;
  }

  function klartextAus(jahr, monatIndex, tag) {
    var d = baueGueltigesDatum(jahr, monatIndex, tag);
    if (!d) return '';
    var wochentag = WOCHENTAGE[d.getUTCDay()];
    var monatsname = MONATE[monatIndex];
    return wochentag + ', ' + tag + '. ' + monatsname + ' ' + jahr;
  }

  /** Parst "YYYY-MM-DD" (Wert von input[type=date]) in einen deutschen Klartext-Satz. */
  function formatiereIso(isoWert) {
    var teile = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoWert || '');
    if (!teile) return '';
    return klartextAus(parseInt(teile[1], 10), parseInt(teile[2], 10) - 1, parseInt(teile[3], 10));
  }

  /** Parst "TT.MM.JJJJ" (Wert des Hybrid-Textfelds) in einen deutschen Klartext-Satz. */
  function formatiereDeutsch(deWert) {
    var teile = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec((deWert || '').trim());
    if (!teile) return '';
    return klartextAus(parseInt(teile[3], 10), parseInt(teile[2], 10) - 1, parseInt(teile[1], 10));
  }

  function istNativesDatumsfeld(el) {
    return !!(el && el.tagName === 'INPUT' && el.type === 'date');
  }

  function istTextDatumsfeld(el) {
    return !!(el && el.tagName === 'INPUT' && el.hasAttribute('data-datum-feld-text'));
  }

  /** Element, NACH dem das Echo eingefuegt wird: beim Hybrid-Textfeld ist das
   * der gesamte Wrapper (Textfeld+Knopf+verstecktes natives Feld), damit das
   * Echo sichtbar UNTER der ganzen Zeile landet statt zwischen Textfeld und
   * Kalender-Knopf. Beim klassischen input[type=date] das Feld selbst. */
  function holeAnkerElement(input) {
    if (istTextDatumsfeld(input)) {
      return input.closest('[data-datum-feld]') || input;
    }
    return input;
  }

  /** Liefert das Echo-Element direkt nach dem Anker, legt es bei Bedarf an. */
  function holeOderErzeugeEchoElement(anker) {
    var naechstes = anker.nextElementSibling;
    if (naechstes && naechstes.classList && naechstes.classList.contains(ECHO_KLASSE)) {
      return naechstes;
    }
    var el = document.createElement('span');
    el.className = ECHO_KLASSE;
    anker.insertAdjacentElement('afterend', el);
    return el;
  }

  function aktualisiereEcho(input) {
    var nativ = istNativesDatumsfeld(input);
    var text = istTextDatumsfeld(input);
    if (!nativ && !text) return;

    var echo = holeOderErzeugeEchoElement(holeAnkerElement(input));
    var rohwert = (input.value || '').trim();

    if (!rohwert) {
      echo.textContent = '';
      echo.classList.remove(ECHO_HINWEIS_KLASSE);
      return;
    }

    var klartext = nativ ? formatiereIso(rohwert) : formatiereDeutsch(rohwert);
    if (klartext) {
      echo.textContent = '= ' + klartext;
      echo.classList.remove(ECHO_HINWEIS_KLASSE);
    } else if (text) {
      // Nur beim Textfeld: eine (noch) ungueltige Eingabe bekommt einen
      // dezenten Hinweis statt eines (falschen) Datums. Beim nativen Feld
      // liefert der Browser ohnehin nie einen unvollstaendigen/kaputten Wert.
      echo.textContent = HINWEIS_TEXT;
      echo.classList.add(ECHO_HINWEIS_KLASSE);
    } else {
      echo.textContent = '';
      echo.classList.remove(ECHO_HINWEIS_KLASSE);
    }
  }

  function initialisiereBereich(bereich) {
    if (!bereich || typeof bereich.querySelectorAll !== 'function') return;
    var felder = bereich.querySelectorAll('input[type="date"], input[data-datum-feld-text]');
    for (var i = 0; i < felder.length; i++) {
      aktualisiereEcho(felder[i]);
    }
  }

  // Delegation auf document: greift auch fuer Felder, die erst spaeter
  // (z. B. per HTMX) ins DOM kommen - unabhaengig vom Zeitpunkt der Bindung.
  function istDatumsfeld(el) {
    return istNativesDatumsfeld(el) || istTextDatumsfeld(el);
  }

  document.addEventListener('input', function (e) {
    if (istDatumsfeld(e.target)) aktualisiereEcho(e.target);
  });
  document.addEventListener('change', function (e) {
    if (istDatumsfeld(e.target)) aktualisiereEcho(e.target);
  });

  // Initialisierung fuer bereits vorbefuellte Felder beim (Nach-)Laden.
  document.addEventListener('DOMContentLoaded', function () {
    initialisiereBereich(document);
  });
  document.addEventListener('htmx:afterSwap', function (e) {
    initialisiereBereich(e.target || document);
  });
  document.addEventListener('htmx:load', function (e) {
    initialisiereBereich(e.target || document);
  });

  // Falls dieses Skript erst nach DOMContentLoaded ausgefuehrt wird (z. B.
  // weil es Teil eines per HTMX nachgeladenen Fragments waere), trotzdem
  // sofort einmal initialisieren.
  if (document.readyState === 'interactive' || document.readyState === 'complete') {
    initialisiereBereich(document);
  }
})();
