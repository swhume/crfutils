"""annotations: the SDTM annotation grammar, table-driven from the vocabularies found in real CRFs."""
import pytest

from crfutils import annotations as A

KNOWN = {"VS", "DM", "CM", "AE", "FT", "SU"}


def _parse(text, level="item", context=None, known=KNOWN, source=None):
    return A.parse(text, level=level, source=source, context_domain=context, known_domains=known)


def _keys(parsed) -> list:
    return [t.key for t in parsed.targets]


# domains

@pytest.mark.parametrize("text, domain", [
    ("DOMAIN = VS", "VS"), ("DOMAIN=VS", "VS"), ("VS (Vital Signs)", "VS"), ("VS = Vital Signs", "VS"), ("VS", "VS"),
    ("SUPPFT", "SUPPFT"), ("  DM  ", "DM"), ("AE (Adverse Events)", "AE"),
])
def test_group_level_domains(text, domain):
    parsed = _parse(text, level="group")
    assert parsed.status == A.PARSED
    assert parsed.domains == (domain,)
    assert parsed.targets == ()


def test_item_level_bare_token_is_a_domain_only_when_known():
    assert _parse("VS").domains == ("VS",)
    assert _keys(_parse("VS")) == []
    unknown = _parse("ZZ", context="DM")
    assert unknown.domains == ()
    assert _keys(unknown) == ["DM.ZZ"]


def test_all_is_never_a_domain():
    assert _parse("ALL", level="group").domains == ()
    assert _parse("ALL", level="item").domains == ()


def test_domain_attribute_is_taken_as_it_stands():
    assert _parse("CM", level="group", source="attr:Domain").domains == ("CM",)
    lower = _parse("all", level="group", source="attr:Domain")
    assert lower.domains == () and lower.status == A.UNPARSED and lower.unparsed == ("all",)
    assert _parse("", level="group", source="attr:Domain").status == A.EMPTY


# targets

@pytest.mark.parametrize("text, context, keys", [
    ("VSORRES when VSTESTCD = SYSBP", None, ["VS.VSORRES where VSTESTCD = SYSBP"]),
    ("VSORRESU = mmHg when VSTESTCD = SYSBP", None, ["VS.VSORRESU where VSTESTCD = SYSBP"]),
    ("VSORRES where VSTESTCD=SYSBP", None, ["VS.VSORRES where VSTESTCD = SYSBP"]),
    ("RSSTRESN/RSSTRESC where RSTESTCD=ATLAS101", "RS", ["RS.RSSTRESN where RSTESTCD = ATLAS101",
                                                        "RS.RSSTRESC where RSTESTCD = ATLAS101"]),
    ("FTASTDEV in SUPPFT", None, ["SUPPFT.QVAL where QNAM = FTASTDEV"]),
    ("CMINDC in SUPPCM", None, ["SUPPCM.QVAL where QNAM = CMINDC"]),
    ("CMDOSE;CMDOSTXT", None, ["CM.CMDOSE", "CM.CMDOSTXT"]),
    ("CMDOSE; CMDOSTXT", None, ["CM.CMDOSE", "CM.CMDOSTXT"]),
    ("DM.SEX=M", None, ["DM.SEX"]),
    ("DM.SEX", None, ["DM.SEX"]),
    ("CM.CMCAT='GENERAL'", None, ["CM.CMCAT"]),
    ("SEX", "DM", ["DM.SEX"]),
    ("AGE", "DM", ["DM.AGE"]),
    ("[NOT SUBMITTED]; VSSTAT = NOT DONE when VSTESTCD = VSALL", None, ["VS.VSSTAT where VSTESTCD = VSALL"]),
    ("[NOT SUBMITTED];CMSTRF;CMSTRTPT", None, ["CM.CMSTRF", "CM.CMSTRTPT"]),
    ("AEACN = DRUG WITHDRAWN if AESER = Y and AEREL IN (POSSIBLE, PROBABLE)", None,
     ["AE.AEACN where AEREL IN (POSSIBLE, PROBABLE) and AESER = Y"]),
    ("LBORRES when LBTESTCD NE HGB", "LB", ["LB.LBORRES where LBTESTCD NE HGB"]),
    ("LBORRES when LBTESTCD != HGB", "LB", ["LB.LBORRES where LBTESTCD NE HGB"]),
    ("VSORRES when VSTESTCD EQ 'SYSBP'", None, ["VS.VSORRES where VSTESTCD = SYSBP"]),
    ("SUDOSE", None, ["SU.SUDOSE"]),
])
def test_targets_and_keys(text, context, keys):
    parsed = _parse(text, context=context)
    assert parsed.status == A.PARSED, parsed
    assert _keys(parsed) == keys


def test_value_and_conditions_are_kept():
    target = _parse("VSORRESU = mmHg when VSTESTCD = SYSBP").targets[0]
    assert (target.dataset, target.variable, target.value) == ("VS", "VSORRESU", "mmHg")
    assert target.where == (A.Condition("VSTESTCD", "EQ", ("SYSBP",)),)
    assert target.qnam is None
    assert target.dataset_source == "prefix"


