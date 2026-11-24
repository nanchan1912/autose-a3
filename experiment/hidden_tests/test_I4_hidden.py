"""Hidden acceptance tests for issue I4 (toc: leave headings with class `no-toc` out of the TOC)."""
import unittest

import markdown


def flatten(tokens):
    for t in tokens:
        yield t
        yield from flatten(t['children'])


def convert(src, **toc_config):
    md = markdown.Markdown(extensions=['toc', 'attr_list'],
                           extension_configs={'toc': toc_config} if toc_config else {})
    html = md.convert(src)
    return md, html


class TestI4Hidden(unittest.TestCase):

    SRC = '# Intro\n\n## Changelog {: .no-toc }\n\n## Usage\n'

    def test_heading_with_class_is_not_in_toc_tokens_or_toc_html(self):
        md, html = convert(self.SRC)
        self.assertEqual([t['name'] for t in flatten(md.toc_tokens)], ['Intro', 'Usage'])
        self.assertEqual([c['name'] for c in md.toc_tokens[0]['children']], ['Usage'])
        self.assertNotIn('#changelog', md.toc)
        self.assertIn('href="#usage"', md.toc)

    def test_excluded_heading_still_gets_id_and_permalink(self):
        md, html = convert(self.SRC, permalink=True)
        self.assertRegex(html, r'<h2[^>]*id="changelog"[^>]*>Changelog<a class="headerlink" href="#changelog"')
        self.assertNotIn('#changelog', md.toc)

    def test_ids_stay_unique_across_excluded_and_included_headings(self):
        md, html = convert('## Usage {: .no-toc }\n\n## Usage\n')
        self.assertIn('id="usage"', html)
        self.assertIn('id="usage_1"', html)
        self.assertEqual([(t['name'], t['id']) for t in flatten(md.toc_tokens)], [('Usage', 'usage_1')])

    def test_other_classes_do_not_exclude_and_class_can_be_combined(self):
        md, html = convert('# A {: .fancy }\n\n# B {: .fancy .no-toc }\n\n# C\n')
        self.assertEqual([t['name'] for t in flatten(md.toc_tokens)], ['A', 'C'])


if __name__ == '__main__':
    unittest.main()
