"""Hidden acceptance tests for issue I1 (TOC text lost around footnote references). Reused from A2 task T1."""
import unittest

import markdown


def toc_tokens(src, extensions=('toc', 'footnotes')):
    md = markdown.Markdown(extensions=list(extensions))
    md.convert(src)
    return md, md.toc_tokens


class TestI1Hidden(unittest.TestCase):

    def test_text_between_markup_and_footnote_is_kept(self):
        md, tokens = toc_tokens('# *Gamma* x[^1] y\n\n[^1]: note\n')
        self.assertEqual(tokens[0]['name'], 'Gamma x y')
        self.assertEqual(tokens[0]['id'], 'gamma-x-y')

    def test_heading_id_in_output_is_complete(self):
        html = markdown.markdown(
            '## Alpha **bold** mid[^1] end\n\n[^1]: note\n',
            extensions=['toc', 'footnotes']
        )
        self.assertIn('<h2 id="alpha-bold-mid-end">', html)

    def test_toc_html_with_several_footnotes(self):
        md, tokens = toc_tokens(
            '# A *b* c[^1] d `e` f[^2] g\n\n[^1]: one\n[^2]: two\n'
        )
        self.assertEqual(tokens[0]['name'], 'A b c d e f g')
        self.assertIn('>A b c d e f g</a>', md.toc)


if __name__ == '__main__':
    unittest.main()
