"""Tests for :mod:`habitron_client.faults` (module operate-mode fault decoder).

The bitmask layout is a fixed contract shared with the SmartHub firmware, so
these pin every bit, the reserved bit and multi-fault combinations.
"""

from habitron_client.faults import MODULE_FAULTS, ModuleFault, decode_module_faults


def test_no_faults_returns_empty() -> None:
    """A zero mask (module healthy) decodes to no faults."""
    assert decode_module_faults(0) == []


def test_single_bits_map_to_expected_codes() -> None:
    """Each defined bit maps to its documented display code and label."""
    assert decode_module_faults(0x01) == [
        ModuleFault("F1", "Timeout Modulkommunikation")
    ]
    assert decode_module_faults(0x02) == [
        ModuleFault("F2", "Fehler Modulkommunikation")
    ]
    assert decode_module_faults(0x04) == [ModuleFault("F4", "Abspeicherfehler")]
    assert decode_module_faults(0x10) == [ModuleFault("F16", "Fehler Leistungsteil")]
    assert decode_module_faults(0x20) == [
        ModuleFault("F32", "Fehler Ekey/GSM-Kommunikation")
    ]
    # The two free high bits carry the forward-table (F3) and mirror (F5) faults.
    assert decode_module_faults(0x40) == [
        ModuleFault("F3", "Weiterleitungstabelle nicht geheilt")
    ]
    assert decode_module_faults(0x80) == [ModuleFault("F5", "Spiegelung gestört")]


def test_reserved_bit_is_ignored() -> None:
    """The reserved 0x08 bit yields no fault and never appears in the table."""
    assert decode_module_faults(0x08) == []
    assert 0x08 not in MODULE_FAULTS


def test_multiple_faults_ordered_by_ascending_bit() -> None:
    """A combined mask decodes to all set faults, ascending by bit value."""
    faults = decode_module_faults(0x01 | 0x10 | 0x80)
    assert [f.code for f in faults] == ["F1", "F16", "F5"]


def test_all_bits_set_decodes_every_defined_fault() -> None:
    """0xFF decodes to exactly the seven defined faults (reserved bit dropped)."""
    assert decode_module_faults(0xFF) == list(MODULE_FAULTS.values())
