# Wilbeth – Anbindung an Authentifizierung (AD / Entra ID): Fragen & Bedarf an IAM

## Kontext
Wilbeth ist ein internes Einsatzplanungs-Tool für IT-Azubis/Studis (ersetzt eine
Excel-Lösung). Es läuft als Container auf Kubernetes (Cluster `ai-apps-staging01`,
Namespace `wilbeth`), erreichbar unter
`https://wilbeth.k8s-ai-apps-staging.grenke.com`. Die App ist aktuell **ohne
Authentifizierung** offen; vor dem Produktivbetrieb soll eine Anmeldung gegen
unseren Identity Provider dazukommen.

## Rollen & Berechtigungen
- **Azubi/Studi** – nur **lesende** Sicht auf den **eigenen** Einsatzplan.
- **Ausbilder** – Einsätze planen/bearbeiten.
- **Orga** – organisatorisch (Umfang noch festzulegen).
- **Applikationsadmin** – Stammdaten/Verwaltung.
- **Unauthentifiziert** – kein Zugriff.

## Gewünschter technischer Ansatz
Die App soll **IdP-agnostisch** bleiben: Authentifizierung übernimmt idealerweise
ein **Auth-Sidecar/Proxy** vor der App (analog zu den SCS), der die Identität per
**HTTP-Header** (User + Gruppen) an die App weiterreicht. Die App vertraut diesen
Headern (Pod nur über den Sidecar erreichbar) und leitet daraus die Rolle ab.
App-Credentials liegen **nicht** in der App, sondern in der Container-Config bzw.
im k8s-Secret.

## Fragen / Bedarf an IAM
1. **Identity Provider:** AD oder Entra ID für diese App? (bestimmt das Protokoll:
   Kerberos/LDAP vs. OIDC)
2. **Auth-Sidecar:** Gibt es einen Standard-Sidecar/Proxy (z. B. `oauth2-proxy`
   für OIDC bzw. SPNEGO/Kerberos für AD), den wir wiederverwenden können – oder
   muss die App das Protokoll selbst implementieren?
3. **Gruppen:** Welche AD-/Entra-Gruppen (Namen + IDs) bilden die Rollen
   **Ausbilder**, **Orga**, **Admin** ab? Wer pflegt die Mitgliedschaften?
4. **App-Registration** (falls OIDC/Entra): App-Registration mit `client_id` /
   `client_secret` und erlaubter Redirect-URI
   (`https://wilbeth.k8s-ai-apps-staging.grenke.com/...`). Secret kommt ins k8s-Secret.
5. **Identitäts-Header:** Falls Sidecar – welche Header liefert er (User-Identifier,
   Gruppen) und in welchem Format?
6. **Azubi-Zuordnung:** Haben die Azubis/Studis AD-Accounts? Welches eindeutige
   Attribut (UPN / E-Mail) sollen wir zum Abgleich mit dem Azubi-Datensatz in
   Wilbeth verwenden?
7. **Umgebungen:** Gilt das identisch für Staging und Prod, oder brauchen wir je
   Umgebung getrennte App-Registrations/Gruppen?

## Übergabe an die App (was wir danach brauchen)
- Sidecar-Konfiguration **oder** OIDC-Client (`client_id`/`client_secret`/Redirect)
  + Discovery-URL.
- Gruppen-Namen/-IDs für das Rollen-Mapping (wird in Wilbeth per Env konfiguriert).
- Das Attribut für die Azubi-Zuordnung (UPN / E-Mail).
