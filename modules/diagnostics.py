"""
Diagnostické utility pro Warehouse Control Tower.

Poskytuje:
- Sledování zdraví aplikace (memory, cache, last refresh)
- Performance monitoring s automatickým logováním pomalých operací
- Bezpečné vykonávání funkcí s fallbackem

Použití v app.py:
    from modules.diagnostics import (
        get_system_health, log_performance, safe_execute,
        record_error, record_successful_load, should_warn_about_errors,
    )

    health = get_system_health()
    log_performance("load_pick", 3.42)
    result = safe_execute(risky_func, arg1, arg2, fallback=[])
"""
import functools
import gc
import logging
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("warehouse.diagnostics")

# Prahy pro varování (v sekundách)
SLOW_OPERATION_THRESHOLD_S = 5.0
VERY_SLOW_OPERATION_THRESHOLD_S = 15.0

# Klíče pro session_state
_LAST_SUCCESS_KEY = "last_successful_load"
_ERROR_COUNTER_KEY = "error_counter"

# Globální stav pro diagnostiku
_DIAGNOSTICS_STATE: Dict[str, Any] = {
    "operation_times": [],  # (timestamp, operation_name, duration_s)
    "error_count": 0,
    "error_window_start": None,
    "last_successful_load": None,
    "slow_operation_threshold_s": SLOW_OPERATION_THRESHOLD_S,
    "error_rate_threshold": 5,  # max 5 chyb za minutu
}


def record_operation(operation_name: str, duration_s: float) -> None:
    """
    Zaznamená dobu trvání operace (v sekundách).
    Pokud je > threshold, loguje warning; při > 15s loguje error.
    Interně ukládá všechny operace za poslední hodinu (pro health panel).
    """
    try:
        now = datetime.now()
        _DIAGNOSTICS_STATE["operation_times"].append((now, operation_name, float(duration_s)))

        # Vyčistit staré záznamy (starší než 1 hodina)
        cutoff = now - timedelta(hours=1)
        _DIAGNOSTICS_STATE["operation_times"] = [
            (ts, op, dur) for ts, op, dur in _DIAGNOSTICS_STATE["operation_times"]
            if ts > cutoff
        ]

        # Logování prahových hodnot
        if duration_s >= VERY_SLOW_OPERATION_THRESHOLD_S:
            logger.error(
                f"⏱️ Velmi pomalá operace: {operation_name} trvala {duration_s:.2f}s "
                f"(práh: {VERY_SLOW_OPERATION_THRESHOLD_S}s)"
            )
        elif duration_s >= _DIAGNOSTICS_STATE["slow_operation_threshold_s"]:
            logger.warning(
                f"⏱️ Pomalá operace: {operation_name} trvala {duration_s:.2f}s "
                f"(práh: {_DIAGNOSTICS_STATE['slow_operation_threshold_s']}s)"
            )
        else:
            logger.debug(f"⏱️ {operation_name}: {duration_s:.2f}s")
    except Exception as e:
        # Nikdy nevyhazovat z diagnostiky
        logger.debug(f"record_operation selhal: {type(e).__name__}: {e}")


def log_performance(operation: str, duration_s: float, threshold: float = SLOW_OPERATION_THRESHOLD_S) -> None:
    """
    Alias na record_operation - loguje výkon operace s prahovou hodnotou.
    Pokud duration_s >= threshold, zaloguje varování (nebo error při velmi pomalých).

    Args:
        operation: název operace (např. "load_pick", "compute_moves")
        duration_s: doba trvání v sekundách
        threshold: práh pro "pomalé" varování v sekundách (default 5s)
    """
    try:
        # Dočasně nastavíme threshold, zavoláme record_operation, vrátíme
        prev = _DIAGNOSTICS_STATE.get("slow_operation_threshold_s")
        _DIAGNOSTICS_STATE["slow_operation_threshold_s"] = threshold
        try:
            record_operation(operation, duration_s)
        finally:
            _DIAGNOSTICS_STATE["slow_operation_threshold_s"] = prev
    except Exception as e:
        logger.debug(f"log_performance selhal: {type(e).__name__}: {e}")


