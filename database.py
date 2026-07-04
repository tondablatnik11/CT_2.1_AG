"""
Modul pro správu Supabase Storage - ukládání a načítání dat jako Parquet.
Optimalizováno pro rychlost, stabilitu a minimální memory footprint.
"""
import os
import io
import time
import logging
import hashlib
import pandas as pd
import streamlit as st
from supabase import create_client, Client
from typing import Optional

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
    except Exception:
        pass  # mimo Streamlit kontext (např. background workers)
    # 2. Fallback: environment variable (Railway, Docker, CI/CD)
    return os.environ.get(key)


def _init_supabase() -> Optional[Client]:
    """Bezpečná inicializace Supabase klienta s detailním error loggingem."""
    try:
        url = _get_secret("SUPABASE_URL")
        key = _get_secret("SUPABASE_KEY")
        if not url or not key:
            logger.error("Supabase credentials nejsou k dispozici (ani v st.secrets, ani v env vars)")
            try:
                st.error("🔐 Chyba: Chybí SUPABASE_URL nebo SUPABASE_KEY (nastavte v Secrets nebo v Railway env vars).")
            except Exception:
                pass
            return None
        client = create_client(url, key)
        logger.info("Supabase client inicializován úspěšně")
        return client
    except Exception as e:
        logger.exception("Nepodařilo se inicializovat Supabase klienta")
        try:
            st.error(f"🔐 Chyba připojení k databázi: {e}")
        except Exception:
            pass
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
        '404',                   # samotné číslo (méně specifické, ale jako fallback)
    ])


def _retry_operation(operation, *args, max_retries: int = MAX_RETRIES, **kwargs):
    """
    Společná retry logika pro síťové operace s exponenciálním backoff.

    DŮLEŽITÉ: Pro 404 Not Found chyby se NERETRYUJE - okamžitý fail.
    Tím ušetříme ~24s při startu aplikace, když chybí vedlejší tabulky (aus_likp atd.).
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            # Rychlý fail pro 404 - neexistující soubory nebudou existovat ani za 3 pokusy
            if _is_not_found_error(e):
                logger.debug(f"Soubor neexistuje (404): {e}")
                raise
            last_exc = e
            if attempt < max_retries - 1:
                wait = RETRY_DELAY_S * (2 ** attempt)
                logger.warning(f"Operace selhala (pokus {attempt + 1}/{max_retries}): {e}. Čekám {wait:.1f}s")
                time.sleep(wait)
            else:
                logger.error(f"Operace selhala po {max_retries} pokusech: {e}")
    raise last_exc


def _safe_remove(supabase: Client, path: str) -> bool:
    """Bezpečné smazání souboru (nevyhazuje výjimku, pokud soubor neexistuje)."""
    try:
        supabase.storage.from_(BUCKET_NAME).remove([path])
        return True
    except Exception as e:
        # Tiché ignorování - soubor typicky neexistuje, což je OK
        logger.debug(f"Smazání {path} selhalo (pravděpodobně neexistuje): {e}")
        return False


def _df_to_optimized_parquet(df: pd.DataFrame) -> bytes:
    """
    Převede DataFrame na optimalizovaný Parquet.
    - Komprese zstd pro minimální velikost
    - Implicitní kategorie pro object sloupce s nízkou kardinalitou
    """
    buffer = io.BytesIO()
    try:
        df.to_parquet(
            buffer,
            engine='pyarrow',
            index=False,
            compression='zstd',
            compression_level=3,
            use_dictionary=True,
            # pyarrow automatic page sizes for streaming
            write_statistics=False,
        )
    except Exception:
        # Fallback na rychlejší kompresi při chybě
        logger.warning("zstd selhal, fallback na snappy")
        buffer = io.BytesIO()
        df.to_parquet(buffer, engine='pyarrow', index=False, compression='snappy')
    return buffer.getvalue()


def _df_from_parquet(file_bytes: bytes) -> pd.DataFrame:
    """Načte Parquet z binárních dat - bezpečně s fallbackem."""
    buffer = io.BytesIO(file_bytes)
    try:
        df = pd.read_parquet(buffer, engine='pyarrow')
        return df
    except Exception as e:
        logger.warning(f"Čtení parquet selhalo: {e}")
        raise


def save_to_db(df: pd.DataFrame, name: str, append: bool = False) -> bool:
    """
    Uloží DataFrame jako optimalizovaný Parquet do Supabase Storage.
    Při append=True stáhne existující data, sloučí a odfiltruje duplicity.
    """
    supabase = get_supabase_client()
    if supabase is None or df is None or df.empty:
        if df is not None and df.empty:
            logger.warning(f"Pokus o uložení prázdného DF do {name}")
        return False

    file_path = f"{name}.parquet"
    start_time = time.time()

    try:
        # 1. Pokud append, stáhneme stará data a sloučíme
        if append:
            old_df = load_from_db(name)
            if old_df is not None and not old_df.empty:
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

        # 2. Převedeme na optimalizovaný Parquet
        file_bytes = _df_to_optimized_parquet(df)
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

        _retry_operation(_upload)

        elapsed = time.time() - start_time
        rows = len(df)
        logger.info(
            f"✅ Uloženo {name}: {rows:,} řádků, {compressed_size_mb:.2f} MB, {elapsed:.2f}s"
        )
        return True

    except Exception as e:
        logger.exception(f"Chyba při ukládání {name}")
        try:
            st.error(f"❌ Chyba při ukládání '{name}': {type(e).__name__}: {e}")
        except Exception:
            pass  # mimo Streamlit kontext
        return False


def _dedupe_by_table(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Inteligentní dedupikace podle specifických klíčů pro každou tabulku."""
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
        logger.warning(f"Dedupikace selhala pro {name}, používám obecnou: {e}")
        df = df.drop_duplicates(keep='last')
    return df


@st.cache_data(show_spinner=False, ttl=300)
def load_from_db(name: str) -> Optional[pd.DataFrame]:
    """
    Načte optimalizovaný Parquet ze Supabase Storage a vrátí DataFrame.
    Cachováno na 5 minut (TTL).

    Optimalizace: Pro 404 (neexistující soubor) okamžitě vrací None.
    Ušetří ~24s při startu, když chybí vedlejší tabulky (aus_likp atd.).
    """
    supabase = get_supabase_client()
    if supabase is None:
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
                logger.debug(f"Soubor {name}.parquet neexistuje v Supabase (404)")
                return None
            raise

        df = _df_from_parquet(response)

        elapsed = time.time() - start_time
        logger.info(f"📥 Načteno {name}: {len(df):,} řádků za {elapsed:.2f}s")
        return df

    except Exception as e:
        # Jakákoliv jiná chyba
        logger.warning(f"Chyba při načítání {name}: {type(e).__name__}: {e}")
        return None


def is_connected() -> bool:
    """Rychlý health check připojení k Supabase."""
    return get_supabase_client() is not None


def clear_cache():
    """Smaže cache funkcí načítajících data (využijte po uploadu nových dat)."""
    try:
        load_from_db.clear()
        get_supabase_client.clear()
        logger.info("Cache vymazána")
    except Exception as e:
        logger.warning(f"Smazání cache selhalo: {e}")