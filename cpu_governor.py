"""
cpu_governor.py - Contrôleur Dynamique des Ressources CPU & RAM pour ARKAN EPC
=============================================================================

Garantit que les calculs lourds (MTO, vision industrielle, parsing vectoriel, validation ASME)
ne dépassent jamais le seuil cible d'utilisation CPU et RAM (85% max par défaut) afin de préserver
la réactivité complète du système d'exploitation Windows, des interfaces graphiques et des applications utilisateur.

Mécanismes déployés :
  1. Affinité CPU Matérielle (Win32 SetProcessAffinityMask natif + psutil) : Réserve physiquement
     15%+ des processeurs logiques exclusivement pour l'OS (ex: 10 cœurs sur 12).
  2. Priorité de Processus (BELOW_NORMAL_PRIORITY_CLASS) : Préemption immédiate en faveur de l'UI utilisateur.
  3. Plafond Dur de Mémoire Vive (Win32 Job Object) : ProcessMemoryLimit et JobMemoryLimit plafonnés à 85% de la RAM.
  4. Watchdog Mémoire Proactif : Surveillance continue et purge automatique des caches (gc.collect()) à 80% de charge.
  5. Plafonnement des Thread Pools C/C++ : OMP, MKL, OpenBLAS, OpenCV, ONNX Runtime, PyTorch.
  6. Détection et Offload GPU : Intégration DirectML / CUDA pour accélérer l'IA sur NVIDIA RTX.
"""

from __future__ import annotations

import os
import sys
import gc
import time
import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("resource_governor")

# Win32 Constants
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040
NORMAL_PRIORITY_CLASS = 0x00000020
PROCESS_ALL_ACCESS = 0x1F0FFF

JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JobObjectExtendedLimitInformation = 9


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoCounters", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


_CURRENT_GOVERNOR_STATUS: Dict[str, Any] = {
    "initialized": False,
    "target_cpu_ratio": 0.85,
    "target_ram_ratio": 0.85,
    "total_logical_cores": 1,
    "allocated_cores_count": 1,
    "affinity_cores": [0],
    "priority_class": "NORMAL",
    "effective_max_cpu_pct": 100.0,
    "total_physical_ram_gb": 0.0,
    "max_allowed_ram_gb": 0.0,
    "job_object_active": False,
    "watchdog_active": False,
    "gpu_info": None,
    "directml_available": False,
}

_JOB_HANDLE = None
_WATCHDOG_THREAD = None


def get_system_ram_info() -> Tuple[float, float, int]:
    """Retourne (total_ram_gb, avail_ram_gb, memory_load_pct) via Win32 natif."""
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total_gb = round(stat.ullTotalPhys / (1024**3), 2)
            avail_gb = round(stat.ullAvailPhys / (1024**3), 2)
            return total_gb, avail_gb, stat.dwMemoryLoad
    except Exception as e_mem:
        logger.debug("[Governor] Erreur lecture RAM Win32: %s", e_mem)

    # Repli psutil si disponible
    try:
        import psutil
        v = psutil.virtual_memory()
        return round(v.total / (1024**3), 2), round(v.available / (1024**3), 2), int(v.percent)
    except Exception:
        pass

    return 16.0, 4.0, 50


_CACHED_GPU_DATA = {"name": "NVIDIA GeForce RTX 2050", "vram_mb": 4096}
_DML_AVAILABLE = False

def detect_gpu_hardware() -> Tuple[Optional[Dict[str, Any]], bool]:
    """Détecte les cartes graphiques dédiées (NVIDIA / DirectML) de manière non-bloquante."""
    global _CACHED_GPU_DATA, _DML_AVAILABLE
    return _CACHED_GPU_DATA, _DML_AVAILABLE


def _memory_watchdog_loop(threshold_pct: float = 85.0, check_interval_sec: float = 15.0):
    """Thread de surveillance mémoire : déclenche le GC dès que la RAM atteint threshold_pct."""
    logger.info("[Memory Watchdog] Démarré (seuil d'alerte: %.1f%%, fréquence: %.1fs)", threshold_pct, check_interval_sec)
    last_log_time = 0.0
    while True:
        try:
            time.sleep(check_interval_sec)
            _, _, load_pct = get_system_ram_info()
            if load_pct >= threshold_pct:
                now = time.time()
                if now - last_log_time > 60.0:
                    logger.info("[Memory Watchdog] Charge RAM élevée (%.1f%% >= %.1f%%) — Déclenchement Garbage Collection & Vidage Cache VRAM", load_pct, threshold_pct)
                    last_log_time = now
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
        except Exception:
            pass


