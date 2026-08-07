# QA — meshcore-ha + reply stagger (RFC-0002 §8)

**Cel:** po `all ping` / `all discovery` w **chacie HA** widać odpowiedzi **wszystkich** węzłów (np. `button` **i** `mcYogi`), nie tylko HA.

**Stack:**
| Component | Tag / version |
|-----------|----------------|
| mcrpc | [v1.2.2](https://github.com/tj57/mcrpc/releases/tag/v1.2.2) |
| meshcore-ha | [v2.12.2](https://github.com/tj57/meshcore-ha/releases/tag/v2.12.2) |
| MeshCore firmware | [mcrpc-1.2.2](https://github.com/tj57/MeshCore/releases/tag/mcrpc-1.2.2) (Heltec + LW010) |
| RFC | [RFC-0002 §8](https://github.com/tj57/mcrpc/blob/v1.2.2/docs/rfc/RFC-0002-mcrpc-1.2-slim-call.md) |

**Constraints:** bez zmian nazw/PSK; **zero TX na Public** (tylko ch1 / mcCtrl).

---

## A. Przygotowanie HA

1. HACS → MeshCore → update do **2.12.2** (Installed = Available, pending false).
2. Restart Home Assistant.
3. Diagnostics / log: runtime `mcrpc` library **1.2.2**, protocol **1.2**.
4. Entry bez zmian: name `mcYogi`, title `mcCtrl`, listen `[1]`, kanał 1 = mcCtrl.

Opcjonalnie włącz **Debug logging for node requests** — w śladach szukaj `tx_jitter` przy odpowiedziach na `all`.

---

## B. Flash urządzeń (gdy USB)

- Heltec: `Heltec_v3_mcrpc_button` z release **mcrpc-1.2.2** (prefer merged @ 0x0).
- LW010: `LW010_mcrpc_gps` z tego samego release.
- Po flashu: `all discovery` → `button … v=1.2` (slim).

Bez USB: wykonaj sekcję C tylko z HA + Android (regresja chatu HA vs app).

---

## C. Scenariusz główny — multi-reply w chacie HA

### C1. Z Androida (osobny TX)

Na ch1 wyślij z apk:

```text
all ping
```

| Check | PASS | FAIL |
|-------|------|------|
| Android widzi | `pong` od **button** i **mcYogi** (kolejność dowolna) | tylko jeden |
| Chat HA widzi | **oba** `pong` (HA + button) | tylko bąbelek HA / brak button |
| Timing | odpowiedzi rozłożone w czasie (~0.25–1.75 s stagger) | obie w tej samej milisekundzie |

Powtórz:

```text
all discovery
```

| Check | PASS | FAIL |
|-------|------|------|
| HA chat | linia slim `mcYogi id=… v=1.2 …` **oraz** linia `button id=… v=1.2 …` | tylko HA |
| Kształt | 8-hex `id=`, brak `protocol=`/`sdk=`/`features=` | kształt 1.1 |

### C2. Z chatu HA (lokalny TX + auto-answer)

W MeshCore Chat (HA) na ch1:

```text
all ping
```

| Check | PASS | FAIL |
|-------|------|------|
| Własny `pong` HA | widoczny (outgoing) | brak |
| `pong` od button | pojawia się w historii chatu | Unheard / brak inbound |
| Trace (debug) | `tx_jitter` z `broadcast=true`, `delay_sec` ∈ [0.25, 1.75] | natychmiastowy TX bez jitter |

```text
all discovery
```

To samo: discovery od **button** musi wejść do chatu HA (inbound `CHANNEL_MSG_RECV`).

---

## D. Regresje (nie psuć 1.2)

| Komenda | Oczekiwane |
|---------|------------|
| `mcYogi ping` | szybki `pong` (adresowane — mały/zerowy jitter) |
| `mcYogi#7 call button.pressed count=4` | `#7 ok` |
| `mcYogi call button_pressed` | `err invalid_argument reason=proc` |
| `ha ping` | cisza (tag ≠ adres) |
| `mcYogi battery` | `err unsupported` |
| Stress 10× `all#N ping` @ ≥2 s | 10/10 `#N pong`, 0 send errors |

Public (ch0): brak auto-answer / brak TX testów.

---

## E. Interpretacja FAIL

| Objaw | Prawdopodobna przyczyna |
|-------|-------------------------|
| Android OK, HA chat tylko HA | stary HA (&lt; 2.12.2) albo stary firmware bez PublishEx delay; albo radio nadal w kolizji |
| Brak `tx_jitter` w trace | bridge nie widzi `AddressKind.All` / starego vendor bez `reply_delay_seconds` |
| Discovery 1.1 w chacie | HACS nie na 2.12.2 / runtime mcrpc ≠ 1.2.2 |
| Brak button w ogóle | firmware nie na kanale / USB nie flasznięty |

---

## F. Sign-off

- [ ] HACS 2.12.2, runtime mcrpc 1.2.2  
- [ ] Android `all ping` → HA chat pokazuje **button + mcYogi**  
- [ ] Android `all discovery` → obie linie slim `v=1.2` w HA  
- [ ] HA Chat `all ping` → inbound `pong` od button  
- [ ] Adresowany `mcYogi ping` nadal szybki  
- [ ] Flat `call` / `@id` / `ha≠adres` OK  
- [ ] Heltec/LW010 flasznięte na mcrpc-1.2.2 (gdy USB)

**READY TO SHIP (HA multi-reply)** tylko gdy C1+C2 PASS.  
On-air Heltec bez USB = BLOCKED na flash, ale C1 z Androida nadal waliduje chat HA jeśli button już na 1.2.x air.
