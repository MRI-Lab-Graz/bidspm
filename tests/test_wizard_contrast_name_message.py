import pytest

from lib.model_wizard import WizardError, _contrast_name


def test_a_value_with_no_ascii_word_character_gets_an_honest_message():
    with pytest.raises(WizardError) as e:
        _contrast_name("trial_type.é")
    assert str(e.value) == (
        "trial_type value 'é' has no ASCII letter, digit or underscore characters, so no contrast name can be derived "
        "from it; rename it in the events file, rename/merge it with the Merge recipe, or uncheck it in step 1")


def test_a_value_with_some_ascii_still_builds():
    assert _contrast_name("trial_type.café") == "caf"