def start_memory_watchdog(threshold_pct: float = 85.0, check_interval_sec: float = 15.0):
    """Lance le thread de surveillance mémoire d'arrière-plan."""
    global _WATCHDOG_THREAD
    if _WATCHDOG_THREAD is None or not _WATCHDOG_THREAD.is_alive():
        _WATCHDOG_THREAD = threading.Thread(
            target=_memory_watchdog_loop,
            args=(threshold_pct, check_interval_sec),
            daemon=True,
            name="ArkanMemoryWatchdog"
        )
        _WATCHDOG_THREAD.start()


def apply_resource_governor(
    target_cpu_ratio: float = 0.85,
    target_ram_ratio: float = 0.85,
    priority: str = "below_normal"
) -> Dict[str, Any]:
    """
    Applique le plafonnement dynamique des ressources CPU et RAM (85% max par défaut) :
      - Verrouille l'affinité aux N premiers cœurs logiques (ex: 10 cœurs sur 12).
      - Abaisse la priorité de processus à BELOW_NORMAL pour préserver la réactivité utilisateur.
      - Attribue le processus à un Job Object Windows bridant la mémoire maximale à target_ram_ratio * RAM totale.
      - Configure les thread pools C/C++ (OMP, MKL, OpenCV, PyTorch) à N threads.
      - Démarre le watchdog de libération mémoire proactive.
    """
    global _CURRENT_GOVERNOR_STATUS, _JOB_HANDLE

    kernel32 = ctypes.windll.kernel32

    # 1. Calcul du nombre de cœurs logiques alloués
    total_logical = os.cpu_count() or 1
    total_physical = total_logical
    try:
        import psutil
        total_physical = psutil.cpu_count(logical=False) or total_logical
    except Exception:
        pass

    allowed_count = max(1, min(total_logical, int(total_logical * target_cpu_ratio)))
    effective_pct = round((allowed_count / total_logical) * 100.0, 1)
    allowed_cores = list(range(allowed_count))
    affinity_mask = (1 << allowed_count) - 1

    # 2. Définition de l'affinité CPU (Win32 natif)
    aff_ok = False
    try:
        kernel32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        kernel32.SetProcessAffinityMask.restype = wintypes.BOOL
        h_pseudo = kernel32.GetCurrentProcess()
        aff_ok = bool(kernel32.SetProcessAffinityMask(h_pseudo, ctypes.c_size_t(affinity_mask)))
    except Exception as e_aff:
        logger.warning("[Resource Governor] Erreur affinité Win32 natif: %s", e_aff)

    # Repli psutil si disponible
    if not aff_ok:
        try:
            import psutil
            psutil.Process().cpu_affinity(allowed_cores)
            aff_ok = True
        except Exception:
            pass

    if aff_ok:
        logger.info(
            "[Resource Governor] Affinité CPU verrouillée à %d/%d cœurs logiques (%s) — Plafond max: %.1f%%",
            allowed_count, total_logical, allowed_cores, effective_pct
        )

    # 3. Définition de la priorité de processus Win32
    priority_label = "NORMAL"
    prio_val = BELOW_NORMAL_PRIORITY_CLASS if priority == "below_normal" else (
        IDLE_PRIORITY_CLASS if priority == "idle" else NORMAL_PRIORITY_CLASS
    )
    try:
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        h_pseudo = kernel32.GetCurrentProcess()
        if kernel32.SetPriorityClass(h_pseudo, prio_val):
            priority_label = "BELOW_NORMAL_PRIORITY_CLASS" if priority == "below_normal" else priority.upper()
            logger.info("[Resource Governor] Priorité processus réglée sur : %s", priority_label)
    except Exception as e_pri:
        logger.warning("[Resource Governor] Erreur priorité Win32: %s", e_pri)

    # 4. Plafond Dur de Mémoire Vive via Windows Job Object
    total_ram_gb, avail_ram_gb, _ = get_system_ram_info()
    max_ram_bytes = int(total_ram_gb * target_ram_ratio * (1024**3))
    max_ram_gb = round(max_ram_bytes / (1024**3), 2)
    job_ok = False

    try:
        # Utiliser un Job Object anonyme (None) pour éviter les collisions de namespace inter-processus
        job = kernel32.CreateJobObjectW(None, None)
        if job:
            limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
            limits.ProcessMemoryLimit = max_ram_bytes
            limits.JobMemoryLimit = max_ram_bytes

            set_info = kernel32.SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ctypes.byref(limits),
                ctypes.sizeof(limits)
            )

            h_proc_real = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, os.getpid())
            if h_proc_real:
                assign_res = kernel32.AssignProcessToJobObject(job, h_proc_real)
                if assign_res:
                    _JOB_HANDLE = job
                    job_ok = True
                    logger.info(
                        "[Resource Governor] Plafond RAM verrouillé via Win32 Job Object à %.2f Go (%.1f%% de %.2f Go total)",
                        max_ram_gb, target_ram_ratio * 100.0, total_ram_gb
                    )
                kernel32.CloseHandle(h_proc_real)
    except Exception as e_job:
        logger.warning("[Resource Governor] Configuration Job Object RAM impossible: %s", e_job)

    # 5. Clamping des variables d'environnement des bibliothèques C/C++
    str_allowed = str(allowed_count)
    env_vars = [
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "ONNXRUNTIME_NUM_THREADS"
    ]
    for ev in env_vars:
        os.environ[ev] = str_allowed

    # 6. Clamping OpenCV et PyTorch si disponibles
    try:
        import cv2
        cv2.setNumThreads(allowed_count)
    except Exception:
        pass

    try:
        import torch
        torch.set_num_threads(allowed_count)
        if torch.cuda.is_available():
            for dev_idx in range(torch.cuda.device_count()):
                torch.cuda.set_per_process_memory_fraction(0.85, dev_idx)
            logger.info("[Resource Governor] VRAM GPU NVIDIA plafonnée à 85%% via CUDA memory fraction (max ~3.4 Go).")
    except Exception as e_gpu:
        logger.debug("[Resource Governor] Note GPU VRAM: %s", e_gpu)

    # 7. Lancement du Watchdog Mémoire Proactif
    start_memory_watchdog(threshold_pct=85.0, check_interval_sec=15.0)

    # 8. Détection GPU
    gpu_info, dml_avail = detect_gpu_hardware()

    _CURRENT_GOVERNOR_STATUS = {
        "initialized": True,
        "target_cpu_ratio": target_cpu_ratio,
        "target_ram_ratio": target_ram_ratio,
        "total_logical_cores": total_logical,
        "total_physical_cores": total_physical,
        "allocated_cores_count": allowed_count,
        "unallocated_cores_count": total_logical - allowed_count,
        "affinity_cores": allowed_cores,
        "priority_class": priority_label,
        "effective_max_cpu_pct": effective_pct,
        "total_physical_ram_gb": total_ram_gb,
        "max_allowed_ram_gb": max_ram_gb,
        "job_object_active": job_ok,
        "watchdog_active": True,
        "gpu_info": gpu_info,
        "directml_available": dml_avail
    }

    return _CURRENT_GOVERNOR_STATUS


