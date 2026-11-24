"""Hidden acceptance tests for issue I2 (abbr: load_glossary() does not override existing entries).

This is a real bug at commit 3f2c551 (not injected): the docstring of AbbrExtension.load_glossary
says that existing abbreviations are overwritten, but once the extension has been loaded the old
glossary entries win. A naive fix (swapping the dict merge order) breaks the existing test
test_abbr_glossary_2, so a correct fix also has to keep that behaviour.
"""
import unittest

import markdown
from markdown.extensions.abbr import AbbrExtension


class TestI2Hidden(unittest.TestCase):

    def test_load_glossary_after_loading_overrides_existing_entry(self):
        ext = AbbrExtension(glossary={'HTML': 'Old title', 'CSS': 'Cascading Style Sheets'})
        md = markdown.Markdown(extensions=[ext])
        ext.load_glossary({'HTML': 'Hyper Text Markup Language'})
        md.reset()
        self.assertEqual(
            md.convert('HTML and CSS'),
            '<p><abbr title="Hyper Text Markup Language">HTML</abbr> and '
            '<abbr title="Cascading Style Sheets">CSS</abbr></p>'
        )

    def test_load_glossary_before_loading_still_wins_over_config(self):
        ext = AbbrExtension(glossary={'ABBR': 'Abbreviation', 'W3C': 'World Wide Web Consortium'})
        ext.load_glossary({'ABBR': 'New Abbreviation'})
        html = markdown.markdown('ABBR W3C', extensions=[ext])
        self.assertEqual(
            html,
            '<p><abbr title="New Abbreviation">ABBR</abbr> '
            '<abbr title="World Wide Web Consortium">W3C</abbr></p>'
        )

    def test_second_load_glossary_call_overrides_first(self):
        ext = AbbrExtension()
        md = markdown.Markdown(extensions=[ext])
        ext.load_glossary({'API': 'First'})
        ext.load_glossary({'API': 'Second'})
        md.reset()
        self.assertEqual(md.convert('API'), '<p><abbr title="Second">API</abbr></p>')

    def test_document_definition_still_beats_glossary_and_reset_restores_it(self):
        ext = AbbrExtension(glossary={'HTML': 'Glossary title'})
        md = markdown.Markdown(extensions=[ext])
        self.assertEqual(
            md.convert('*[HTML]: Document title\n\nHTML'),
            '<p><abbr title="Document title">HTML</abbr></p>'
        )
        md.reset()
        self.assertEqual(md.convert('HTML'), '<p><abbr title="Glossary title">HTML</abbr></p>')


if __name__ == '__main__':
    unittest.main()
