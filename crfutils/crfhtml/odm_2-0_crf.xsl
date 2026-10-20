<?xml version="1.0" encoding="UTF-8"?>
<!--
  crfutils rendering of a CDISC ODM v2.0 CRF (blank or annotated) as HTML.

  A reworked copy of Lex Jansen's odm_2-0_transform.xsl (cdisc360i-pocs, MIT; see odm_2-0_crf.xsl.LICENSE).
  Every edit is logged in stylesheet_changes.md at the repository root.

  XSLT 1.0 only: it runs under lxml/libxslt (crfhtml) and under Saxon. The stylesheet emits data-* attributes
  but no ids: crfhtml assigns the ids (F.<form>, A.<n>) and the TOC/matrix hrefs in Python, because
  generate-id() is not stable across processors. The elements, classes and data-* attributes are a contract
  with crfpdf (see CRF_UTILS_PLAN.md section 5).

  Parameters (integers are 0/1; strings are passed through XSLT.strparam):
    displayAnnotations    1 shows the SDTM annotations; 0 renders a blank CRF
    displayDataTypeLength 1 shows each item's DataType and Length
    displayToc            1 renders the table of contents
    displayVisitMatrix    1 renders the visit matrix (the caller passes 0 when there is no schedule)
    displayTitlePage      1 renders the title page (print mode)
    maxCodeListItems      in print mode, a codelist with more items than this is rendered as a text field that
                          names the codelist instead of listing every item (a units list can run to hundreds)
    mode                  'screen' (interactive controls, embedded style) or 'print' (static controls, no style)
    formOrder             ' OID1 OID2 ' - the forms in display order, each OID surrounded by spaces; '' keeps
                          document order
    visitOrder            the StudyEventDefs in schedule order, in the same form
    docTitle              the document title; '' uses the StudyName
    generatedOn           a timestamp for the footer and title page; '' omits them
    crfutilsVersion       the crfutils version for the footer and title page
