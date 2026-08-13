/*
 * Hybrid-Datumsfeld (TEIL 3): sichtbares Textfeld im Format TT.MM.JJJJ +
 * Kalender-Knopf, der ein visuell verstecktes natives <input type="date">
 * oeffnet und das Textfeld befuellt (siehe templates/_partials/datum_feld.html).
 *
 * Hintergrund: <input type="date"> zeigt sein Anzeigeformat je nach
 * Browser-Sprache -- das hat schon zu einem echten Datenfehler gefuehrt
 * (1.9. wurde als 9.1. gespeichert). Das sichtbare Textfeld ist deshalb
 * IMMER TT.MM.JJJJ, unabhaengig von der Browser-Locale; der native Picker
 * dient nur noch als Komfort-Eingabehilfe und sendet selbst NICHTS mit ab
 * (kein name-Attribut auf dem versteckten Feld).
 *
 * Ohne JS bleibt das Textfeld normal von Hand ausfuellbar (TT.MM.JJJJ) --
 * der Kalender-Knopf tut dann einfach nichts (progressive enhancement).
 *
 * Event-Delegation auf document (wie date-echo.js), damit das Skript auch
 * fuer per HTMX nachgeladene Formulare funktioniert.
 */
(function () {
  'use strict';

  function nurZiffern(s) {
    return (s || '').replace(/\D/g, '');
  }

  /** Formatiert Ziffern fortlaufend zu TT.MM.JJJJ waehrend des Tippens. */
  function formatiereEingabe(ziffern) {
    ziffern = ziffern.slice(0, 8);
    var teile = [];
    if (ziffern.length > 0) teile.push(ziffern.slice(0, 2));
    if (ziffern.length > 2) teile.push(ziffern.slice(2, 4));
    if (ziffern.length > 4) teile.push(ziffern.slice(4, 8));
    return teile.join('.');
  }

  function istTextFeld(el) {
    return !!(el && el.tagName === 'INPUT' && el.hasAttribute('data-datum-feld-text'));
  }

  function beiEingabe(e) {
    var input = e.target;
    if (!istTextFeld(input)) return;
    var cursorAmEnde = input.selectionEnd === input.value.length;
    var neuerWert = formatiereEingabe(nurZiffern(input.value));
    if (neuerWert !== input.value) {
      input.value = neuerWert;
      if (cursorAmEnde) {
        input.setSelectionRange(neuerWert.length, neuerWert.length);
      }
    }
  }

  /** "TT.MM.JJJJ" -> "JJJJ-MM-TT" (fuers native Feld), '' bei Nicht-Treffer. */
  function deNachIso(wert) {
    var m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec((wert || '').trim());
    if (!m) return '';
    var tag = ('0' + m[1]).slice(-2);
    var monat = ('0' + m[2]).slice(-2);
    return m[3] + '-' + monat + '-' + tag;
  }

  /** "JJJJ-MM-TT" -> "TT.MM.JJJJ", '' bei Nicht-Treffer. */
  function isoNachDe(wert) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(wert || '');
    if (!m) return '';
    return m[3] + '.' + m[2] + '.' + m[1];
  }

  function beiKlick(e) {
    var btn = e.target.closest('[data-datum-feld-btn]');
    if (!btn) return;
    var wrapper = btn.closest('[data-datum-feld]');
    if (!wrapper) return;
    var textFeld = wrapper.querySelector('[data-datum-feld-text]');
    var nativesFeld = wrapper.querySelector('[data-datum-feld-native]');
    if (!textFeld || !nativesFeld) return;

    // Aktuellen (gueltigen) Textwert als Startwert in den Picker uebernehmen.
    var iso = deNachIso(textFeld.value);
    nativesFeld.value = iso;

    if (typeof nativesFeld.showPicker === 'function') {
      try {
        nativesFeld.showPicker();
        return;
      } catch (err) {
        // Manche Browser werfen (z. B. wenn das Feld gerade nicht fokussierbar
        // ist) -- dann auf den klassischen Klick zurueckfallen.
      }
    }
    nativesFeld.click();
  }

  function beiNativerAenderung(e) {
    var nativesFeld = e.target;
    if (!nativesFeld.matches || !nativesFeld.matches('[data-datum-feld-native]')) return;
    var wrapper = nativesFeld.closest('[data-datum-feld]');
    if (!wrapper) return;
    var textFeld = wrapper.querySelector('[data-datum-feld-text]');
    if (!textFeld) return;
    var de = isoNachDe(nativesFeld.value);
    if (!de) return;
    textFeld.value = de;
    // date-echo.js (und ggf. weitere Listener) ueber die Aenderung informieren.
    textFeld.dispatchEvent(new Event('input', { bubbles: true }));
    textFeld.dispatchEvent(new Event('change', { bubbles: true }));
  }

  document.addEventListener('input', beiEingabe);
  document.addEventListener('click', beiKlick);
  document.addEventListener('change', beiNativerAenderung);
})();