def record_error() -> None:
    """
    Zaznamená chybu. Pokud > threshold za minutu, zaloguje error.
    Bezpečná - nikdy nevyhodí výjimku.
    """
    try:
        now = datetime.now()
        _DIAGNOSTICS_STATE["error_count"] += 1

        if _DIAGNOSTICS_STATE["error_window_start"] is None:
            _DIAGNOSTICS_STATE["error_window_start"] = now
        elif (now - _DIAGNOSTICS_STATE["error_window_start"]).seconds > 60:
            # Reset okno po 1 minutě
            _DIAGNOSTICS_STATE["error_count"] = 1
            _DIAGNOSTICS_STATE["error_window_start"] = now

        if _DIAGNOSTICS_STATE["error_count"] > _DIAGNOSTICS_STATE["error_rate_threshold"]:
            logger.error(
                f"Vysoká chybovost: {_DIAGNOSTICS_STATE['error_count']} "
                f"chyb za poslední minutu (práh: {_DIAGNOSTICS_STATE['error_rate_threshold']})"
            )
    except Exception as e:
        logger.debug(f"record_error selhal: {type(e).__name__}: {e}")


def record_successful_load() -> None:
    """Zaznamená úspěšné načtení dat - uloží ISO timestamp do session_state (pokud existuje)."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        _DIAGNOSTICS_STATE["last_successful_load"] = datetime.now()
        # Zároveň uložíme do session_state pro cross-page diagnostiku
        try:
            import streamlit as st
            st.session_state[_LAST_SUCCESS_KEY] = now_iso
        except Exception:
            # Mimo Streamlit kontext - nevadí
            pass
    except Exception as e:
        logger.debug(f"record_successful_load selhal: {type(e).__name__}: {e}")


def time_operation(operation_name: Optional[str] = None):
    """Dekorátor pro měření doby trvání operace.

    Použití:
        @time_operation("load_pick_data")
        def load_pick_data():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation_name or func.__name__
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_s = (time.perf_counter() - start)
                record_operation(op_name, duration_s)
                return result
            except Exception as e:
                duration_s = (time.perf_counter() - start)
                record_operation(f"{op_name}_FAILED", duration_s)
                record_error()
                logger.exception(f"Chyba v {op_name} po {duration_s:.2f}s: {type(e).__name__}: {e}")
                raise
        return wrapper
    return decorator


def safe_execute(
    func: Callable,
    *args,
    fallback: Any = None,
    error_message: Optional[str] = None,
    log_errors: bool = True,
    operation_name: Optional[str] = None,
    raise_on_error: bool = False,
    **kwargs,
) -> Any:
    """Bezpečně vykoná funkci s fallbackem při chybě.

    Args:
        func: Funkce k vykonání
        *args: Argumenty pro func
        fallback: Co vrátit při chybě (default: None)
        error_message: Vlastní chybová zpráva pro log
        log_errors: Zda logovat chyby (default: True)
        operation_name: Název operace (default: func.__name__)
        raise_on_error: Pokud True, výjimka se vyhodí i přes fallback logiku
        **kwargs: Keyword argumenty pro func

    Returns:
        Výsledek func nebo fallback při chybě
    """
    op_name = operation_name or getattr(func, "__name__", str(func))
    try:
        return func(*args, **kwargs)
    except Exception as e:
        record_error()
        if log_errors:
            msg = error_message or f"Chyba v {op_name}"
            logger.exception(f"{msg}: {type(e).__name__}: {e}")
        if raise_on_error:
            raise
        return fallback


