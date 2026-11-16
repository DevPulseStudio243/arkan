"""
Tests de validation pour le Resource Governor (Plafonnement 85% CPU & RAM).
"""
import os
import sys
import pytest

from cpu_governor import apply_resource_governor, get_cpu_governor_status, get_system_ram_info


def test_resource_governor_85pct():
    status = apply_resource_governor(target_cpu_ratio=0.85, target_ram_ratio=0.85)

    assert status["initialized"] is True
    assert status["target_cpu_ratio"] == 0.85
    assert status["target_ram_ratio"] == 0.85

    # Cœurs alloués : sur 12 cœurs -> 10 cœurs
    total_logical = status["total_logical_cores"]
    allocated = status["allocated_cores_count"]
    expected_allocated = max(1, min(total_logical, int(total_logical * 0.85)))
    assert allocated == expected_allocated

    # Vérification que des cœurs restent libres pour Windows
    assert status["unallocated_cores_count"] >= 1

    # Priorité BELOW_NORMAL
    assert "BELOW_NORMAL" in status["priority_class"]

    # RAM bridée
    total_ram = status["total_physical_ram_gb"]
    max_ram = status["max_allowed_ram_gb"]
    assert max_ram <= total_ram * 0.86
    assert status["job_object_active"] is True
    assert status["watchdog_active"] is True


def test_get_system_ram_info():
    total_gb, avail_gb, load_pct = get_system_ram_info()
    assert total_gb > 0
    assert avail_gb >= 0
    assert 0 <= load_pct <= 100
