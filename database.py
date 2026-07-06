"""
Modul pro správu Supabase Storage - ukládání a načítání dat jako Parquet.
Optimalizováno pro rychlost, stabilitu a minimální memory footprint.

Defensive programování:
- Všechny výjimky jsou logovány s traceback (logger.exception)
- Funkce vracejí None / False / fallback, aby UI nepadalo
- User-friendly chybové zprávy (CZ, s emoji a vysvětlením)
"""
import io
import logging
import os
import time
from typing import Optional

import pandas as pd
import streamlit as st
from supabase import Client, create_client

# Konfigurace loggeru
logger = logging.getLogger("warehouse.database")

# Název bucketu v Supabase Storage
BUCKET_NAME = "warehouse_data"

# Verze schématu parquet - inkrementujte při zásadní změně struktury sloupců
SCHEMA_VERSION = 2

# Timeout a retry konfigurace
MAX_RETRIES = 3
RETRY_DELAY_S = 1.0
UPLOAD_TIMEOUT_S = 120
DOWNLOAD_TIMEOUT_S = 60


def _get_secret(key: str) -> Optional[str]:
    """Získá secret ze st.secrets nebo z os.environ (pro Railway/headless deploy)."""
    # 1. Priorita: Streamlit secrets (lokální vývoj a Streamlit Cloud)
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception as e:
        # Logujeme, ale pokračujeme na env vars fallback
        logger.debug(f"Čtení st.secrets['{key}'] selhalo: {e}")
    # 2. Fallback: environment variable (Railway, Docker, CI/CD)
    return os.environ.get(key)


def _user_friendly_error(prefix: str, exc: Exception) -> str:
    """
    Sestaví user-friendly chybovou zprávu s krátkým popisem
    (technický traceback se loguje samostatně do loggeru).
    """
    exc_type = type(exc).__name__
    detail = str(exc).strip()[:200] or "bez detailu"
    return f"{prefix}\n\n**Typ:** `{exc_type}`\n\n**Detail:** {detail}"


def _safe_st_error(message: str) -> None:
    """Zobrazí chybovou zprávu ve Streamlit, ale nikdy nevyhodí výjimku."""
    try:
        st.error(message)
    except Exception as e:
        # mimo Streamlit kontext (background worker, test) - pouze log
        logger.debug(f"st.error() selhal: {e}")


def _safe_st_warning(message: str) -> None:
    """Zobrazí warning ve Streamlit, ale nikdy nevyhodí výjimku."""
    try:
        st.warning(message)
    except Exception as e:
        logger.debug(f"st.warning() selhal: {e}")


def _init_supabase() -> Optional[Client]:
    """Bezpečná inicializace Supabase klienta s detailním error loggingem."""
    try:
        url = _get_secret("SUPABASE_URL")
        key = _get_secret("SUPABASE_KEY")
        if not url or not key:
            logger.error(
                "Supabase credentials nejsou k dispozici "
                "(ani v st.secrets, ani v env vars)"
            )
            _safe_st_error(
                "🔐 **Chyba konfigurace**: Chybí `SUPABASE_URL` nebo `SUPABASE_KEY`.\n\n"
                "Nastavte je prosím v `.streamlit/secrets.toml` (lokální vývoj) "
                "nebo v Railway env vars (produkce)."
            )
            return None
        client = create_client(url, key)
        logger.info("Supabase client inicializován úspěšně")
        return client
    except Exception as e:
        # Kompletní traceback do logu (logger.exception = traceback level)
        logger.exception(f"Nepodařilo se inicializovat Supabase klienta: {type(e).__name__}: {e}")
        _safe_st_error(_user_friendly_error(
            "🔐 **Chyba připojení k databázi Supabase**.",
            e,
        ))
        return None


# Lazy inicializace - vytvoří se klient až při prvním použití
@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Optional[Client]:
    """Cacheovaný Supabase klient (vytvoří se jen jednou za session)."""
    return _init_supabase()