def get_memory_usage_mb() -> float:
    """Vrátí aktuální memory usage v MB (pokud je dostupný tracemalloc)."""
    if not tracemalloc.is_tracing():
        try:
            tracemalloc.start()
            return 0.0
        except Exception:
            return -1.0

    try:
        current, peak = tracemalloc.get_traced_memory()
        return current / (1024 * 1024)
    except Exception:
        return -1.0


def get_peak_memory_mb() -> float:
    """Vrátí peak memory usage v MB."""
    if not tracemalloc.is_tracing():
        try:
            tracemalloc.start()
            return 0.0
        except Exception:
            return -1.0

    try:
        _, peak = tracemalloc.get_traced_memory()
        return peak / (1024 * 1024)
    except Exception:
        return -1.0


def get_system_health() -> Dict[str, Any]:
    """Vrátí dict s metrikami zdraví aplikace.

    Returns:
        Dict s klíči:
        - memory_mb: Aktuální memory usage (tracemalloc, nebo None)
        - peak_memory_mb: Peak memory usage (tracemalloc, nebo None)
        - cache_size: Počet položek v Streamlit cache (-1 = neznámo)
        - last_successful_load: ISO timestamp posledního úspěšného loadu
        - operations_last_hour: Počet operací za poslední hodinu
        - slow_operations: Počet pomalých operací za poslední hodinu
        - errors_last_minute: Počet chyb za poslední minutu
        - error_count: Celkový počet chyb od posledního resetu
        - health_status: 'healthy' | 'warning' | 'critical'
        - timestamp: ISO timestamp tohoto volání
    """
    try:
        now = datetime.now()
        recent_ops = list(_DIAGNOSTICS_STATE.get("operation_times", []))
        cutoff = now - timedelta(hours=1)
        recent_ops = [(ts, op, dur) for ts, op, dur in recent_ops if ts > cutoff]
        slow_ops = [
            op for _, op, dur in recent_ops
            if dur > _DIAGNOSTICS_STATE.get("slow_operation_threshold_s", SLOW_OPERATION_THRESHOLD_S)
        ]

        memory_mb = get_memory_usage_mb()
        errors = _DIAGNOSTICS_STATE.get("error_count", 0)

        if memory_mb > 1000 or errors > 10:
            health = "critical"
        elif memory_mb > 500 or errors > 5 or len(slow_ops) > 20:
            health = "warning"
        else:
            health = "healthy"

        last_load = _DIAGNOSTICS_STATE.get("last_successful_load")
        last_load_iso = last_load.isoformat() if last_load else None

        return {
            "memory_mb": round(memory_mb, 2) if memory_mb >= 0 else None,
            "peak_memory_mb": round(get_peak_memory_mb(), 2),
            "cache_size": _safe_get_cache_size(),
            "last_successful_load": last_load_iso,
            "operations_last_hour": len(recent_ops),
            "slow_operations": len(slow_ops),
            "errors_last_minute": errors,
            "error_count": errors,
            "health_status": health,
            "timestamp": now.isoformat(),
        }
    except Exception as e:
        logger.warning(f"get_system_health selhal: {type(e).__name__}: {e}")
        return {
            "memory_mb": None,
            "peak_memory_mb": None,
            "cache_size": -1,
            "last_successful_load": None,
            "operations_last_hour": 0,
            "slow_operations": 0,
            "errors_last_minute": 0,
            "error_count": 0,
            "health_status": "unknown",
            "timestamp": datetime.now().isoformat(),
        }


def _safe_get_cache_size() -> int:
    """Bezpečně zjistí počet položek ve Streamlit cache. Vrátí -1 pokud nelze zjistit."""
    try:
        import streamlit as st
        cache = getattr(st, "cache_data", None) or getattr(st, "legacy_caching", None)
        if cache is None:
            return -1
        try:
            stats_func = getattr(cache, "get_stats", None)
            if callable(stats_func):
                stats = stats_func()
                if isinstance(stats, dict):
                    return int(stats.get("cache_size", -1))
        except Exception:
            pass
        return -1
    except Exception:
        return -1


