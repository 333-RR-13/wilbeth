# Design System: Wilbeth

Hybrid aus Vercel (Praezision, shadow-as-border, typografische Kompression) und Airtable (Blau-Akzent, data-dense, enterprise-freundlich).

Fuer den AI-Agenten: Dieses Dokument ist die verbindliche Design-Referenz. Alle UI-Komponenten folgen diesem System.

---

## 1. Visual Theme & Atmosphere

Internes Admin-Tool fuer Einsatzplanung. Klar, dicht, funktional — kein Marketing-Look.
Dunkle Sidebar (Navy), heller Content-Bereich. Blau nur als Interaktions-Akzent.

---

## 2. Color Palette

### Kern
- **Text Primary** `#171717`: Ueberschriften, Labels
- **Text Secondary** `#4d4d4d`: Beschreibungstext, Metadaten
- **Text Muted** `#808080`: Platzhalter, deaktivierte Elemente
- **Page Background** `#f8fafc`: Seiten-Hintergrund (leicht getoentes Weiss)
- **Surface** `#ffffff`: Karten, Tabellen, Formulare

### Akzent
- **Accent Blue** `#1b61c9`: CTAs, Links, aktive Sidebar-Elemente, Focus-Ring
- **Accent Hover** `#154ea0`: Hover-Zustand fuer blaue Buttons
- **Accent Light** `#ebf3ff`: Badge-Hintergrund, Hover-Hintergrund in Tabellen

### Sidebar
- **Sidebar Bg** `#181d26`: Haupthintergrund Sidebar
- **Sidebar Text** `rgba(255,255,255,0.75)`: Inaktive Nav-Links
- **Sidebar Active Bg** `#1b61c9`: Aktiver Nav-Link Hintergrund
- **Sidebar Active Text** `#ffffff`: Aktiver Nav-Link Text
- **Sidebar Border** `rgba(255,255,255,0.08)`: Trennlinien in Sidebar

### Semantisch
- **Success** `#16a34a`: Erfolgs-Badges, positive Aktionen
- **Success Light** `#f0fdf4`: Erfolgs-Badge-Hintergrund
- **Warning** `#d97706`: Konflikt-Warnungen
- **Warning Light** `#fffbeb`: Warn-Badge-Hintergrund
- **Danger** `#dc2626`: Loeschen, Fehler
- **Danger Light** `#fef2f2`: Fehler-Badge-Hintergrund

### Grenzen (Vercel shadow-as-border)
- **Border Default** `rgba(0,0,0,0.08) 0px 0px 0px 1px`: Standard-Rahmen als Shadow
- **Border Card** `rgba(0,0,0,0.08) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 2px 4px`: Karten-Elevation
- **Border Table** `#e0e2e6`: Tabellen-Rahmen als echte CSS-Border (besser fuer dense tables)

---

## 3. Typography

Font: **Inter** (Google Fonts CDN). Fallback: `-apple-system, system-ui, Segoe UI, Roboto, sans-serif`.

| Rolle | Groesse | Weight | Letter-Spacing | Verwendung |
|---|---|---|---|---|
| Page Title | 24px | 600 | -0.5px | Seiten-Ueberschrift (h1) |
| Section Title | 18px | 600 | -0.3px | Abschnitt (h2) |
| Body | 14px | 400 | normal | Fliessstext, Tabellen |
| Body Medium | 14px | 500 | normal | Navigation, Labels |
| Body Strong | 14px | 600 | normal | Emphasis |
| Caption | 12px | 400 | 0.1px | Metadaten, Badges |
| Caption Strong | 12px | 500 | 0.1px | Badge-Text |

Prinzip: Kompakt und funktional. Keine grossen Display-Groessen — das ist ein Tool, kein Marketing-Auftritt.

---

## 4. Components

### Buttons
- **Primary**: `#1b61c9` Bg, weiss Text, 6px Radius, 8px 14px Padding, 14px weight 500
- **Primary Hover**: `#154ea0`
- **Secondary**: weiss Bg, `#171717` Text, shadow-as-border, 6px Radius
- **Danger**: `#dc2626` Bg, weiss Text, 6px Radius — nur fuer Loeschen-Aktionen
- **Ghost**: transparent, `#4d4d4d` Text, Hover: `#f8fafc` Bg — fuer Tabellen-Actions

Kein Radius > 8px auf Action-Buttons. Pill-Radius (9999px) nur fuer Status-Badges.

### Cards
- Bg: `#ffffff`
- Shadow: `rgba(0,0,0,0.08) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 2px 4px`
- Radius: 8px
- Padding: 24px

### Tables
- Header-Bg: `#f8fafc`
- Header-Text: 12px weight 500 uppercase letter-spacing 0.5px, `#4d4d4d`
- Row-Border: `1px solid #e0e2e6`
- Row Hover-Bg: `#f8fafc`
- Zellen-Padding: 12px 16px

### Inputs & Selects
- Border: `1px solid #e0e2e6`
- Focus-Border: `1px solid #1b61c9` + `0 0 0 3px rgba(27,97,201,0.15)` Box-Shadow
- Radius: 6px
- Padding: 8px 12px
- Font: 14px weight 400
- Placeholder: `#808080`

### Badges / Pills
- Radius: 9999px
- Padding: 2px 8px
- Font: 12px weight 500
- Varianten: success (gruen), warning (orange), danger (rot), neutral (grau), info (blau)

### Sidebar Navigation
- Breite: 240px, fest
- Bg: `#181d26`
- Logo/App-Name: oben, weiss, 15px weight 600
- Nav-Links: 14px weight 500, `rgba(255,255,255,0.75)`, Padding 8px 12px, Radius 6px
- Aktiv: `#1b61c9` Bg, `#ffffff` Text
- Hover: `rgba(255,255,255,0.08)` Bg
- Abschnitt-Label: 11px uppercase letter-spacing 0.8px, `rgba(255,255,255,0.4)`

### Flash Messages
- Padding: 12px 16px
- Radius: 6px
- Shadow-as-border Technik
- Varianten: success / error / info

---

## 5. Layout

- Sidebar: 240px fest links, volle Hoehe
- Content Area: `calc(100vw - 240px)`, scrollt unabhaengig
- Content Padding: 32px
- Content max-width: 1100px (zentriert im Content-Bereich)
- Spacing-Skala: 4px / 8px / 12px / 16px / 24px / 32px / 48px

---

## 6. Do's and Don'ts

### Do
- Shadow-as-border fuer Cards und erhoehte Elemente
- `#1b61c9` nur fuer interaktive Elemente (Buttons, Links, aktive States)
- Inter mit -0.5px Letter-Spacing bei Ueberschriften ab 18px
- Tabellen mit kompaktem Padding (12px 16px) fuer Datendichte

### Don't
- Kein `border-radius > 8px` auf Buttons
- Kein `border-radius > 12px` auf Cards
- Keine Farbe ausser Blau als Akzent in der UI-Chrome
- Keine Dekorations-Schatten — Shadows sind immer funktional (Border oder Elevation)
- Keine externen KI-API-Calls im Produkt
