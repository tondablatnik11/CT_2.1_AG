# Full-history stabilizace Warehouse Control Tower

Datum: 2026-07-07  
Stav: návrh schválený uživatelem k sepsání specu  
Projekt: `C:\AI\Hellmann\CT_2.1_AG`  
Primární cíl: stabilita aplikace při načítání celé historie dat ze Supabase Storage bucketu `warehouse_data`

## Kontext

Aplikace je Python/Streamlit analytický nástroj pro logistická a skladová data Hellmann. Data se ukládají do Supabase Storage jako Parquet soubory a aplikace je načítá do pandas DataFrame objektů, nad kterými počítá KPI, billing, pohyby, Vollpalette detekci a další provozní přehledy.

Uživatel doplnil data za další měsíce. Aplikace nyní častěji padá nebo je obtížně použitelná. Uživatel zároveň potvrdil, že po otevření má aplikace standardně pracovat s **celou historií**, ne pouze s aktuálním nebo posledním obdobím.

Z toho plyne hlavní technický požadavek: výkon a stabilitu nelze řešit omezením výchozího rozsahu dat. Musíme zachovat full-history default a snížit paměťové špičky, zbytečné kopie, opakované výpočty a rizikové cache/mutation vzory.

## Cíle

1. Zachovat přesnost současných business výpočtů a vzorců.
2. Stabilizovat aplikaci při rostoucím počtu měsíců dat.
3. Zrychlit start, přepínání tabů, Billing, Packing, Daily/Monthly KPI a exporty bez změny výstupní logiky.
4. Zlepšit chování při chybách Supabase, chybějících secrets, refreshi a uploadu.
5. Připravit bezpečný storage redesign pro další růst dat.
6. Zlepšit profesionální dojem aplikace až po odstranění P0 stabilitních rizik.
7. Před pushem na GitHub opakovaně ověřit testy, build/importy a runtime smoke.

## Necíle

- Neměnit business pravidla jen kvůli rychlosti.
- Neměnit default z celé historie na kratší období.
- Nedělat destruktivní migraci Supabase Storage bez parity testu a rollback plánu.
- Nedělat kosmetický redesign, který maskuje stabilitní problémy.
- Nerozbíjet současné názvy výstupních sloupců, kategorií, KPI nebo sign conventions bez explicitního schválení.

## Hlavní zjištění z auditu

### 1. Full-history načítání roste lineárně

Současný model načítá celé logické tabulky do pandas před tím, než se řeší období nebo konkrétní tab. To je akceptovatelné pro menší historii, ale s dalšími měsíci roste čas i RAM.

### 2. Append upload má vysokou paměťovou špičku

Při append scénáři datová vrstva stahuje existující Parquet, spojí jej s novým DataFrame, deduplikuje a znovu serializuje celý výsledek. Peak RAM tak typicky obsahuje:

- původní historická data,
- nově nahraná data,
- concatenated výsledek,
- Parquet buffer před uploadem.

Tento vzor je dlouhodobě rizikový pro `raw_pick` a další rostoucí tabulky.

### 3. Některé výpočty jsou opakované nebo příliš eager

Audit označil jako rizikové zejména:

- opakovanou Vollpalette detekci,
- řádkové Python smyčky ve výpočtech pohybů a Vollpalette,
- Billing full-history výpočet a mezikopie,
- eager Excel export po renderu místo až po explicitním kliknutí,
- opakované kopie DataFrame objektů mezi cache, session state a taby.

### 4. Cache a mutace DataFrame objektů jsou křehké

Streamlit cache a `st.session_state` mohou držet více velkých verzí stejných dat. In-place přidávání helper sloupců do DataFrame objektů je nebezpečné, pokud objekt pochází z cache nebo je sdílen mezi taby.

### 5. Některé provozní chyby mohou působit jako prázdná data

Supabase auth/rate-limit/config chyby nesmí být zaměněny za „soubor neexistuje“. Chybějící nebo slabé admin heslo nesmí otevřít Admin zónu fail-open chováním.

## Doporučený přístup

Zvolený směr je **formula-safe stabilizace pro celou historii**.

Nejdřív chránit výpočty golden/regresními testy, potom provést P0 stabilizační změny bez změny business logiky, následně optimalizovat výkonnost a až poté zavést storage redesign.

Tento postup minimalizuje riziko, že zrychlení nebo refaktor změní billing, pohyby, Vollpalette detekci nebo KPI hodnoty.

