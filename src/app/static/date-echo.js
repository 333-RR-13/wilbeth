/*
 * Klartext-Echo fuer alle <input type="date">-Felder.
 *
 * Hintergrund: Das Anzeigeformat von <input type="date"> (z. B. MM/DD/YYYY vs.
 * DD.MM.YYYY) haengt an der BROWSER-Sprache, nicht am lang="de" des Dokuments.
 * Ein Browser mit englischer UI zeigt also MM/DD/YYYY, egal was die Seite tut -
 * "01/09/2024" wird dann leicht als 1. September statt als 9. Januar gelesen.
 * Da sich das Anzeigeformat des nativen Pickers nicht erzwingen laesst, macht
 * dieses Skript stattdessen den TATSAECHLICH GEWAEHLTEN Wert unmissverstaendlich
 * sichtbar: ein deutscher Klartext-Satz (inkl. Wochentag) direkt unter dem Feld.
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

  /** Parst "YYYY-MM-DD" (Format von input[type=date].value) in einen deutschen Klartext-Satz. */
  function formatiereKlartext(isoWert) {
    var teile = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoWert || '');
    if (!teile) return '';
    var jahr = parseInt(teile[1], 10);
    var monatIndex = parseInt(teile[2], 10) - 1;
    var tag = parseInt(teile[3], 10);

    // UTC verwenden, damit die Wochentagsberechnung nicht von der lokalen
    // Zeitzone des Browsers verschoben wird.
    var d = new Date(Date.UTC(jahr, monatIndex, tag));
    var gueltig = d.getUTCFullYear() === jahr
      && d.getUTCMonth() === monatIndex
      && d.getUTCDate() === tag;
    if (!gueltig || monatIndex < 0 || monatIndex > 11) return '';

    var wochentag = WOCHENTAGE[d.getUTCDay()];
    var monatsname = MONATE[monatIndex];
    return wochentag + ', ' + tag + '. ' + monatsname + ' ' + jahr;
  }

  /** Liefert das Echo-Element direkt nach dem Feld, legt es bei Bedarf an. */
  function holeOderErzeugeEchoElement(input) {
    var naechstes = input.nextElementSibling;
    if (naechstes && naechstes.classList && naechstes.classList.contains(ECHO_KLASSE)) {
      return naechstes;
    }
    var el = document.createElement('span');
    el.className = ECHO_KLASSE;
    input.insertAdjacentElement('afterend', el);
    return el;
  }

  function aktualisiereEcho(input) {
    if (!input || input.tagName !== 'INPUT' || input.type !== 'date') return;
    var echo = holeOderErzeugeEchoElement(input);
    var klartext = input.value ? formatiereKlartext(input.value) : '';
    echo.textContent = klartext ? ('= ' + klartext) : '';
  }

  function initialisiereBereich(bereich) {
    if (!bereich || typeof bereich.querySelectorAll !== 'function') return;
    var felder = bereich.querySelectorAll('input[type="date"]');
    for (var i = 0; i < felder.length; i++) {
      aktualisiereEcho(felder[i]);
    }
  }

  // Delegation auf document: greift auch fuer Felder, die erst spaeter
  // (z. B. per HTMX) ins DOM kommen - unabhaengig vom Zeitpunkt der Bindung.
  function istDatumsfeld(el) {
    return !!(el && el.tagName === 'INPUT' && el.type === 'date');
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