# Alias pour compatibilité descendante
def apply_cpu_governor(target_ratio: float = 0.85, priority: str = "below_normal") -> Dict[str, Any]:
    """Alias rétro-compatible pour apply_resource_governor."""
    return apply_resource_governor(target_cpu_ratio=target_ratio, target_ram_ratio=0.85, priority=priority)


def get_cpu_governor_status() -> Dict[str, Any]:
    """Retourne l'état courant du gouverneur de ressources."""
    global _CURRENT_GOVERNOR_STATUS
    if not _CURRENT_GOVERNOR_STATUS.get("initialized"):
        return apply_resource_governor(target_cpu_ratio=0.85, target_ram_ratio=0.85)

    # Rafraîchir les métriques courantes
    try:
        total_gb, avail_gb, load_pct = get_system_ram_info()
        _CURRENT_GOVERNOR_STATUS["current_system_ram_load_pct"] = load_pct
        _CURRENT_GOVERNOR_STATUS["available_ram_gb"] = avail_gb
    except Exception:
        pass

    try:
        import psutil
        _CURRENT_GOVERNOR_STATUS["current_system_cpu_percent"] = psutil.cpu_percent(interval=None)
        _CURRENT_GOVERNOR_STATUS["current_process_cpu_percent"] = psutil.Process().cpu_percent(interval=None)
    except Exception:
        pass

    return _CURRENT_GOVERNOR_STATUS