def _is_not_found_error(exc: Exception) -> bool:
    """Detekuje 404 / not_found chyby ze Supabase (soubor neexistuje)."""
    exc_str = str(exc).lower()
    # Hledáme typické markery pro "soubor neexistuje"
    # - case-insensitive (exc_str je již .lower())
    # - pokrývá různé formáty (s/bez mezer, camelCase/snake_case)
    return any(marker in exc_str for marker in [
        'statuscode": 404',      # camelCase JSON: "statusCode": 404
        'status_code": 404',     # snake_case JSON: "status_code": 404
        'statuscode: 404',       # bez uvozovek
        'httpstatuscode": 404',  # HttpStatusCode formát
        'not_found',             # Python dict nebo API: not_found
        'not found',             # text
        'object not found',      # Supabase storage spec.
        '404 not found',         # HTTP reason phrase
        # 4xx obecně: klient nemá právo / špatný požadavek — nikdy se neopraví retry,
        # a opakované requesty zdržují pipeline při startu (~3 s na každou tabulku).
        'statuscode": 400', 'status_code": 400', 'statuscode: 400',
        'statuscode": 401', 'status_code": 401', 'statuscode: 401',
        'statuscode": 403', 'status_code": 403', 'statuscode: 403',
        # 429 rate-limit: retry situaci jen zhorší (prodlužuje cooldown Supabase)
        'statuscode": 429', 'status_code": 429', 'statuscode: 429',
        '429 too many requests', 'rate limit', 'too many requests',
        '400 bad request', '401 unauthorized', '403 forbidden',
    ])


def _retry_operation(operation, *args, max_retries: int = MAX_RETRIES, **kwargs):
    """
    Společná retry logika pro síťové operace s exponenciálním backoff.

    DŮLEŽITÉ: Pro 404 Not Found chyby se NERETRYUJE - okamžitý fail.
    Tím ušetříme ~24s při startu aplikace, když chybí vedlejší tabulky (aus_likp atd.).
    """
    last_exc = None
    op_name = getattr(operation, "__name__", str(operation))
    for attempt in range(max_retries):
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            # Rychlý fail pro 404 - neexistující soubory nebudou existovat ani za 3 pokusy
            if _is_not_found_error(e):
                logger.debug(f"Soubor neexistuje (404) při '{op_name}': {e}")
                raise
            last_exc = e
            if attempt < max_retries - 1:
                wait = RETRY_DELAY_S * (2 ** attempt)
                logger.warning(
                    f"Operace '{op_name}' selhala "
                    f"(pokus {attempt + 1}/{max_retries}): "
                    f"{type(e).__name__}: {e}. Čekám {wait:.1f}s"
                )
                time.sleep(wait)
            else:
                logger.exception(
                    f"Operace '{op_name}' selhala po {max_retries} pokusech: "
                    f"{type(e).__name__}: {e}"
                )
    # Místo původního `raise last_exc` zabalíme do runtime chyby s traceback
    assert last_exc is not None
    raise last_exc


def _safe_remove(supabase: Client, path: str) -> bool:
    """Bezpečné smazání souboru (nevyhazuje výjimku, pokud soubor neexistuje)."""
    try:
        supabase.storage.from_(BUCKET_NAME).remove([path])
        return True
    except Exception as e:
        # Tiché ignorování - soubor typicky neexistuje, což je OK
        if _is_not_found_error(e):
            logger.debug(f"Smazání {path} přeskočeno (soubor neexistuje).")
        else:
            logger.warning(f"Smazání {path} selhalo: {type(e).__name__}: {e}")
        return False


