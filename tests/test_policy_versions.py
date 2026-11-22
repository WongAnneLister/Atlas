from datetime import date

import pytest

from support_agent.config import get_settings
from support_agent.data.policy_versions import (
    PolicySection,
    load_versions,
    version_id,
)


def test_synthetic_policy_starts_and_ends_at_declared_boundaries():
    versions = load_versions(get_settings().policy_versions)
    assert len(versions.entries) == 2
    current = {
        entry.base_section_id: PolicySection(heading="Generic store", prose=entry.old.find)
        for entry in versions.entries
    }
    historical = versions.apply_versions(current)
    assert len(historical) == 2
    for entry in versions.entries:
        old_id = version_id(entry.base_section_id, date(2026, 1, 1))
        assert historical[old_id] == PolicySection(
            heading="Generic store (policy before 2026-09-01)", prose=entry.old.replace
        )
        assert entry.section_at(date(2026, 8, 31)) == old_id
        assert entry.section_at(date(2026, 9, 1)) == entry.base_section_id


@pytest.mark.parametrize("occurrences", [0, 2])
def test_changed_source_text_cannot_generate_historical_version(occurrences):
    versions = load_versions(get_settings().policy_versions)
    entry = versions.entries[0]
    base = PolicySection(heading="Generic store", prose=entry.old.find * occurrences)
    with pytest.raises(ValueError, match="exactly once"):
        entry.historical_section(base)