## Architektura změn

### Vrstva 1: Formula baseline

Před optimalizacemi se doplní testy pro nejcitlivější výpočty:

- `fast_compute_moves()`:
  - full pallet vs non-full pallet,
  - box tuple pořadí,
  - missing box data,
  - decimal/NaN/edge množství,
  - očekávané hodnoty pohybů, exact a loose/miss.
- `detect_vollpalettes()`:
  - přesný set `(delivery, HU)` před a po refaktoru,
  - nested HU a VEPO/VEKP vztahy,
  - interní/externí HU,
  - výjimky typu KLT/PI_PA.
- Billing:
  - kategorie,
  - počet HU,
  - počet TO,
  - bilance,
  - sign conventions,
  - Vollpalette remap.
- MARM/master data:
  - jeden materiál může mít více alternative unit řádků,
  - dedupe nesmí zahodit business-relevantní varianty.
- Datumy a KPI:
  - day-first/ISO formáty,
  - invalid hodnoty,
  - month boundary,
  - denní a měsíční agregace.

### Vrstva 2: P0 stabilita bez změny vzorců

Tato fáze smí měnit orchestrace, cache, refresh a error handling, ale nesmí měnit obchodní výsledky.

Plánované zásahy:

1. Zavést centrální `clear_all_caches()` pro:
   - databázový loader,
   - app-level cached loadery,
   - module-level Billing/Packing cache,
   - relevantní `st.session_state` klíče.
2. Odstranit závislost Packing, FU Compare a Board tabů na předchozí návštěvě Billing tabu.
3. Přesunout Excel export do explicitního flow:
   - render tabu export negeneruje,
   - export se připraví až po kliknutí,
   - velké full-history exporty dostanou jasnou informaci o náročnosti.
4. Odstranit duplicitní Vollpalette výpočet a předávat jeden ověřený výsledek dál.
5. Zastavit in-place mutace sdílených/cached DataFrame objektů:
   - taby pracují s lokální kopií nebo view,
   - helper sloupce se přidávají jen do lokálního objektu,
   - cached loader vrací immutable-like boundary.
6. Zpřesnit Supabase error handling:
   - 401/403/429/config chyby jsou explicitní chyby,
   - not-found zůstane not-found,
   - tokeny a secrets se nerednerují do UI/logů.
7. Admin zóna fail-closed:
   - žádný fallback `admin123`,
   - chybějící admin heslo znamená vypnutou Admin zónu s jasným vysvětlením.

### Vrstva 3: Performance refaktor s paritou výstupů

Po úspěšné formula baseline lze optimalizovat:

1. `fast_compute_moves()`:
   - snížit Python objektové alokace,
   - vracet NumPy/pandas-friendly struktury,
   - seskupovat podle stejných box konfigurací,
   - zachovat stejný výstup pro všechny golden případy.
2. `detect_vollpalettes()`:
   - pracovat nad unikátními `(delivery, HU)` páry,
   - využít index/merge strategii,
   - zachovat stejný `voll_set`.
3. Billing:
   - centralizovat výpočet přes stabilní `data_version`/signature,
   - odstranit zbytečné mezikopie a merge, pokud neovlivňují výstup,
   - zpřístupnit výsledek všem tabům bez závislosti na pořadí kliknutí.
4. Daily/Monthly KPI a Packing:
   - sdílet již připravené deriváty,
   - neprovádět stejné full-history výpočty vícekrát,
   - omezit zobrazování obřích tabulek bez nutnosti.

### Vrstva 4: Storage redesign pro dlouhodobý růst

Protože default zůstává celá historie, finální řešení má směřovat k append-only storage modelu.

Cílový koncept:

- každý upload uloží nový immutable chunk,
- manifest popisuje dostupné chunky,
- manifest obsahuje minimálně:
  - logical table,
  - path,
  - schema version,
  - row count,
  - date range,
  - columns/schema fingerprint,
  - created timestamp,
  - source/upload id.
- loader umí:
  - načíst celou historii,
  - načíst jen vybrané sloupce,
  - v budoucnu filtrovat podle období,
  - číst starý monolitický formát i nový chunk formát.
- upload je recoverable:
  - nejdřív staging/temp objekt,
  - validace velikosti/schématu,
  - update manifestu,
  - staré objekty se nemažou bez rollback možnosti.

První implementace storage redesignu musí být kompatibilní se současnými `raw_*.parquet` soubory. Migrace nesmí být destruktivní.