def _df_to_optimized_parquet(df: pd.DataFrame) -> bytes:
    """
    Převede DataFrame na optimalizovaný Parquet.
    - Komprese zstd pro minimální velikost
    - Implicitní kategorie pro object sloupce s nízkou kardinalitou

    Při fatální chybě (ani fallback) vrátí prázdné bytes a zaloguje traceback.
    """
    if df is None or df.empty:
        logger.warning("_df_to_optimized_parquet: prázdný DataFrame")
        return b""

    buffer = io.BytesIO()
    try:
        df.to_parquet(
            buffer,
            engine='pyarrow',
            index=False,
            compression='zstd',
            compression_level=3,
            use_dictionary=True,
            write_statistics=False,
        )
        return buffer.getvalue()
    except Exception as primary_err:
        # Fallback na rychlejší kompresi při chybě
        logger.warning(
            f"Parquet (zstd) selhal: {type(primary_err).__name__}: {primary_err}. "
            f"Fallback na snappy."
        )
        try:
            buffer = io.BytesIO()
            df.to_parquet(buffer, engine='pyarrow', index=False, compression='snappy')
            return buffer.getvalue()
        except Exception as fallback_err:
            logger.exception(
                f"Parquet (snappy fallback) také selhal: "
                f"{type(fallback_err).__name__}: {fallback_err}"
            )
            return b""


def _df_from_parquet(file_bytes: bytes) -> pd.DataFrame:
    """Načte Parquet z binárních dat - bezpečně s fallbackem."""
    if not file_bytes:
        logger.warning("_df_from_parquet: prázdné vstupní bytes")
        return pd.DataFrame()
    buffer = io.BytesIO(file_bytes)
    try:
        df = pd.read_parquet(buffer, engine='pyarrow')
        return df
    except Exception as e:
        logger.warning(
            f"Čtení parquet selhalo: {type(e).__name__}: {e}"
        )
        raise


def save_to_db(df: pd.DataFrame, name: str, append: bool = False) -> bool:
    """
    Uloží DataFrame jako optimalizovaný Parquet do Supabase Storage.
    Při append=True stáhne existující data, sloučí a odfiltruje duplicity.

    Při jakékoliv chybě vrátí False, zaloguje traceback a zobrazí user-friendly
    zprávu ve Streamlit (nevyhazuje výjimku - UI nikdy nepadá).
    """
    supabase = get_supabase_client()
    if supabase is None:
        logger.error(f"save_to_db('{name}'): Supabase klient není dostupný")
        _safe_st_error(
            "☁️ **Nelze uložit data**: připojení k Supabase není aktivní.\n\n"
            "Zkuste obnovit stránku (F5) nebo kontaktujte správce."
        )
        return False
    if df is None:
        logger.warning(f"save_to_db('{name}'): df je None")
        return False
    if df.empty:
        logger.warning(f"save_to_db('{name}'): pokus o uložení prázdného DataFrame")
        _safe_st_warning(f"⚠️ Tabulka **{name}** je prázdná - nic nebylo uloženo.")
        return False

    file_path = f"{name}.parquet"
    start_time = time.time()

    try:
        # 1. Pokud append, stáhneme stará data a sloučíme
        if append:
            old_df = load_from_db(name)
            if old_df is not None and not old_df.empty:
                try:
                    # load_from_db je @st.cache_data → vrací SDÍLENÝ objekt.
                    # Musíme kopírovat, jinak mutace níže poškodí cache pro ostatní taby.
                    old_df = old_df.copy()
                    # Zarovnání sloupců - přidáme chybějící sloupce z nového DF
                    for col in df.columns:
                        if col not in old_df.columns:
                            old_df[col] = pd.NA
                    for col in old_df.columns:
                        if col not in df.columns:
                            df[col] = pd.NA
                    df = pd.concat([old_df, df], ignore_index=True, sort=False)

                    # Dedupikace podle specifických klíčů pro danou tabulku
                    df = _dedupe_by_table(df, name)
                except Exception as merge_err:
                    logger.exception(
                        f"Chyba při merge/dedup pro '{name}' (append): "
                        f"{type(merge_err).__name__}: {merge_err}. "
                        f"Pokračuji bez append (uložím pouze nová data)."
                    )
                    # Pokračujeme bez append - uložíme jen nová data

        # 2. Převedeme na optimalizovaný Parquet
        file_bytes = _df_to_optimized_parquet(df)
        if not file_bytes:
            logger.error(f"Parquet serializace vrátila prázdná bytes pro '{name}'")
            _safe_st_error(
                f"❌ **Chyba serializace** dat pro **{name}**: "
                f"nepodařilo se převést DataFrame na Parquet."
            )
            return False
        compressed_size_mb = len(file_bytes) / (1024 * 1024)

        # 3. Smažeme starý soubor (best-effort)
        _safe_remove(supabase, file_path)

        # 4. Nahrajeme nový soubor (s retry)
        def _upload():
            return supabase.storage.from_(BUCKET_NAME).upload(
                file_path,
                file_bytes,
                file_options={"content-type": "application/octet-stream", "upsert": "false"}
            )

        try:
            _retry_operation(_upload)
        except Exception as upload_err:
            # 404 zde znamená, že bucket/storage je v pořádku - spíše síť/proto.
            # Pokud je to 4xx, neopakujeme (retry už má fast-fail).
            logger.exception(
                f"Upload '{name}' do Supabase selhal: "
                f"{type(upload_err).__name__}: {upload_err}"
            )
            _safe_st_error(_user_friendly_error(
                f"❌ **Chyba při uploadu** tabulky **{name}** do Supabase Storage.",
                upload_err,
            ))
            return False

        # Po append uploadu invalidujeme cache load_from_db, aby další čtení
        # (i další iterace dávkového uploadu téže tabulky) vidělo čerstvá data
        # místo stale cache → jinak by se append prováděl proti zastaralému stavu.
        if append:
            try:
                load_from_db.clear()
            except Exception as clear_err:
                logger.debug(f"Invalidace cache po uložení selhala (nefatální): {clear_err}")

        elapsed = time.time() - start_time
        rows = len(df)
        logger.info(
            f"✅ Uloženo {name}: {rows:,} řádků, {compressed_size_mb:.2f} MB, {elapsed:.2f}s"
        )
        return True

    except Exception as e:
        # Jakákoliv neočekávaná chyba - kompletní traceback do logu.
        logger.exception(
            f"Neočekávaná chyba při ukládání '{name}': {type(e).__name__}: {e}"
        )
        _safe_st_error(_user_friendly_error(
            f"❌ **Neočekávaná chyba** při ukládání **{name}**.",
            e,
        ))
        return False


