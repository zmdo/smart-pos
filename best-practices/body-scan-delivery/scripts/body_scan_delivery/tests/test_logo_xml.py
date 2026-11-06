"""XML-only checks; do not rasterize or process member images."""
import unittest
import xml.etree.ElementTree as ET
from scripts.body_scan_delivery.logo import normalized_svg


class LogoXMLTests(unittest.TestCase):
    def test_illustrator_namespace_entities_and_private_payload(self):
        data=b'''<!DOCTYPE svg [<!ENTITY ns_ai "http://ns.adobe.com/AdobeIllustrator/10.0/">]>
        <svg xmlns="http://www.w3.org/2000/svg" xmlns:i="&ns_ai;" viewBox="0 0 100 100">
          <style>.white{fill:white}</style><switch><foreignObject width="1" height="1"><i:aipgfRef/></foreignObject>
          <g><path class="white" d="M 10 10 H 90 V 90 H 10 Z"/></g></switch><i:aipgf>private payload</i:aipgf></svg>'''
        clean=normalized_svg(data)
        self.assertNotIn(b'ENTITY',clean);self.assertNotIn(b'private payload',clean)
        self.assertNotIn(b'foreignObject',clean)
        root=ET.fromstring(clean)
        self.assertEqual(len(root.findall('.//{http://www.w3.org/2000/svg}path')),1)

    def test_external_nested_and_parameter_entities_are_rejected(self):
        for declaration in ('<!ENTITY ns_ai SYSTEM "file:///etc/passwd">',
                            '<!ENTITY ns_ai "&other;&other;">',
                            '<!ENTITY % ns_ai "http://example.com/">'):
            with self.assertRaisesRegex(ValueError,'unsupported_svg_entity'):
                normalized_svg(('<!DOCTYPE svg ['+declaration+']><svg/>').encode())
