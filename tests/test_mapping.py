"""mapping: the mappingInstructions grammar, the alias correction, the concept-group conditions and the proposed origin."""
import pytest

from crfutils import annotations as A
from crfutils import mapping as M
from crfutils._design import Alias, AnnotationRecord, Origin

KNOWN = {"AE", "CM", "LB", "MH", "VS"}

# the CDASHIG mapping instructions as data-definition-engine writes them
DIRECT = "Maps directly to the SDTMIG variable listed in the SDTMIG Target column."
CONCATENATED = ("This does not map directly to an SDTMIG variable. For the SDTM submission dataset, concatenate all "
                "collected CDASH START DATE and TIME components and populate the SDTMIG variable AESTDTC in ISO 8601 "
                "format.")
RELATIVE = ("This does not map directly to an SDTM variable. May be used to populate a value into an SDTMIG relative "
            "timing variable such as MHSTRF or MHSTRTPT.")
SPLIT = ("This does not map directly to an SDTMIG variable. Numeric values map to CMDOSE in SDTM. Non-numeric values "
         "(e.g., \"200-400\") map to CMDOSTXT in SDTM.")
SPLIT_IF = ("This does not map directly to an SDTMIG variable. The data collected in this dose text-format field should "
            "be mapped to either ECDOSE if numeric or ECDOSTXT if text.")
NOT_SUBMITTED = ("When ECADJ is collected, does not map to an SDTMIG variable. The SDTM annotated CRF indicates that this "
                 "field is NOT SUBMITTED. When ECADJ is not collected, the sponsor may submit this variable in SUPPEC.")


def _parse(text, context=None):
    return A.parse(text, level="item", context_domain=context, known_domains=KNOWN)


def _record(item_oid, group_path=("IG.FORM.LB", "IG.SEC.LB", "IG.CON.PT"), level="item"):
    return AnnotationRecord(level, "alias:SDTM", "", group_path[0], group_path, item_oid=item_oid)


# classify

@pytest.mark.parametrize("text, kind, variables", [
    (DIRECT, M.DIRECT, ()),
    (DIRECT + " May be used to create RELREC to link this record with a record in another domain.", M.DIRECT, ()),
    (CONCATENATED, M.CONCATENATED, ("AESTDTC",)),
    (RELATIVE, M.RELATIVE_TIMING, ()),
    (SPLIT, M.SPLIT, ()),
    (SPLIT_IF, M.SPLIT, ()),
    (NOT_SUBMITTED, M.NOT_SUBMITTED, ()),
    ("Sponsor-defined.", M.OTHER, ()),
])
def test_classify(text, kind, variables):
    instruction = M.classify(text)
    assert (instruction.kind, instruction.variables) == (kind, variables)
    assert instruction.text == text


def test_classify_normalizes_and_ignores_placeholders():
    assert M.classify("  Maps directly\n   to the SDTMIG variable  ").text == "Maps directly to the SDTMIG variable"
    assert M.classify(None) is None and M.classify("  ") is None and M.classify(M.PLACEHOLDER) is None


def test_instructions_text_reads_the_alias():
    aliases = (Alias("CDASH", "AESTDAT"), Alias("mappingInstructions", CONCATENATED), Alias("SDTM", "AESTDAT"))
    assert M.instructions_text(aliases) == CONCATENATED
    assert M.instructions_text((Alias("SDTM", "AESTDAT"),)) is None


# correct

def test_correct_replaces_a_cdash_name_with_the_variable_the_instructions_name():
    parsed, disagreement = M.correct(_parse("AESTDAT"), M.classify(CONCATENATED), known_domains=KNOWN)

    target = parsed.targets[0]
    assert (target.dataset, target.dataset_source, target.variable, target.key, target.variable_source) == \
           ("AE", "prefix", "AESTDTC", "AE.AESTDTC", "mappingInstructions")
    assert disagreement == "the SDTM annotation names AESTDAT; the mapping instructions name AESTDTC"


def test_correct_keeps_a_qualified_dataset_and_the_conditions():
    parsed, _ = M.correct(_parse("AE.AESTDAT when AECAT = SOLICITED"), M.classify(CONCATENATED), known_domains=KNOWN)
    assert parsed.targets[0].key == "AE.AESTDTC where AECAT = SOLICITED"
    assert parsed.targets[0].dataset_source == "qualified"


def test_correct_leaves_agreeing_and_uninstructed_annotations_alone():
    agreeing = _parse("AESTDTC")
    assert M.correct(agreeing, M.classify(CONCATENATED), known_domains=KNOWN) == (agreeing, None)
    assert M.correct(agreeing, M.classify(DIRECT), known_domains=KNOWN) == (agreeing, None)
    assert M.correct(agreeing, None, known_domains=KNOWN) == (agreeing, None)
    not_submitted = _parse("[NOT SUBMITTED]")
    assert M.correct(not_submitted, M.classify(NOT_SUBMITTED)) == (not_submitted, None)


