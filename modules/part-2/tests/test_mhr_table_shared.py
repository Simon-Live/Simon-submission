"""`avatar` and `autorig` read one MHR joint table (part2/mhr_export.py); neither keeps a copy."""
from part2 import autorig, avatar, mhr_export


def test_both_commands_use_the_same_table():
    assert autorig.MHR_INDEX is mhr_export.MHR_INDEX
    assert autorig.UNDER is mhr_export.UNDER
    assert autorig.JOINTS == mhr_export.JOINTS == 127
    assert autorig.LICENCE == mhr_export.LICENCE
    assert autorig.joint_names is mhr_export.joint_names
    if hasattr(avatar, "MHR_INDEX"):
        assert avatar.MHR_INDEX is mhr_export.MHR_INDEX


def test_autorig_source_defines_no_table_of_its_own():
    import inspect
    src = inspect.getsource(autorig)
    assert "MHR_INDEX = {" not in src and "UNDER = {" not in src
