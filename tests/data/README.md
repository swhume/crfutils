# Test data

Every file here is an ODM v2.0 document. All of them are XSD-valid (`tests/test_validate.py`) and load strictly in
odmlib (`tests/test_model.py`). Six are copies of published examples, kept byte-identical to their sources; one
is written for these tests.

| File | Source | License | Exercises |
|---|---|---|---|
| `vital_signs_odmv2-0.xml` | [odmlib_examples](https://github.com/swhume/odmlib_examples) `snippets/data/` | MIT | annotation vocabulary A (`formAnnotation`, `VSORRES when VSTESTCD = SYSBP`); Form > Section > Concept nesting |
| `cdash_demo_v20.xml` | [odmlib](https://github.com/swhume/odmlib) `tests/data/` | MIT | the `FTASTDEV in SUPPFT` annotation form; no form-level domain |
| `Result_ODMv2.xml` | [DataExchange-ODM](https://github.com/cdisc-org/DataExchange-ODM) `examples/Protocol_to_Workflow/` | MIT (c) 2022 cdisc | 7 forms, 5 visits, 11 visit-form links; section `SDTM` aliases and `@Domain` (vocabulary B); CodeListItem aliases; 148 empty TranslatedText; a WorkflowDef |
| `Atlas_QS_ODMv2.xml` | DataExchange-ODM `examples/Atlas_RS/` | MIT (c) 2022 cdisc | ClinicalData (noted, not examined); `RSSTRESN/RSSTRESC where RSTESTCD=ATLAS101` alternatives; a Protocol and StudyEventGroupDef |
| `Columbia-Suicide_Severity_Scale_ODMv2.xml` | DataExchange-ODM `examples/Columbia_Suicidal_Scale/` | MIT (c) 2022 cdisc | 41 groups, sections nested in sections, an ItemGroupRef and ItemRef interleaved without OrderNumbers; no annotations; no ODMVersion attribute; ClinicalData |
| `Demographics_RACE_check_all_that_apply.xml` | DataExchange-ODM `examples/Demographics_RACE/` | MIT (c) 2022 cdisc | three ItemRefs followed by an ItemGroupRef, with no OrderNumbers (odmlib fix O5 keeps that order); ClinicalData |
| `crf_synthetic.xml` | written for crfutils | MIT (crfutils) | see the comment at the top of the file: protocol order opposite to document order, a Common event, an unscheduled form with a slash in its OID, vocabulary B, every annotation form, xhtml TranslatedText, UnitsItemOID, a MethodDef, ConditionDef and AnnotatedCRF Leaf |

`crf-2.0.xml` from data-definition-engine (a 14-form, 394-item CRF) is used only locally, for timing the PDF
rendering and checking the page-references JSON; its repository's license has a placeholder copyright, so it is
not copied here. `crf_synthetic.xml` reproduces the parts of it the JSON reads (ItemRef Origins and
PreSpecifiedValue, mappingInstructions, a prefilled concept sibling, and the SDTMItemOIDs / SDTMMappingType
aliases and Concept fixed values the data-definition-engine declares).

The `golden/` folder holds the crfrefs JSON reports the tests compare against. Regenerate them after a deliberate
change to the report with `CRFUTILS_UPDATE_GOLDEN=1 pytest tests/test_crfrefs.py`.

Generated `.html`, `.pdf` and `.pagerefs.json` files in this folder are ignored by git.