def test_correct_only_describes_what_it_cannot_resolve():
    several = _parse("AESTDAT;AESTTIM")
    assert M.correct(several, M.classify(CONCATENATED), known_domains=KNOWN) == \
           (several, "the SDTM annotation names AESTDAT, AESTTIM; the mapping instructions name AESTDTC")
    supp = _parse("AESTDAT in SUPPAE")
    assert M.correct(supp, M.classify(CONCATENATED))[0] == supp


def test_correct_flags_targets_the_instructions_say_are_not_submitted():
    parsed = _parse("ECDOSADJ")
    assert M.correct(parsed, M.classify(NOT_SUBMITTED)) == \
           (parsed, "the mapping instructions say the field is not submitted, but the SDTM annotation names ECDOSADJ")


# enrich

def test_enrich_adds_the_concept_groups_fixed_value_to_value_level_targets():
    pairs = [(_record("IT.PT_LBSPEC"), _parse("LBSPEC = BLOOD")),
             (_record("IT.PT_LBORRES"), _parse("LBORRES when LBTESTCD = PT")),
             (_record("IT.PT_LBDAT"), _parse("LBDTC"))]

    spec, result, date = M.enrich(pairs, ["IG.CON.PT"])

    assert spec == pairs[0][1] and date == pairs[2][1]
    assert result.targets[0].where == (A.Condition("LBTESTCD", "EQ", ("PT",)),
                                       A.Condition("LBSPEC", "EQ", ("BLOOD",), source="concept"))
    assert result.targets[0].key == "LB.LBORRES where LBSPEC = BLOOD and LBTESTCD = PT"
    assert A.annotation_key(result.targets[0]) == "LB.LBORRES where LBTESTCD = PT"


def test_enrich_ignores_disagreeing_tested_and_foreign_values():
    pairs = [(_record("IT.SPEC1"), _parse("LBSPEC = BLOOD")),
             (_record("IT.SPEC2"), _parse("LBSPEC = URINE")),
             (_record("IT.METHOD"), _parse("LBMETHOD = DIPSTICK")),
             (_record("IT.POS"), _parse("VSPOS = SITTING")),
             (_record("IT.FAST"), _parse("[NOT SUBMITTED]; LBFAST = Y")),
             (_record("IT.CL", level="codelist-item"), _parse("LBCAT = CHEMISTRY")),
             (_record("IT.RES"), _parse("LBORRES when LBTESTCD = GLUC and LBMETHOD = STRIP"))]

    result = M.enrich(pairs, ["IG.CON.PT"])[-1]

    # LBSPEC has two values, LBMETHOD is already tested, VSPOS is another dataset, and neither a NOT SUBMITTED
    # field nor a codelist item fixes a value
    assert result.targets[0].key == "LB.LBORRES where LBMETHOD = STRIP and LBTESTCD = GLUC"


def test_enrich_needs_a_concept_group_and_another_item():
    pairs = [(_record("IT.SPEC"), _parse("LBSPEC = BLOOD")),
             (_record("IT.RES"), _parse("LBORRES when LBTESTCD = PT"))]
    assert M.enrich(pairs, ["IG.CON.OTHER"])[1] == pairs[1][1]
    # an item's own fixed value is not a condition on its other targets
    own = [(_record("IT.RES"), _parse("LBSPEC = BLOOD; LBORRES when LBTESTCD = PT"))]
    assert M.enrich(own, ["IG.CON.PT"])[0].targets[1].key == "LB.LBORRES where LBTESTCD = PT"


# propose

@pytest.mark.parametrize("text, instruction, origins, expected", [
    ("MHSTRF", RELATIVE, (Origin("Collected", "Investigator"),),
     M.ProposedOrigin("Derived", "Sponsor", "mappingInstructions", M.PLACEHOLDER)),
    ("CMDOSE;CMDOSTXT", SPLIT, (), M.ProposedOrigin("Derived", "Sponsor", "mappingInstructions", M.PLACEHOLDER)),
    ("[NOT SUBMITTED];MHSTRF;MHSTRTPT", None, (Origin("Collected", "Investigator"),),
     M.ProposedOrigin("Derived", "Sponsor", "not_submitted", M.PLACEHOLDER)),
    ("AESTDTC", CONCATENATED, (Origin("Collected", "Investigator"),),
     M.ProposedOrigin("Collected", "Investigator", "ItemRef/Origin", None)),
    ("LBSPEC = BLOOD", DIRECT, (Origin(None, None), Origin("Protocol", "Sponsor")),
     M.ProposedOrigin("Protocol", "Sponsor", "ItemRef/Origin", None)),
    ("AGE", None, (Origin("Derived", None),), M.ProposedOrigin("Derived", M.PLACEHOLDER, "ItemRef/Origin", M.PLACEHOLDER)),
    ("AETERM", None, (), M.ProposedOrigin("Collected", M.PLACEHOLDER, "annotation", None)),
])
def test_propose(text, instruction, origins, expected):
    assert M.propose(_parse(text), M.classify(instruction), origins) == expected


