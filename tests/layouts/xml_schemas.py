"""Kinds of XML schema project, for tests that run a check in every layout: a schema with its documents, and a
stylesheet."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

XSD = """\
<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="catalog">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="item" maxOccurs="unbounded">
          <xs:complexType>
            <xs:attribute name="name" type="xs:string" use="required"/>
            <xs:attribute name="price" type="xs:nonNegativeInteger" use="required"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""
CATALOG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<catalog>\n  <item name="apple" price="1"/>\n'
    '  <item name="pear" price="2"/>\n</catalog>\n'
)
XSL = """\
<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="3.0">
  <xsl:output method="text"/>
  <xsl:template match="/catalog">
    <xsl:value-of select="sum(item/@price)"/>
  </xsl:template>
</xsl:stylesheet>
"""

LAYOUTS = (
    ProjectLayout(
        name="XML Schema",
        files={"schema/catalog.xsd": XSD, "data/catalog.xml": CATALOG},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"XML Schema", "XML"}),
    ),
    ProjectLayout(
        name="XSLT stylesheet",
        files={"xslt/total.xsl": XSL},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"XSLT", "XML"}),
    ),
)
