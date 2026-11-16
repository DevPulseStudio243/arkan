# cpu_governor.py

- IO_COUNTERS · class · L44-L52 — class IO_COUNTERS(ctypes.Structure)
- JOBOBJECT_BASIC_LIMIT_INFORMATION · class · L55-L66 — class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure)
- JOBOBJECT_EXTENDED_LIMIT_INFORMATION · class · L69-L77 — class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure)
- MEMORYSTATUSEX · class · L80-L91 — class MEMORYSTATUSEX(ctypes.Structure)
- get_system_ram_info · function · L115-L135 — def get_system_ram_info() -> Tuple[float, float, int]
- detect_gpu_hardware · function · L141-L144 — def detect_gpu_hardware() -> Tuple[Optional[Dict[str, Any]], bool]
- _memory_watchdog_loop · function · L147-L168 — def _memory_watchdog_loop(threshold_pct: float = 85.0, check_interval_sec: float = 15.0)
- start_memory_watchdog · function · L171-L181 — def start_memory_watchdog(threshold_pct: float = 85.0, check_interval_sec: float = 15.0)
- apply_resource_governor · function · L184-L346 — def apply_resource_governor( target_cpu_ratio: float = 0.85, target_ram_ratio: float = 0.85, priority: str = "below_normal" ) -> Dict[str, Any]
- apply_cpu_governor · function · L350-L352 — def apply_cpu_governor(target_ratio: float = 0.85, priority: str = "below_normal") -> Dict[str, Any]
- get_cpu_governor_status · function · L355-L376 — def get_cpu_governor_status() -> Dict[str, Any]