def test_propose_nothing_without_targets():
    assert M.propose(_parse("[NOT SUBMITTED]"), None, (Origin("Collected", "Investigator"),)) is None
    assert M.propose(A.parse("VS", level="group")) is None


# the facts a CRF declares (pagerefs schema 2.1)

def test_a_declared_mapping_type_replaces_the_classified_kind():
    declared = M.instruction([Alias("mappingInstructions", RELATIVE), Alias("SDTMMappingType", "direct")])
    assert (declared.kind, declared.kind_source, declared.variables) == ("direct", "crf", ())
    assert declared.text == A.normalize(RELATIVE)
    prose = M.instruction([Alias("mappingInstructions", SPLIT)])
    assert (prose.kind, prose.kind_source) == ("split", "mappingInstructions")
    alone = M.instruction([Alias("SDTMMappingType", " Relative_Timing ")])
    assert (alone.kind, alone.kind_source, alone.text) == ("relative_timing", "crf", "")
    # an unknown code is ignored, and "other" is never declared
    assert M.instruction([Alias("SDTMMappingType", "other"), Alias("mappingInstructions", DIRECT)]).kind == "direct"
    assert M.instruction([Alias("SDTMMappingType", "sideways")]) is None
    assert M.instruction([]) is None


def test_define_oids():
    pairs = M.define_oids([Alias("SDTMItemOIDs", "VS.VSORRES=IT.VS.VSORRES.SYSBP  VS.VSTESTCD=IT.VS.VSTESTCD junk")])
    assert pairs == {"VS.VSORRES": "IT.VS.VSORRES.SYSBP", "VS.VSTESTCD": "IT.VS.VSTESTCD"}
    assert M.define_oids([Alias("SDTM", "VSORRES")]) is None


def test_pair_define_oids():
    parsed = _parse("VSORRES when VSTESTCD = SYSBP")
    paired, problems = M.pair_define_oids(parsed, {"VS.VSORRES": "IT.VS.VSORRES.SYSBP"})
    assert paired.targets[0].define_item_oid == "IT.VS.VSORRES.SYSBP" and problems == []
    # a SUPP target pairs on its dataset and QVAL
    supp, problems = M.pair_define_oids(_parse("CMINDC in SUPPCM"), {"SUPPCM.QVAL": "IT.SUPPCM.QVAL.CMINDC"})
    assert supp.targets[0].define_item_oid == "IT.SUPPCM.QVAL.CMINDC" and problems == []
    unpaired, problems = M.pair_define_oids(parsed, {"VS.VSSTRESN": "IT.X"})
    assert unpaired.targets[0].define_item_oid is None
    assert problems == ["target VS.VSORRES where VSTESTCD = SYSBP has no SDTMItemOIDs pair",
                        "SDTMItemOIDs pair VS.VSSTRESN=IT.X names no target"]
    # without the alias nothing is paired and nothing is reported
    assert M.pair_define_oids(parsed, None) == (parsed, [])


def test_enrich_keeps_the_define_item_oid():
    record = _record("IT.LB.PT", level="item")
    sibling = _record("IT.LB.LBSPEC", level="item")
    paired, _ = M.pair_define_oids(_parse("LBORRES when LBTESTCD = PT"), {"LB.LBORRES": "IT.LB.LBORRES.PT"})
    enriched = M.enrich([(record, paired), (sibling, _parse("LBSPEC = BLOOD"))], ["IG.CON.PT"])
    assert enriched[0].targets[0].key == "LB.LBORRES where LBSPEC = BLOOD and LBTESTCD = PT"
    assert enriched[0].targets[0].define_item_oid == "IT.LB.LBORRES.PT"


def test_propose_protocol_for_a_concepts_fixed_values():
    fixed = A.parse("VSTESTCD = SYSBP; VSTEST = Systolic Blood Pressure", level="concept", known_domains=KNOWN)
    assert M.propose(fixed, level="concept") == M.ProposedOrigin("Protocol", "Sponsor", "concept", None)
    # a concept annotation with a where clause (vocabulary A) is not a fixed value
    targeted = A.parse("VSORRES when VSTESTCD = SYSBP", level="concept", known_domains=KNOWN)
    assert M.propose(targeted, level="concept").basis == "annotation"
    # the same text on an item keeps the item rules
    assert M.propose(_parse("VSTESTCD = SYSBP")).basis == "annotation"