def test_supp_target():
    target = _parse("FTASTDEV in SUPPFT").targets[0]
    assert (target.dataset, target.variable, target.qnam, target.dataset_source) == ("SUPPFT", "QVAL", "FTASTDEV", "supp")
    assert target.where == (A.Condition("QNAM", "EQ", ("FTASTDEV",)),)


def test_not_submitted():
    assert _parse("[NOT SUBMITTED]").not_submitted
    assert _parse("[NOT SUBMITTED]").status == A.PARSED
    assert _parse("NOT SUBMITTED").not_submitted
    assert _parse("not submitted").not_submitted
    parsed = _parse("[NOT SUBMITTED]; VSSTAT = NOT DONE when VSTESTCD = VSALL")
    assert parsed.not_submitted and parsed.targets[0].value == "NOT DONE"
    assert not _parse("VSORRES").not_submitted


# dataset resolution

def test_dataset_sources():
    assert _parse("DM.SEX").targets[0].dataset_source == "qualified"
    assert _parse("CMINDC in SUPPCM").targets[0].dataset_source == "supp"
    assert _parse("VSORRES").targets[0].dataset_source == "prefix"
    assert _parse("SEX", context="DM").targets[0].dataset_source == "context"


def test_prefix_takes_the_longest_known_domain():
    parsed = _parse("SUPPAEQVAL", known={"SU", "SUPPAE"})
    assert parsed.targets[0].dataset == "SUPPAE"


def test_prefix_must_be_strict():
    # the variable VS is not VS-prefixed; with VS known it is a domain, and with nothing known it is unresolved
    assert _parse("VS", known=set()).targets[0].dataset is None


def test_qualified_dataset_beats_context_and_prefix():
    assert _parse("DM.VSORRES", context="AE").targets[0].dataset == "DM"


def test_unresolved_dataset_warns_and_keys_the_bare_variable():
    parsed = _parse("RSORRES", known=set())
    assert parsed.status == A.PARSED
    assert parsed.targets[0].dataset is None and parsed.targets[0].dataset_source is None
    assert parsed.targets[0].key == "RSORRES"
    assert A.DATASET_UNRESOLVED in parsed.warnings


# what cannot be read

def test_unparsed_text():
    parsed = _parse("see protocol section 5")
    assert parsed.status == A.UNPARSED
    assert parsed.unparsed == ("see protocol section 5",)
    assert parsed.warnings == (A.UNPARSED_TEXT,)
    assert parsed.targets == ()


def test_partial():
    parsed = _parse("CMTRT; see the protocol")
    assert parsed.status == A.PARTIAL
    assert _keys(parsed) == ["CM.CMTRT"]
    assert parsed.unparsed == ("see the protocol",)


def test_unparsed_condition_keeps_the_target():
    parsed = _parse("VSORRES when VSTESTCD")
    assert _keys(parsed) == ["VS.VSORRES"]
    assert A.UNPARSED_CONDITION in parsed.warnings
    assert parsed.status == A.PARSED


@pytest.mark.parametrize("text", ["", "   ", None, ";;"])
def test_empty(text):
    parsed = _parse(text)
    assert parsed.status == A.EMPTY
    assert parsed.targets == () and parsed.domains == ()


def test_parse_never_raises_on_odd_input():
    for text in ["=", "= =", "when", "x in SUPP", "(", "A.B.C", "lowercase var", "VS.", "1ABC"]:
        A.parse(text, known_domains=KNOWN)


# the key

def test_target_key_canonical_form():
    where = [A.Condition("VSTESTCD", "EQ", ("SYSBP",)), A.Condition("VSPOS", "IN", ("SUPINE", "SITTING")),
             A.Condition("VSCAT", "NE", ("X",))]
    assert A.target_key("VS", "VSORRES", where) == \
           "VS.VSORRES where VSCAT NE X and VSPOS IN (SITTING, SUPINE) and VSTESTCD = SYSBP"
    assert A.target_key("VS", "VSORRES") == "VS.VSORRES"
    assert A.target_key(None, "VSORRES") == "VSORRES"


def test_whitespace_is_normalized():
    assert _parse("  VSORRES   when   VSTESTCD  =  SYSBP ").targets[0].key == "VS.VSORRES where VSTESTCD = SYSBP"
    assert A.normalize("a\n  b\tc") == "a b c"


def test_datasets_named():
    assert A.datasets_named("FTASTDEV in SUPPFT") == {"FT"}
    assert A.datasets_named("DM.SEX=M;RS.X/RSY") == {"DM", "RS"}
    assert A.datasets_named("VSORRES when VSTESTCD = SYSBP") == set()
    assert A.datasets_named("[NOT SUBMITTED]; LB.LBORRES") == {"LB"}