def _dedupe_by_table(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Inteligentní dedupikace podle specifických klíčů pro každou tabulku.
    Bezpečná - nikdy nevyhodí výjimku; při fatální chybě vrátí DF jak je.
    """
    if df is None or df.empty:
        return df
    try:
        if name == 'raw_pick' and 'Transfer Order Number' in df.columns and 'Material' in df.columns:
            subset = [c for c in ['Transfer Order Number', 'Material', 'Confirmation date', 'Confirmation time'] if c in df.columns]
            df = df.drop_duplicates(subset=subset, keep='last')
        elif name == 'raw_vekp' and 'Handling Unit' in df.columns:
            df = df.drop_duplicates(subset=['Handling Unit'], keep='last')
        elif name == 'raw_cats':
            del_col = next((c for c in df.columns if str(c).strip().lower() in ['lieferung', 'delivery', 'zakázka', 'dodávka']), None)
            if del_col:
                df = df.drop_duplicates(subset=[del_col], keep='last')
            else:
                df = df.drop_duplicates(keep='last')
        elif name == 'raw_queue' and 'Transfer Order Number' in df.columns:
            df = df.drop_duplicates(subset=['Transfer Order Number'], keep='last')
        elif name in ['raw_marm', 'raw_manual'] and 'Material' in df.columns:
            df = df.drop_duplicates(subset=['Material'], keep='last')
        elif name == 'raw_oe' and 'DN NUMBER (SAP)' in df.columns:
            df = df.drop_duplicates(keep='last')
        elif name == 'raw_lx03':
            # LX03 - unikátní podle storage bin
            bin_col = next((c for c in df.columns if 'storage bin' in str(c).lower() or 'skladové místo' in str(c).lower() or 'lagerplatz' in str(c).lower()), None)
            if bin_col:
                df = df.drop_duplicates(subset=[bin_col], keep='last')
            else:
                df = df.drop_duplicates(keep='last')
        elif name == 'raw_lt10':
            bin_col = next((c for c in df.columns if 'storage bin' in str(c).lower() or 'skladové místo' in str(c).lower() or 'lagerplatz' in str(c).lower()), None)
            mat_col = next((c for c in df.columns if 'material' in str(c).lower() or 'materiál' in str(c).lower()), None)
            if bin_col and mat_col:
                df = df.drop_duplicates(subset=[bin_col, mat_col], keep='last')
            else:
                df = df.drop_duplicates(keep='last')
        else:
            df = df.drop_duplicates(keep='last')
    except Exception as e:
        logger.warning(
            f"Dedupikace selhala pro {name}, používám obecnou: "
            f"{type(e).__name__}: {e}"
        )
        try:
            df = df.drop_duplicates(keep='last')
        except Exception as fallback_err:
            logger.exception(
                f"Ani obecná dedupikace pro {name} neselhala: "
                f"{type(fallback_err).__name__}: {fallback_err}"
            )
            # Vrátíme DF jak je - lepší než spadnout
    return df


@st.cache_data(show_spinner=False, ttl=300)
def load_from_db(name: str) -> Optional[pd.DataFrame]:
    """
    Načte optimalizovaný Parquet ze Supabase Storage a vrátí DataFrame.
    Cachováno na 5 minut (TTL).

    Optimalizace: Pro 404 (neexistující soubor) okamžitě vrací None.
    Ušetří ~24s při startu, když chybí vedlejší tabulky (aus_likp atd.).

    Při jakékoliv jiné chybě vrátí None a zaloguje traceback (logger.exception).
    """
    supabase = get_supabase_client()
    if supabase is None:
        logger.debug(f"load_from_db('{name}'): Supabase není dostupný")
        return None

    file_path = f"{name}.parquet"
    start_time = time.time()

    try:
        def _download():
            return supabase.storage.from_(BUCKET_NAME).download(file_path)

        # Přímý download bez retry pro 404 - _retry_operation už má 404 fast-fail
        try:
            response = _retry_operation(_download)
        except Exception as dl_err:
            if _is_not_found_error(dl_err):
                # Rychlý debug log, žádné varování - soubor prostě neexistuje
                logger.debug(f"Soubor {file_path} neexistuje v Supabase (404)")
                return None
            # Jinak zalogujeme kompletní traceback (varování stačí, ne error)
            logger.warning(
                f"Chyba při stahování {file_path}: "
                f"{type(dl_err).__name__}: {dl_err}"
            )
            return None

        df = _df_from_parquet(response)

        if df is None:
            logger.warning(f"load_from_db('{name}'): _df_from_parquet vrátil None")
            return None

        elapsed = time.time() - start_time
        logger.info(f"📥 Načteno {name}: {len(df):,} řádků za {elapsed:.2f}s")
        return df

    except Exception as e:
        # Jakákoliv jiná chyba - traceback do logu, vrátíme None
        logger.exception(
            f"Neočekávaná chyba při načítání '{name}': "
            f"{type(e).__name__}: {e}"
        )
        return None


def is_connected() -> bool:
    """Rychlý health check připojení k Supabase.
    Bezpečný - nikdy nevyhodí výjimku (všechny chyby jsou polknuty a logovány).
    """
    try:
        return get_supabase_client() is not None
    except Exception as e:
        logger.debug(f"is_connected(): kontrola selhala: {type(e).__name__}: {e}")
        return False


def clear_cache():
    """Smaže cache funkcí načítajících data (využijte po uploadu nových dat).
    Bezpečný - nikdy nevyhodí výjimku."""
    try:
        load_from_db.clear()
        get_supabase_client.clear()
        logger.info("Cache vymazána")
    except Exception as e:
        logger.warning(
            f"Smazání cache selhalo: {type(e).__name__}: {e}"
        )