-->
<xsl:stylesheet
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:odm="http://www.cdisc.org/ns/odm/v2.0"
    version="1.0"
    exclude-result-prefixes="odm">
    <xsl:output method="html" encoding="UTF-8" version="5" indent="yes"/>

    <xsl:param name="displayAnnotations" select="1"/>
    <xsl:param name="displayDataTypeLength" select="0"/>
    <xsl:param name="displayToc" select="1"/>
    <xsl:param name="displayVisitMatrix" select="1"/>
    <xsl:param name="displayTitlePage" select="0"/>
    <xsl:param name="maxCodeListItems" select="20"/>
    <xsl:param name="mode" select="'screen'"/>
    <xsl:param name="formOrder" select="''"/>
    <xsl:param name="visitOrder" select="''"/>
    <xsl:param name="docTitle" select="''"/>
    <xsl:param name="generatedOn" select="''"/>
    <xsl:param name="crfutilsVersion" select="''"/>

    <!-- the rendered document is the first Study's first MetaDataVersion -->
    <xsl:variable name="study" select="/odm:ODM/odm:Study[1]"/>
    <xsl:variable name="mdv" select="/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]"/>
    <xsl:variable name="print" select="$mode = 'print'"/>
    <xsl:variable name="annotate" select="$displayAnnotations = 1"/>
    <!-- the nesting depth at which group recursion stops; the same cap as _design.MAX_DEPTH -->
    <xsl:variable name="maxDepth" select="10"/>

    <!-- OID lookups, anchored at the rendered MetaDataVersion (a key pattern cannot use a variable) -->
    <xsl:key name="igd" match="/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]/odm:ItemGroupDef" use="@OID"/>
    <xsl:key name="itd" match="/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]/odm:ItemDef" use="@OID"/>
    <xsl:key name="cl" match="/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]/odm:CodeList" use="@OID"/>
    <xsl:key name="sed" match="/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]/odm:StudyEventDef" use="@OID"/>

    <xsl:variable name="title">
        <xsl:choose>
            <xsl:when test="$docTitle != ''"><xsl:value-of select="$docTitle"/></xsl:when>
            <xsl:when test="$study/@StudyName"><xsl:value-of select="$study/@StudyName"/></xsl:when>
            <xsl:otherwise><xsl:value-of select="$mdv/odm:ItemGroupDef[@Type='Form'][1]/@Name"/></xsl:otherwise>
        </xsl:choose>
    </xsl:variable>

    <!-- ============================================================================================ -->
    <!-- the document                                                                                 -->
    <!-- ============================================================================================ -->
    <xsl:template match="/">
        <html lang="en">
            <head>
                <meta charset="utf-8"/>
                <title><xsl:value-of select="$title"/></title>
                <xsl:if test="not($print)">
                    <xsl:call-template name="screen-style"/>
                </xsl:if>
            </head>
            <body class="mode-{$mode}">
                <xsl:choose>
                    <xsl:when test="$print and $displayTitlePage = 1">
                        <xsl:call-template name="title-page"/>
                    </xsl:when>
                    <xsl:otherwise>
                        <header class="doc-header">
                            <h1 class="doc-title"><xsl:value-of select="$title"/></h1>
                            <p class="doc-meta">
                                <span class="doc-study"><xsl:value-of select="$study/@StudyName"/></span>
                                <xsl:if test="$study/@ProtocolName">
                                    <xsl:text> - Protocol: </xsl:text>
                                    <span class="doc-protocol"><xsl:value-of select="$study/@ProtocolName"/></span>
                                </xsl:if>
                                <xsl:if test="$mdv/@Name">
                                    <xsl:text> - </xsl:text>
                                    <span class="doc-mdv"><xsl:value-of select="$mdv/@Name"/></span>
                                </xsl:if>
                            </p>
                        </header>
                    </xsl:otherwise>
                </xsl:choose>
                <xsl:if test="$displayToc = 1">
                    <xsl:call-template name="toc"/>
                </xsl:if>
                <xsl:if test="$displayVisitMatrix = 1">
                    <xsl:call-template name="visit-matrix"/>
                </xsl:if>
                <xsl:for-each select="$mdv/odm:ItemGroupDef[@Type='Form']">
                    <xsl:sort data-type="number" select="string-length(substring-before($formOrder, concat(' ', @OID, ' ')))"/>
                    <xsl:call-template name="form"/>
                </xsl:for-each>
                <xsl:if test="$generatedOn != ''">
                    <footer class="doc-footer">
                        <xsl:text>Generated by crfutils </xsl:text>
                        <xsl:value-of select="$crfutilsVersion"/>
                        <xsl:text> on </xsl:text>
                        <xsl:value-of select="$generatedOn"/>
                    </footer>
                </xsl:if>
            </body>
        </html>
    </xsl:template>

    <!-- the print title page; the doc-study span sets the running string the page footers show -->
    <xsl:template name="title-page">
        <section class="title-page">
            <h1 class="doc-title"><xsl:value-of select="$title"/></h1>
            <table class="title-meta">
                <tr><th>Study</th><td><span class="doc-study"><xsl:value-of select="$study/@StudyName"/></span></td></tr>
                <tr><th>Protocol</th><td><xsl:value-of select="$study/@ProtocolName"/></td></tr>
                <xsl:if test="$study/odm:Description/odm:TranslatedText">
                    <tr><th>Study description</th><td><xsl:value-of select="$study/odm:Description/odm:TranslatedText[1]"/></td></tr>
                </xsl:if>
                <tr><th>Metadata version</th><td><xsl:value-of select="$mdv/@Name"/> (<xsl:value-of select="$mdv/@OID"/>)</td></tr>
                <xsl:if test="$mdv/odm:Description/odm:TranslatedText">
                    <tr><th>Description</th><td><xsl:value-of select="$mdv/odm:Description/odm:TranslatedText[1]"/></td></tr>
                </xsl:if>
                <tr><th>Forms</th><td><xsl:value-of select="count($mdv/odm:ItemGroupDef[@Type='Form'])"/></td></tr>
                <xsl:if test="$generatedOn != ''">
                    <tr><th>Generated</th><td><xsl:value-of select="$generatedOn"/> by crfutils <xsl:value-of select="$crfutilsVersion"/></td></tr>
                </xsl:if>
            </table>
        </section>
    </xsl:template>

    <!-- the table of contents: one link per form; crfhtml sets each href -->
    <xsl:template name="toc">
        <nav class="toc">
            <h2 class="toc-title">Table of Contents</h2>
            <ol class="toc-list">
                <xsl:for-each select="$mdv/odm:ItemGroupDef[@Type='Form']">
                    <xsl:sort data-type="number" select="string-length(substring-before($formOrder, concat(' ', @OID, ' ')))"/>
                    <li><a class="toc-link" data-form-oid="{@OID}"><xsl:value-of select="@Name"/></a></li>
                </xsl:for-each>
            </ol>
        </nav>
    </xsl:template>

    <!-- the visit matrix: forms by visit; X collected, (X) collected but not mandatory -->
    <xsl:template name="visit-matrix">
        <section class="visit-matrix">
            <h2 class="matrix-title">Visit Matrix</h2>
            <table class="matrix">
                <thead>
                    <tr>
                        <th class="matrix-form">Form</th>
                        <xsl:for-each select="$mdv/odm:StudyEventDef">
                            <xsl:sort data-type="number" select="string-length(substring-before($visitOrder, concat(' ', @OID, ' ')))"/>
                            <th class="matrix-visit" data-visit-oid="{@OID}"><xsl:value-of select="@Name"/></th>
                        </xsl:for-each>
                    </tr>
                </thead>
                <tbody>
                    <xsl:for-each select="$mdv/odm:ItemGroupDef[@Type='Form']">
                        <xsl:sort data-type="number" select="string-length(substring-before($formOrder, concat(' ', @OID, ' ')))"/>
                        <xsl:variable name="formOID" select="@OID"/>
                        <tr>
                            <th class="matrix-form" scope="row"><a class="matrix-link" data-form-oid="{@OID}"><xsl:value-of select="@Name"/></a></th>
                            <xsl:for-each select="$mdv/odm:StudyEventDef">
                                <xsl:sort data-type="number" select="string-length(substring-before($visitOrder, concat(' ', @OID, ' ')))"/>
                                <xsl:variable name="ref" select="odm:ItemGroupRef[@ItemGroupOID = $formOID][1]"/>
                                <td class="matrix-cell">
                                    <xsl:choose>
                                        <xsl:when test="$ref/@Mandatory = 'No'">(X)</xsl:when>
                                        <xsl:when test="$ref">X</xsl:when>
                                    </xsl:choose>
                                </td>
                            </xsl:for-each>
                        </tr>
                    </xsl:for-each>
                </tbody>
            </table>
        </section>
    </xsl:template>

    <!-- ============================================================================================ -->
    <!-- a form: one table, with a heading row per nested group                                       -->
    <!-- ============================================================================================ -->
    <xsl:template name="form">
        <section class="form" data-form-oid="{@OID}" data-form-name="{@Name}">
            <h2 class="form-title"><xsl:value-of select="@Name"/></h2>
            <xsl:if test="$annotate">
                <div class="form-annotations">
                    <xsl:call-template name="group-annotations">
                        <xsl:with-param name="level" select="'form'"/>
                        <xsl:with-param name="formOID" select="@OID"/>
                        <xsl:with-param name="groupPath" select="@OID"/>
                    </xsl:call-template>
                </div>
            </xsl:if>
            <xsl:call-template name="group-notes"/>
            <table class="crf">
                <thead>
                    <tr>
                        <th class="col-question">Question</th>
                        <th class="col-response">Response</th>
                        <xsl:if test="$annotate">
                            <th class="col-anno">SDTM annotation</th>
                        </xsl:if>
                    </tr>
                </thead>
                <tbody>
                    <xsl:call-template name="group-rows">
                        <xsl:with-param name="group" select="."/>
                        <xsl:with-param name="formOID" select="@OID"/>
                        <xsl:with-param name="groupPath" select="@OID"/>
                        <xsl:with-param name="depth" select="0"/>
                    </xsl:call-template>
                </tbody>
            </table>
            <div class="footnote"><span class="mandatory">*</span> Mandatory field</div>
        </section>
    </xsl:template>

    <!-- a group's description and completion instructions (vocabularies A and B) -->
    <xsl:template name="group-notes">
        <xsl:if test="odm:Description/odm:TranslatedText">
            <p class="description"><xsl:value-of select="odm:Description/odm:TranslatedText[1]"/></p>
        </xsl:if>
        <xsl:for-each select="odm:Alias[@Context='formSectionCompletionInstruction' or @Context='completionInstructions']">
            <p class="instruction"><xsl:value-of select="@Name"/></p>
        </xsl:for-each>
    </xsl:template>

    <!--
      the annotations of the context group, by level: a form's formAnnotation or SDTM aliases, a section's
      formSectionAnnotation or SDTM aliases, a concept's SDTM aliases; a form or section with none shows
      its @Domain. _design.StudyDesign.group_annotations reads the same rule
    -->
    <xsl:template name="group-annotations">
        <xsl:param name="level"/>
        <xsl:param name="formOID"/>
        <xsl:param name="groupPath"/>
        <xsl:variable name="aliases" select="odm:Alias[($level = 'form' and (@Context = 'formAnnotation' or @Context = 'SDTM'))
                                                       or ($level = 'section' and (@Context = 'formSectionAnnotation' or @Context = 'SDTM'))
                                                       or ($level = 'concept' and @Context = 'SDTM')]"/>
        <xsl:for-each select="$aliases">
            <span class="anno anno-{$level}" data-level="{$level}" data-source="alias:{@Context}" data-text="{@Name}"
                  data-form-oid="{$formOID}" data-group-path="{$groupPath}"><xsl:value-of select="@Name"/></span>
        </xsl:for-each>
        <xsl:if test="not($aliases) and $level != 'concept' and @Domain">
            <span class="anno anno-{$level}" data-level="{$level}" data-source="attr:Domain" data-text="{@Domain}"
                  data-form-oid="{$formOID}" data-group-path="{$groupPath}"><xsl:value-of select="@Domain"/></span>
        </xsl:if>
    </xsl:template>

    <!-- the level of a group, from its Type -->
    <xsl:template name="group-level">
        <xsl:choose>
            <xsl:when test="@Type = 'Form'">form</xsl:when>
            <xsl:when test="@Type = 'Concept'">concept</xsl:when>
            <xsl:otherwise>section</xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <!--
      the rows of a group: its ItemRef and ItemGroupRef children in OrderNumber order (children without one
      first, then document order, as XSLT's stable number sort gives). A nested group adds a heading row and
      then its own rows; a group that is already on the path (a cycle), or nested deeper than $maxDepth, gets
      an error row and is not entered. _design.StudyDesign.walk produces the same rows
    -->
    <xsl:template name="group-rows">
        <xsl:param name="group"/>
        <xsl:param name="formOID"/>
        <xsl:param name="groupPath"/>
        <xsl:param name="depth"/>
        <xsl:for-each select="$group/odm:ItemRef | $group/odm:ItemGroupRef">
            <xsl:sort select="@OrderNumber" data-type="number"/>
            <xsl:choose>
                <xsl:when test="self::odm:ItemRef">
                    <xsl:call-template name="item-row">
                        <xsl:with-param name="formOID" select="$formOID"/>
                        <xsl:with-param name="groupPath" select="$groupPath"/>
                        <xsl:with-param name="depth" select="$depth"/>
                    </xsl:call-template>
                </xsl:when>
                <xsl:otherwise>
                    <xsl:variable name="childOID" select="@ItemGroupOID"/>
                    <xsl:variable name="child" select="key('igd', $childOID)"/>
                    <xsl:variable name="childPath" select="concat($groupPath, ' > ', $childOID)"/>
                    <xsl:variable name="cycle" select="contains(concat(' > ', $groupPath, ' > '), concat(' > ', $childOID, ' > '))"/>
                    <xsl:variable name="level">
                        <xsl:for-each select="$child"><xsl:call-template name="group-level"/></xsl:for-each>
                    </xsl:variable>
                    <tr data-group-oid="{$childOID}">
                        <xsl:attribute name="class">
                            <xsl:text>group-head</xsl:text>
                            <xsl:if test="$child"><xsl:value-of select="concat(' type-', $child/@Type)"/></xsl:if>
                            <xsl:value-of select="concat(' depth-', $depth + 1)"/>
                            <xsl:if test="not($child)"> missing</xsl:if>
                            <xsl:if test="$cycle"> cycle</xsl:if>
                            <xsl:if test="$depth >= $maxDepth"> too-deep</xsl:if>
                        </xsl:attribute>
                        <td class="group-name">
                            <xsl:attribute name="colspan">
                                <xsl:choose>
                                    <xsl:when test="$annotate">2</xsl:when>
                                    <xsl:otherwise>3</xsl:otherwise>
                                </xsl:choose>
                            </xsl:attribute>
                            <xsl:choose>
                                <xsl:when test="not($child)">
                                    <span class="group-title missing">ItemGroupDef <xsl:value-of select="$childOID"/> is not defined</span>
                                </xsl:when>
                                <xsl:when test="$cycle">
                                    <span class="group-title missing">ItemGroupDef <xsl:value-of select="$childOID"/> contains itself</span>
                                </xsl:when>
                                <xsl:when test="$depth >= $maxDepth">
                                    <span class="group-title missing">ItemGroupDef <xsl:value-of select="$childOID"/> is nested too deeply to render</span>
                                </xsl:when>
                                <xsl:otherwise>
                                    <span class="group-title"><xsl:value-of select="$child/@Name"/></span>
                                    <xsl:for-each select="$child"><xsl:call-template name="group-notes"/></xsl:for-each>
                                </xsl:otherwise>
                            </xsl:choose>
                        </td>
                        <xsl:if test="$annotate">
                            <td class="anno-cell">
                                <xsl:for-each select="$child">
                                    <xsl:call-template name="group-annotations">
                                        <xsl:with-param name="level" select="string($level)"/>
                                        <xsl:with-param name="formOID" select="$formOID"/>
                                        <xsl:with-param name="groupPath" select="$childPath"/>
                                    </xsl:call-template>
                                </xsl:for-each>
                            </td>
                        </xsl:if>
                    </tr>
                    <xsl:if test="$child and not($cycle) and $depth &lt; $maxDepth">
                        <xsl:call-template name="group-rows">
                            <xsl:with-param name="group" select="$child"/>
                            <xsl:with-param name="formOID" select="$formOID"/>
                            <xsl:with-param name="groupPath" select="$childPath"/>
                            <xsl:with-param name="depth" select="$depth + 1"/>
                        </xsl:call-template>
                    </xsl:if>
                </xsl:otherwise>
            </xsl:choose>
        </xsl:for-each>
    </xsl:template>

    <!-- ============================================================================================ -->
    <!-- an item row: question, response control, annotations                                        -->
    <!-- ============================================================================================ -->
    <xsl:template name="item-row">
        <xsl:param name="formOID"/>
        <xsl:param name="groupPath"/>
        <xsl:param name="depth"/>
        <xsl:variable name="item" select="key('itd', @ItemOID)"/>
        <tr class="item depth-{$depth}" data-item-oid="{@ItemOID}" data-group-path="{$groupPath}">
            <td class="question">
                <xsl:if test="@Mandatory = 'Yes'">
                    <span class="mandatory">* </span>
                </xsl:if>
                <xsl:choose>
                    <xsl:when test="not($item)">
                        <span class="missing">ItemDef <xsl:value-of select="@ItemOID"/> is not defined</span>
                    </xsl:when>
                    <xsl:when test="$item/odm:Prompt/odm:TranslatedText">
                        <span class="question-text"><xsl:value-of select="$item/odm:Prompt/odm:TranslatedText[1]"/></span>
                    </xsl:when>
                    <xsl:when test="$item/odm:Question/odm:TranslatedText">
                        <span class="question-text"><xsl:value-of select="$item/odm:Question/odm:TranslatedText[1]"/></span>
                    </xsl:when>
                    <xsl:otherwise>
                        <span class="question-text"><xsl:value-of select="$item/@Name"/></span>
                    </xsl:otherwise>
                </xsl:choose>
                <xsl:if test="$item/odm:CRFCompletionInstructions/odm:TranslatedText">
                    <div class="instruction"><xsl:value-of select="$item/odm:CRFCompletionInstructions/odm:TranslatedText[1]"/></div>
                </xsl:if>
                <xsl:if test="$displayDataTypeLength = 1 and $item">
                    <div class="type">
                        <xsl:value-of select="$item/@DataType"/>
                        <xsl:if test="$item/@Length"> (<xsl:value-of select="$item/@Length"/>)</xsl:if>
                    </div>
                </xsl:if>
            </td>
            <td class="response">
                <xsl:if test="$item">
                    <xsl:call-template name="control">
                        <xsl:with-param name="item" select="$item"/>
                        <xsl:with-param name="formOID" select="$formOID"/>
                        <xsl:with-param name="groupPath" select="$groupPath"/>
                    </xsl:call-template>
                </xsl:if>
            </td>
            <xsl:if test="$annotate">
                <td class="anno-cell">
                    <xsl:for-each select="$item/odm:Alias[@Context = 'SDTM']">
                        <span class="anno anno-item" data-level="item" data-source="alias:SDTM" data-text="{@Name}"
                              data-form-oid="{$formOID}" data-group-path="{$groupPath}" data-item-oid="{$item/@OID}"><xsl:value-of select="@Name"/></span>
                    </xsl:for-each>
                    <xsl:variable name="codelist" select="key('cl', $item/odm:CodeListRef/@CodeListOID)"/>
                    <xsl:if test="$item/odm:CodeListRef and (not($print) or count($codelist/odm:CodeListItem) > $maxCodeListItems)">
                        <!-- on screen, and in print when the codelist is too long to list, the codelist item
                             annotations are listed here; otherwise in print they sit beside each option -->
                        <xsl:for-each select="$codelist/odm:CodeListItem[odm:Alias[@Context = 'SDTM']]">
                            <div class="option-anno">
                                <span class="coded-value"><xsl:value-of select="@CodedValue"/>: </span>
                                <xsl:call-template name="codelist-item-annotations">
                                    <xsl:with-param name="item" select="$item"/>
                                    <xsl:with-param name="formOID" select="$formOID"/>
                                    <xsl:with-param name="groupPath" select="$groupPath"/>
                                </xsl:call-template>
                            </div>
                        </xsl:for-each>
                    </xsl:if>
                </td>
            </xsl:if>
        </tr>
    </xsl:template>

    <!-- the SDTM annotations of the context CodeListItem -->
    <xsl:template name="codelist-item-annotations">
        <xsl:param name="item"/>
        <xsl:param name="formOID"/>
        <xsl:param name="groupPath"/>
        <xsl:for-each select="odm:Alias[@Context = 'SDTM']">
            <span class="anno anno-codelist-item" data-level="codelist-item" data-source="alias:SDTM" data-text="{@Name}"
                  data-form-oid="{$formOID}" data-group-path="{$groupPath}" data-item-oid="{$item/@OID}"
                  data-codelist-oid="{../../@OID}" data-coded-value="{../@CodedValue}"><xsl:value-of select="@Name"/></span>
        </xsl:for-each>
    </xsl:template>

    <!--
      the response control of an item. Screen mode renders interactive controls; print mode renders static
      boxes and fields, and lists every codelist item, since a PDF of a dropdown would show one option
    -->
    <xsl:template name="control">
        <xsl:param name="item"/>
        <xsl:param name="formOID"/>
        <xsl:param name="groupPath"/>
        <xsl:choose>
            <xsl:when test="@PreSpecifiedValue">
                <xsl:choose>
                    <xsl:when test="$print"><span class="field prespecified"><xsl:value-of select="@PreSpecifiedValue"/></span></xsl:when>
                    <xsl:otherwise><input type="text" name="{$item/@OID}" value="{@PreSpecifiedValue}" class="prespecified" readonly="readonly"/></xsl:otherwise>
                </xsl:choose>
            </xsl:when>
            <xsl:when test="$item/odm:CodeListRef">
                <xsl:call-template name="codelist-control">
                    <xsl:with-param name="item" select="$item"/>
                    <xsl:with-param name="formOID" select="$formOID"/>
                    <xsl:with-param name="groupPath" select="$groupPath"/>
                </xsl:call-template>
            </xsl:when>
            <xsl:when test="$item/@DataType = 'date' or $item/@DataType = 'partialDate' or $item/@DataType = 'incompleteDate'">
                <xsl:choose>
                    <xsl:when test="$print"><span class="field date">DD / MMM / YYYY</span></xsl:when>
                    <xsl:otherwise><input type="date" name="{$item/@OID}"/></xsl:otherwise>
                </xsl:choose>
            </xsl:when>
            <xsl:when test="$item/@DataType = 'datetime' or $item/@DataType = 'partialDatetime' or $item/@DataType = 'incompleteDatetime'">
                <xsl:choose>
                    <xsl:when test="$print"><span class="field datetime">DD / MMM / YYYY  HH : MM</span></xsl:when>
                    <xsl:otherwise><input type="datetime-local" name="{$item/@OID}"/></xsl:otherwise>
                </xsl:choose>
            </xsl:when>
            <xsl:when test="$item/@DataType = 'time' or $item/@DataType = 'partialTime' or $item/@DataType = 'incompleteTime'">
                <xsl:choose>
                    <xsl:when test="$print"><span class="field time">HH : MM</span></xsl:when>
                    <xsl:otherwise><input type="time" name="{$item/@OID}"/></xsl:otherwise>
                </xsl:choose>
            </xsl:when>
            <xsl:when test="$item/@DataType = 'integer' or $item/@DataType = 'float' or $item/@DataType = 'decimal' or $item/@DataType = 'double'">
                <xsl:choose>
                    <xsl:when test="$print"><span class="field number"></span></xsl:when>
                    <xsl:otherwise><input type="number" name="{$item/@OID}"/></xsl:otherwise>
                </xsl:choose>
            </xsl:when>
            <xsl:when test="$item/@DataType = 'boolean'">
                <xsl:choose>
                    <xsl:when test="$print">
                        <label class="option"><span class="box"></span><span class="decode">Yes</span></label>
                        <label class="option"><span class="box"></span><span class="decode">No</span></label>
                    </xsl:when>
                    <xsl:otherwise>
                        <label class="option"><input type="radio" name="{$item/@OID}" value="true"/><span class="decode">Yes</span></label>
                        <label class="option"><input type="radio" name="{$item/@OID}" value="false"/><span class="decode">No</span></label>
                    </xsl:otherwise>
                </xsl:choose>
            </xsl:when>
            <xsl:otherwise>
                <xsl:choose>
                    <xsl:when test="$print"><span class="field text"></span></xsl:when>
                    <xsl:otherwise>
                        <input type="text" name="{$item/@OID}">
                            <xsl:if test="$item/@Length"><xsl:attribute name="maxlength"><xsl:value-of select="$item/@Length"/></xsl:attribute></xsl:if>
                        </input>
                    </xsl:otherwise>
                </xsl:choose>
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <!-- a coded item: radios for two options or fewer, a select for more; every option with a box in print -->
    <xsl:template name="codelist-control">
        <xsl:param name="item"/>
        <xsl:param name="formOID"/>
        <xsl:param name="groupPath"/>
        <xsl:variable name="codelist" select="key('cl', $item/odm:CodeListRef/@CodeListOID)"/>
        <xsl:variable name="count" select="count($codelist/odm:CodeListItem)"/>
        <xsl:choose>
            <xsl:when test="not($codelist)">
                <span class="missing">CodeList <xsl:value-of select="$item/odm:CodeListRef/@CodeListOID"/> is not defined</span>
            </xsl:when>
            <xsl:when test="$print and $count > $maxCodeListItems">
                <!-- a codelist too long to list (units, countries): a field, and the codelist named beneath it -->
                <span class="field text"></span>
                <div class="codelist-note">Select from <xsl:value-of select="$codelist/@Name"/> (<xsl:value-of select="$count"/> terms)</div>
            </xsl:when>
            <xsl:when test="$print or $count &lt;= 2">
                <xsl:for-each select="$codelist/odm:CodeListItem">
                    <label class="option">
                        <xsl:choose>
                            <xsl:when test="$print"><span class="box"></span></xsl:when>
                            <xsl:otherwise><input type="radio" name="{$item/@OID}" value="{@CodedValue}"/></xsl:otherwise>
                        </xsl:choose>
                        <span class="decode">
                            <xsl:choose>
                                <xsl:when test="odm:Decode/odm:TranslatedText"><xsl:value-of select="odm:Decode/odm:TranslatedText[1]"/></xsl:when>
                                <xsl:otherwise><xsl:value-of select="@CodedValue"/></xsl:otherwise>
                            </xsl:choose>
                        </span>
                        <xsl:if test="$print and $annotate">
                            <xsl:call-template name="codelist-item-annotations">
                                <xsl:with-param name="item" select="$item"/>
                                <xsl:with-param name="formOID" select="$formOID"/>
                                <xsl:with-param name="groupPath" select="$groupPath"/>
                            </xsl:call-template>
                        </xsl:if>
                    </label>
                </xsl:for-each>
            </xsl:when>
            <xsl:otherwise>
                <select name="{$item/@OID}">
                    <option value="">-- Select --</option>
                    <xsl:for-each select="$codelist/odm:CodeListItem">
                        <option value="{@CodedValue}">
                            <xsl:choose>
                                <xsl:when test="odm:Decode/odm:TranslatedText"><xsl:value-of select="odm:Decode/odm:TranslatedText[1]"/></xsl:when>
                                <xsl:otherwise><xsl:value-of select="@CodedValue"/></xsl:otherwise>
                            </xsl:choose>
                        </option>
                    </xsl:for-each>
                </select>
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <!-- ============================================================================================ -->
    <!-- the screen style; print mode gets crfpdf/acrf.css from crfpdf instead                        -->
    <!-- ============================================================================================ -->
    <xsl:template name="screen-style">
        <style>
            body { font-family: Arial, Helvetica, sans-serif; margin: 20px; background-color: #f5f5f5; color: #222; }
            .doc-header, .toc, .visit-matrix, .form { max-width: 1200px; margin: 0 auto 20px auto; background: white; padding: 16px 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1.doc-title { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; margin: 0 0 8px 0; }
            .doc-meta { color: #555; margin: 0; }
            h2 { color: #34495e; margin: 0 0 10px 0; background: #ecf0f1; padding: 10px; border-left: 4px solid #3498db; }
            .toc-list { columns: 2; }
            .toc-list a, .matrix-link { color: #2980b9; text-decoration: none; }
            .toc-list a:hover, .matrix-link:hover { text-decoration: underline; }
            table { width: 100%; border-collapse: collapse; margin: 10px 0; }
            th, td { padding: 6px 10px; text-align: left; border: 1px solid #bdc3c7; vertical-align: top; }
            thead th { background-color: #3498db; color: white; font-weight: bold; }
            tr.item:nth-child(even) { background-color: #f8f9fa; }
            .crf .col-question { width: 35%; }
            .crf .col-response { width: 35%; }
            .crf .col-anno { width: 30%; }
            tr.group-head td, tr.group-head th { background: #ecf0f1; font-weight: bold; color: #2c3e50; }
            tr.group-head.type-Concept td { background: #f7f9fa; color: #2980b9; }
            tr.group-head.depth-2 .group-title { padding-left: 1em; }
            tr.group-head.depth-3 .group-title { padding-left: 2em; }
            tr.group-head.depth-4 .group-title { padding-left: 3em; }
            tr.group-head.missing td, tr.group-head.cycle td, tr.group-head.too-deep td, .missing { color: #c0392b; }
            .description, .instruction { font-weight: normal; font-size: 0.9em; color: #555; margin: 4px 0 0 0; white-space: pre-wrap; }
            .type { font-size: 0.85em; color: #7f8c8d; font-style: italic; }
            input[type="text"], input[type="date"], input[type="datetime-local"], input[type="time"], input[type="number"], select {
                width: 250px; max-width: 100%; padding: 5px; border: 1px solid #bdc3c7; border-radius: 3px; font-size: 14px; }
            input:focus, select:focus { outline: none; border-color: #3498db; box-shadow: 0 0 5px rgba(52, 152, 219, 0.3); }
            .prespecified { background-color: #e8f5e8; font-weight: bold; }
            label.option { display: block; }
            .mandatory { color: #e74c3c; }
            .footnote { font-size: 8pt; color: #555; }
            .anno { display: inline-block; background-color: LightYellow; border: 1px solid #ccc; padding: 2px 5px; margin: 1px 4px 1px 0; font-size: 0.9em; }
            .anno-form, .anno-section { font-weight: bold; }
            .option-anno { font-size: 0.9em; }
            .coded-value { color: #555; }
            .matrix th.matrix-visit { font-weight: normal; }
            .matrix-cell { text-align: center; }
            .doc-footer { max-width: 1200px; margin: 0 auto; color: #7f8c8d; font-size: 0.85em; }
            @media print {
                body { background: white; margin: 0; }
                .doc-header, .toc, .visit-matrix, .form { box-shadow: none; border-radius: 0; padding: 0; max-width: none; }
                .form { page-break-before: always; break-before: page; }
                tr { page-break-inside: avoid; break-inside: avoid; }
                thead { display: table-header-group; }
            }
        </style>
    </xsl:template>

</xsl:stylesheet>