def get_recent_error_count(window_s: float = 60.0) -> int:
    """Vrátí počet chyb za posledních `window_s` sekund (z interního state)."""
    try:
        window_start = _DIAGNOSTICS_STATE.get("error_window_start")
        if not window_start:
            return 0
        elapsed = (datetime.now() - window_start).total_seconds()
        if elapsed > window_s:
            return 0  # okno už vypršelo, reset
        return int(_DIAGNOSTICS_STATE.get("error_count", 0))
    except Exception:
        return 0


def should_warn_about_errors(threshold: int = 5, window_s: float = 60.0) -> bool:
    """True pokud počet chyb za posledních `window_s` sekund překročil `threshold`."""
    try:
        return get_recent_error_count(window_s) > threshold
    except Exception:
        return False


def force_garbage_collection() -> Dict[str, int]:
    """Vynutí garbage collection a vrátí statistiky.

    Returns:
        Dict s počtem sesbíraných objektů v každé generaci
    """
    try:
        collected_gen0 = gc.collect(0)
        collected_gen1 = gc.collect(1)
        collected_gen2 = gc.collect(2)
        return {
            "gen0": collected_gen0,
            "gen1": collected_gen1,
            "gen2": collected_gen2,
            "total": collected_gen0 + collected_gen1 + collected_gen2,
        }
    except Exception as e:
        logger.warning(f"Garbage collection selhal: {e}")
        return {"gen0": 0, "gen1": 0, "gen2": 0, "total": 0}


def reset_diagnostics() -> None:
    """Resetuje všechny diagnostické statistiky."""
    try:
        _DIAGNOSTICS_STATE["operation_times"] = []
        _DIAGNOSTICS_STATE["error_count"] = 0
        _DIAGNOSTICS_STATE["error_window_start"] = None
        _DIAGNOSTICS_STATE["last_successful_load"] = None
    except Exception as e:
        logger.debug(f"reset_diagnostics selhal: {type(e).__name__}: {e}")


def render_health_panel() -> None:
    """Vykreslí diagnostický panel do Streamlit sidebaru."""
    try:
        import streamlit as st

        health = get_system_health()
        status_emoji = {
            "healthy": "✅",
            "warning": "⚠️",
            "critical": "🔴",
        }
        emoji = status_emoji.get(health["health_status"], "❓")

        with st.sidebar:
            with st.expander(f"{emoji} **Diagnostika**", expanded=False):
                st.markdown(f"**Status:** `{health['health_status'].upper()}`")

                if health["memory_mb"] is not None:
                    st.metric("💾 Paměť", f"{health['memory_mb']:.1f} MB")
                    st.caption(f"Peak: {health['peak_memory_mb']:.1f} MB")

                st.metric("⚡ Operací/hod", health["operations_last_hour"])
                if health["slow_operations"] > 0:
                    st.warning(f"🐌 Pomalých: {health['slow_operations']}")

                if health["errors_last_minute"] > 0:
                    st.error(f"❌ Chyb/min: {health['errors_last_minute']}")

                if health["last_successful_load"]:
                    try:
                        last_dt = datetime.fromisoformat(health["last_successful_load"])
                        age = int((datetime.now() - last_dt).total_seconds())
                        st.caption(f"📅 Poslední load: {age}s ago")
                    except Exception:
                        st.caption(f"📅 Poslední load: {health['last_successful_load']}")

                if st.button("🧹 Vyčistit paměť", width="stretch"):
                    stats = force_garbage_collection()
                    st.success(f"Uvolněno: {stats['total']} objektů")

                if st.button("🔄 Reset diagnostiky", width="stretch"):
                    reset_diagnostics()
                    st.success("Diagnostika resetována")
    except ImportError:
        # Mimo Streamlit kontext - tiše přeskočíme
        pass
    except Exception as e:
        logger.warning(f"Render health panel selhal: {e}")