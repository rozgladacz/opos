# Frontend JavaScript OPOS

Frontend składa się z dwóch małych plików bez frameworka:

- `app/static/js/opos.js` — wspólne zachowania strony, CSRF i proste akcje formularzy.
- `app/static/js/opos_editor.js` — stan modalu oddziału, selektory zdolności, stateless quote oraz zapis profilu.

Edytor odczytuje wersję zasad i dane startowe z atrybutów `data-*` oraz elementów JSON renderowanych przez Jinja. Cena z `/quote` jest wyłącznie podglądem; backend zawsze przelicza ją ponownie przy zapisie.

Zmiana asynchroniczna quote używa numeru żądania, aby spóźniona odpowiedź nie nadpisała nowszego stanu. Tryb custom stats jest właściwością rozpiski, nie globalnym ustawieniem użytkownika.

Po zmianie któregokolwiek pliku:

```powershell
node --check app/static/js/opos.js
node --check app/static/js/opos_editor.js
```

Następnie wykonaj smoke z [testing.md](testing.md), w tym widok mobilny i kontrolę konsoli.