### Vrstva 5: UI a observability polish

Po P0 stabilitě:

- sjednotit loading/progress texty,
- zobrazovat přátelské chybové stavy místo tracebacks,
- přidat diagnostiku datové verze, počtu řádků, cache refresh a memory status,
- sjednotit chart/table rendering helpery,
- zlepšit export UX,
- doplnit dokumentaci pro secrets, upload, refresh, rollback a recovery.

## Data flow po stabilizaci

1. Aplikace při startu načte full-history default přes bezpečnější loader.
2. Loader vrací surové/canonical DataFrame objekty bez tab-specific helper mutací.
3. Pipeline vytvoří stabilní `data_version`/signature.
4. Sdílené výpočty se provedou jednou a předávají se tabům.
5. Taby renderují z připravených dat nebo lazy dopočítají vlastní výsledek přes centrální cache.
6. Export se generuje pouze po explicitním uživatelském požadavku.
7. Quick Refresh/Admin upload zavolá jednotnou cache invalidaci a odstraní stale session state.

## Error handling

- Supabase not-found je jiný stav než auth/config/rate-limit chyba.
- Chybějící secrets mají vlastní přátelskou obrazovku.
- Admin zóna je při chybějící konfiguraci uzamčená.
- Upload chyby nesmí zanechat storage ve stavu, kde aplikace čte poloviční data.
- Uživatelská chyba musí říkat, co má uživatel opravit; technický detail může zůstat v logu/diagnostice bez secrets.

## Testovací a build brány

Před implementací změn:

```bash
python -m pytest tests -v --tb=short
python -m compileall -q app.py database.py modules tests
```

Po P0 stabilizaci:

```bash
python -m pytest tests -v --tb=short
python -m pytest tests --cov=modules --cov=database --cov-report=term --cov-report=xml -v
python -m compileall -q app.py database.py modules tests
```

Runtime smoke:

```bash
streamlit run app.py --server.headless true --server.port 8501
```

Specifické gate scénáře:

- aplikace bez secrets ukáže kontrolovanou chybu,
- aplikace se secrets odpoví přes Streamlit health endpoint,
- Packing/FU Compare/Board fungují bez předchozí návštěvy Billing,
- Quick Refresh vyčistí všechny známé cache a session derived hodnoty,
- Excel export se negeneruje před kliknutím,
- tab/helper funkce nemutují caller-owned DataFrame,
- Supabase 401/403/429 nejsou interpretovány jako prázdná data,
- golden testy potvrzují stejné formule před a po performance změnách.

## Rizika a mitigace

| Riziko | Mitigace |
| --- | --- |
| Výkonový refaktor změní výpočet | Nejdřív golden testy, potom parity gate. |
| Storage redesign poškodí data | Append-only chunk model, manifest, staging, rollback, kompatibilní read path. |
| Full-history default zůstane náročný | Lazy export, méně kopií, sdílené výpočty, postupný chunk loader. |
| Cache invalidace bude neúplná | Jeden centrální `clear_all_caches()` testovaný monkeypatch testem. |
| UI polish odvede pozornost od stability | UI polish až po P0 stabilitě. |
| Secrets/auth chyba se zamění za prázdná data | Explicitní error classification a testy pro Supabase chyby. |

## Implementační pořadí

1. Přidat formula/golden testy a baseline performance testy.
2. Implementovat P0 stabilitu bez změny vzorců.
3. Spustit testy, compileall a runtime smoke.
4. Optimalizovat performance kritické cesty pod ochranou golden testů.
5. Spustit rozšířené testy a parity kontroly.
6. Navrhnout a implementovat storage chunk/manifest kompatibilní vrstvu.
7. Doplnit UI/observability polish.
8. Znovu projet testy, build, runtime smoke a případně code review agenty.
9. Commitnout implementaci a pushnout branch na GitHub.

## Kritéria dokončení

- Full-history default zůstává zachovaný.
- Všechny existující i nové formula testy procházejí.
- Aplikace neprovádí eager Excel export při běžném renderu.
- Cache refresh čistí všechny známé odvozené hodnoty.
- Billing-dependent taby nejsou závislé na pořadí návštěvy tabů.
- Supabase auth/config/rate-limit chyby jsou explicitní a bezpečné.
- Runtime smoke potvrdí, že Streamlit aplikace nastartuje.
- GitHub CI/build má projít na první pokus podle lokálních gate výsledků.
